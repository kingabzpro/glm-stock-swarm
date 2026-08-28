"""Reusable GLM-5.3-Flash/CrewAI stock research pipeline."""

from __future__ import annotations

import os
import re
import time
import warnings
from collections.abc import Callable

import finnhub
import numpy as np
import pandas as pd
import requests
from crewai import Agent, Crew, LLM, Process, Task
from crewai.tools import tool
from crewai_tools import TavilySearchTool
from dotenv import load_dotenv
from openai import AsyncOpenAI, RateLimitError

REQUIRED_ENV_VARS = ("ZAI_API_KEY", "FINNHUB_API_KEY", "TAVILY_API_KEY")
TICKER_PATTERN = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")
StatusCallback = Callable[[str], None]

load_dotenv()
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
warnings.filterwarnings(
    "ignore",
    message="function callbacks cannot be serialized.*",
    module="pydantic.main",
)


def validate_environment() -> None:
    """Raise a safe error when a required credential is unavailable."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        raise EnvironmentError(
            "Missing required environment variables: " + ", ".join(missing)
        )


def validate_ticker(ticker: str) -> str:
    """Normalize and validate a US-style stock symbol."""
    normalized = ticker.strip().upper()
    if not TICKER_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Enter a valid ticker containing 1-10 letters, numbers, dots, or hyphens."
        )
    return normalized


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Add deterministic moving-average, RSI, and MACD calculations."""
    if frame.empty:
        return frame.copy()

    result = frame.copy()
    result.attrs.update(frame.attrs)
    result["SMA20"] = result["close"].rolling(20).mean()
    result["SMA50"] = result["close"].rolling(50).mean()
    result["SMA200"] = result["close"].rolling(200).mean()

    delta = result["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    result["RSI14"] = 100 - 100 / (1 + avg_gain / avg_loss.replace(0, np.nan))
    result["EMA12"] = result["close"].ewm(span=12, adjust=False).mean()
    result["EMA26"] = result["close"].ewm(span=26, adjust=False).mean()
    result["MACD"] = result["EMA12"] - result["EMA26"]
    return result


class MarketData:
    """Fetch financial facts and calculate technical indicators."""

    def __init__(self) -> None:
        validate_environment()
        self.finnhub = finnhub.Client(api_key=os.environ["FINNHUB_API_KEY"])
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "glm-stock-swarm/1.0"})

    def _finnhub_history(self, ticker: str, days: int) -> pd.DataFrame:
        end = int(time.time())
        start = end - days * 24 * 60 * 60
        response = self.http.get(
            "https://finnhub.io/api/v1/stock/candle",
            params={
                "symbol": ticker,
                "resolution": "D",
                "from": start,
                "to": end,
                "token": os.environ["FINNHUB_API_KEY"],
            },
            timeout=30,
        )
        if response.status_code != 200:
            return pd.DataFrame()
        data = response.json()
        if data.get("s") != "ok":
            return pd.DataFrame()
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(data["t"], unit="s", utc=True).tz_localize(None),
                "open": data["o"],
                "high": data["h"],
                "low": data["l"],
                "close": data["c"],
                "volume": data["v"],
            }
        )
        frame.attrs["source"] = "Finnhub daily candles"
        return frame

    def _yahoo_history(self, ticker: str, days: int) -> pd.DataFrame:
        end = int(time.time())
        start = end - days * 24 * 60 * 60
        response = self.http.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={
                "period1": start,
                "period2": end,
                "interval": "1d",
                "events": "history",
            },
            timeout=30,
        )
        response.raise_for_status()
        chart = response.json().get("chart", {})
        if chart.get("error") or not chart.get("result"):
            raise RuntimeError(f"No historical price data returned for {ticker}.")
        result = chart["result"][0]
        values = result["indicators"]["quote"][0]
        frame = (
            pd.DataFrame(
                {
                    "date": pd.to_datetime(
                        result["timestamp"], unit="s", utc=True
                    ).tz_localize(None),
                    "open": values["open"],
                    "high": values["high"],
                    "low": values["low"],
                    "close": values["close"],
                    "volume": values["volume"],
                }
            )
            .dropna(subset=["close"])
            .sort_values("date")
            .reset_index(drop=True)
        )
        frame.attrs["source"] = (
            "Yahoo public chart fallback (Finnhub candles unavailable)"
        )
        return frame

    def price_history(self, ticker: str, days: int = 450) -> pd.DataFrame:
        frame = self._finnhub_history(ticker, days)
        return frame if not frame.empty else self._yahoo_history(ticker, days)

    @staticmethod
    def _number(value: object, decimals: int = 2) -> str:
        if value is None or pd.isna(value):
            return "N/A"
        return f"{float(value):,.{decimals}f}"

    def fundamentals(self, ticker: str) -> str:
        ticker = validate_ticker(ticker)
        quote = self.finnhub.quote(ticker)
        if not quote or quote.get("c") in (None, 0):
            raise RuntimeError(f"Finnhub returned no current quote for {ticker}.")
        metrics = self.finnhub.company_basic_financials(ticker, "all")
        values = metrics.get("metric", {})
        number = self._number
        return f"""Ticker: {ticker}
Source: Finnhub
Current price: {number(quote.get('c'))}
Previous close: {number(quote.get('pc'))}
Daily change %: {number(quote.get('dp'))}
Day high / low: {number(quote.get('h'))} / {number(quote.get('l'))}
Market cap (USD millions): {number(values.get('marketCapitalization'))}
52-week high / low: {number(values.get('52WeekHigh'))} / {number(values.get('52WeekLow'))}
Normalized annual P/E: {number(values.get('peNormalizedAnnual'))}
Annual P/B: {number(values.get('pbAnnual'))}
Annual P/S: {number(values.get('psAnnual'))}
ROE TTM: {number(values.get('roeTTM'))}
Net margin TTM: {number(values.get('netProfitMarginTTM'))}
Revenue growth TTM YoY: {number(values.get('revenueGrowthTTMYoy'))}
EPS growth TTM YoY: {number(values.get('epsGrowthTTMYoy'))}
Annual debt/equity: {number(values.get('totalDebt/totalEquityAnnual'))}"""

    def technicals(self, ticker: str) -> str:
        ticker = validate_ticker(ticker)
        frame = add_indicators(self.price_history(ticker))
        if len(frame) < 200:
            raise RuntimeError(
                f"Technical analysis requires 200 observations; received {len(frame)}."
            )
        latest = frame.iloc[-1]
        number = self._number
        return f"""Ticker: {ticker}
Source: {frame.attrs.get('source', 'unknown')}
Last market date: {latest['date'].date()}
Close: {number(latest['close'])}
SMA20 / SMA50 / SMA200: {number(latest['SMA20'])} / {number(latest['SMA50'])} / {number(latest['SMA200'])}
RSI14: {number(latest['RSI14'])}
MACD: {number(latest['MACD'])}
20-day return: {number((latest['close'] / frame['close'].iloc[-20] - 1) * 100)}%
50-day return: {number((latest['close'] / frame['close'].iloc[-50] - 1) * 100)}%
Price vs SMA20: {number((latest['close'] / latest['SMA20'] - 1) * 100)}%
Price vs SMA50: {number((latest['close'] / latest['SMA50'] - 1) * 100)}%
Price vs SMA200: {number((latest['close'] / latest['SMA200'] - 1) * 100)}%"""


def _task_callback(status: str, callback: StatusCallback | None):
    if callback is None:
        return None

    def completed(_output: object) -> None:
        callback(status)

    return completed


def _rate_limit_message(exc: RateLimitError) -> str:
    detail = str(exc).lower()
    if "insufficient balance" in detail or "no resource package" in detail:
        return (
            "Z.ai has insufficient balance for this request. Recharge the account "
            "or add a GLM resource package, then try again."
        )
    return "Z.ai rate-limited the request. Wait briefly, then try again."


def build_crew(ticker: str, status: StatusCallback | None = None) -> Crew:
    """Build a fresh four-agent research crew for one ticker."""
    validate_environment()
    ticker = validate_ticker(ticker)
    market_data = MarketData()

    @tool("Get Stock Fundamentals")
    def get_fundamentals(symbol: str) -> str:
        """Get current price and company fundamentals for one stock ticker."""
        return market_data.fundamentals(symbol)

    @tool("Analyze Stock Technicals")
    def get_technicals(symbol: str) -> str:
        """Calculate trends, returns, moving averages, RSI, and MACD."""
        return market_data.technicals(symbol)

    web_search = TavilySearchTool(
        api_key=os.environ["TAVILY_API_KEY"],
        topic="news",
        search_depth="advanced",
        days=30,
        max_results=5,
    )
    llm = LLM(
        model="openai/glm-5.3-flash",
        api_key=os.environ["ZAI_API_KEY"],
        base_url="https://api.z.ai/api/paas/v4/",
        temperature=0.1,
    )

    fundamental_agent = Agent(
        role="Fundamental Analyst",
        goal="Evaluate financial health, growth, profitability, valuation, and risk.",
        backstory=(
            "You are a careful long-term equity analyst. Use the fundamentals tool "
            "and never invent a figure. Treat N/A as missing, not zero."
        ),
        tools=[get_fundamentals],
        llm=llm,
        allow_delegation=False,
        max_iter=4,
        max_retry_limit=0,
        verbose=False,
    )
    technical_agent = Agent(
        role="Technical Analyst",
        goal="Classify the current setup as bullish, bearish, or neutral.",
        backstory=(
            "You interpret indicators calculated by Python. Never guess a market "
            "price or indicator value."
        ),
        tools=[get_technicals],
        llm=llm,
        allow_delegation=False,
        max_iter=4,
        max_retry_limit=0,
        verbose=False,
    )
    news_agent = Agent(
        role="Financial News Analyst",
        goal="Find material recent developments and separate facts from speculation.",
        backstory=(
            "You are a skeptical financial-news researcher. Prioritize primary and "
            "reputable sources, dates, and links."
        ),
        tools=[web_search],
        llm=llm,
        allow_delegation=False,
        max_iter=5,
        max_retry_limit=0,
        verbose=False,
    )
    manager_agent = Agent(
        role="Portfolio Manager",
        goal="Combine the reports into a balanced, evidence-based research signal.",
        backstory=(
            "You lead an equity research team. Weigh bullish and bearish evidence, "
            "use HOLD when evidence is mixed, and never add unsupported facts."
        ),
        llm=llm,
        allow_delegation=False,
        max_iter=4,
        max_retry_limit=0,
        verbose=False,
    )

    fundamental_task = Task(
        description=(
            f"Analyze {ticker}'s growth, profitability, valuation, balance sheet, "
            "and business quality. Use Get Stock Fundamentals. Return a Fundamental "
            "Score from 0-100, strongest positive, biggest risk, and missing data."
        ),
        expected_output=(
            "A concise fundamental assessment with score, evidence, strongest "
            "positive, biggest risk, and missing-data note."
        ),
        agent=fundamental_agent,
        callback=_task_callback("Fundamentals complete - analyzing technicals...", status),
    )
    technical_task = Task(
        description=(
            f"Analyze {ticker}'s technical setup with Analyze Stock Technicals. "
            "Consider SMA20/50/200, RSI14, MACD, returns, and trend. Return a 0-100 "
            "score, signal, trend, momentum, and main risk."
        ),
        expected_output=(
            "A concise technical assessment with score, signal, trend, momentum, "
            "data source, and main risk."
        ),
        agent=technical_agent,
        callback=_task_callback("Technicals complete - researching recent news...", status),
    )
    news_task = Task(
        description=(
            f"Research important news for {ticker}, focusing on the last 30 days: "
            "earnings, guidance, analyst revisions, products, partnerships, M&A, "
            "regulation, lawsuits, management, and industry developments. Use Tavily "
            "Search. Return a 0-100 score, sentiment, catalysts, dates, and URLs."
        ),
        expected_output=(
            "A sourced recent-news assessment with score, sentiment, catalysts, "
            "dates, and clickable URLs."
        ),
        agent=news_agent,
        callback=_task_callback("News complete - portfolio manager is deciding...", status),
    )
    decision_task = Task(
        description=(
            f"Review all specialist reports and make the final educational research "
            f"assessment for {ticker}. Return exactly one signal: BUY, HOLD, or SELL. "
            "Use HOLD when evidence is mixed. Use only the supplied reports."
        ),
        expected_output=(
            "Ticker; Signal; Overall Score /100; Confidence %; component scores; "
            "Bull Case; Bear Case; Main Catalyst; Main Risk; Final Explanation; "
            "Sources; and an educational-not-financial-advice disclaimer."
        ),
        agent=manager_agent,
        context=[fundamental_task, technical_task, news_task],
        callback=_task_callback("Final report complete.", status),
    )

    return Crew(
        agents=[fundamental_agent, technical_agent, news_agent, manager_agent],
        tasks=[fundamental_task, technical_task, news_task, decision_task],
        process=Process.sequential,
        verbose=False,
        tracing=False,
    )


async def analyze_stock(
    ticker: str, status: StatusCallback | None = None
) -> str:
    """Run the stock crew and return its final Markdown report."""
    ticker = validate_ticker(ticker)
    try:
        result = await build_crew(ticker, status).kickoff_async()
    except RateLimitError as exc:
        raise RuntimeError(_rate_limit_message(exc)) from None
    return result.raw


async def answer_follow_up(ticker: str, report: str, question: str) -> str:
    """Answer a user question using only the completed report as evidence."""
    validate_environment()
    ticker = validate_ticker(ticker)
    question = question.strip()
    if not question:
        raise ValueError("Enter a follow-up question.")
    if not report.strip():
        raise ValueError("Run a stock analysis before asking a follow-up question.")

    client = AsyncOpenAI(
        api_key=os.environ["ZAI_API_KEY"],
        base_url="https://api.z.ai/api/paas/v4/",
    )
    try:
        response = await client.chat.completions.create(
            model="glm-5.3-flash",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are the portfolio manager for {ticker}. Answer only from "
                        "the supplied research report. Clearly say when the report does "
                        "not contain enough evidence. Be concise and never present the "
                        "answer as personalized financial advice."
                    ),
                },
                {
                    "role": "user",
                    "content": f"RESEARCH REPORT\n{report}\n\nQUESTION\n{question}",
                },
            ],
            temperature=0.1,
            max_tokens=1200,
        )
    except RateLimitError as exc:
        raise RuntimeError(_rate_limit_message(exc)) from None
    answer = (response.choices[0].message.content or "").strip()
    if not answer:
        raise RuntimeError("GLM-5.3-Flash returned an empty follow-up answer.")
    return answer
