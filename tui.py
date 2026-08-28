"""Interactive terminal UI for the GLM Stock Swarm."""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    Markdown,
    Static,
)

from stock_swarm import analyze_stock, answer_follow_up, validate_ticker


class StockSwarmApp(App[None]):
    """Research stocks and discuss each report from the terminal."""

    TITLE = "GLM Stock Swarm"
    SUB_TITLE = "GLM-5.3-Flash · CrewAI · Finnhub · Tavily"

    CSS = """
    Screen {
        background: #08111f;
        color: #d9e7ff;
    }

    Header {
        background: #0c1c33;
        color: #80d8ff;
    }

    #app-title {
        text-style: bold;
        color: #80d8ff;
        padding: 1 2 0 2;
    }

    #tagline {
        color: #8fa9c9;
        padding: 0 2 1 2;
    }

    .control-row {
        height: 3;
        margin: 0 2;
    }

    Input {
        border: tall #284b75;
        background: #0c1c33;
    }

    Input:focus {
        border: tall #45c4ff;
    }

    #ticker-input {
        width: 1fr;
        margin-right: 1;
    }

    #question-input {
        width: 1fr;
        margin-right: 1;
    }

    Button {
        min-width: 16;
        background: #146c94;
        color: white;
        border: none;
    }

    Button:hover {
        background: #1f95c8;
    }

    #status-row {
        height: 3;
        margin: 0 2;
        padding: 0 1;
        background: #0c1c33;
        border: round #284b75;
        content-align: left middle;
    }

    #status {
        width: 1fr;
        color: #9ec5ef;
    }

    #spinner {
        display: none;
        width: 5;
        height: 1;
    }

    #report {
        height: 1fr;
        margin: 1 2;
        padding: 1 2;
        background: #0a1729;
        border: round #284b75;
        overflow-y: auto;
    }

    #disclaimer {
        height: 2;
        color: #718aa8;
        content-align: center middle;
    }

    Footer {
        background: #0c1c33;
    }
    """

    BINDINGS = [
        ("ctrl+r", "analyze", "Research"),
        ("ctrl+l", "clear", "Clear"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current_ticker = ""
        self.current_report = ""
        self.conversation = ""
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Multi-Agent Stock Analyst", id="app-title")
        yield Static(
            "Fundamentals + technicals + current news → evidence-based signal",
            id="tagline",
        )
        with Horizontal(classes="control-row"):
            yield Input(
                value="NVDA",
                placeholder="Ticker, for example NVDA",
                id="ticker-input",
                max_length=10,
            )
            yield Button("Run research", id="analyze-button", variant="primary")
        with Horizontal(id="status-row"):
            yield Label("Ready. Enter a ticker and run the research crew.", id="status")
            yield LoadingIndicator(id="spinner")
        yield Markdown(
            "# Ready\n\nEnter a ticker above to start the four-agent analysis.",
            id="report",
        )
        with Horizontal(classes="control-row"):
            yield Input(
                placeholder="Ask a follow-up about the completed report",
                id="question-input",
                disabled=True,
            )
            yield Button("Ask GLM", id="ask-button", disabled=True)
        yield Static(
            "Educational research only · Not financial advice", id="disclaimer"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#ticker-input", Input).focus()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.query_one("#analyze-button", Button).disabled = busy
        self.query_one("#ticker-input", Input).disabled = busy
        self.query_one("#ask-button", Button).disabled = busy or not bool(
            self.current_report
        )
        self.query_one("#question-input", Input).disabled = busy or not bool(
            self.current_report
        )
        self.query_one("#spinner", LoadingIndicator).display = busy

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Label).update(message)

    def _requested_ticker(self) -> str | None:
        try:
            return validate_ticker(self.query_one("#ticker-input", Input).value)
        except ValueError as exc:
            self._set_status(f"Input error: {exc}")
            self.notify(str(exc), severity="error")
            return None

    def action_analyze(self) -> None:
        ticker = self._requested_ticker()
        if ticker:
            self.run_analysis(ticker)

    @on(Button.Pressed, "#analyze-button")
    def analyze_button_pressed(self) -> None:
        self.action_analyze()

    @on(Input.Submitted, "#ticker-input")
    def ticker_submitted(self) -> None:
        self.action_analyze()

    @work(exclusive=True, group="analysis", exit_on_error=False)
    async def run_analysis(self, ticker: str) -> None:
        self._set_busy(True)
        self.current_ticker = ticker
        self.current_report = ""
        self.conversation = ""
        await self.query_one("#report", Markdown).update(
            f"# Researching {ticker}\n\nThe four-agent crew is collecting evidence…"
        )
        try:
            self._set_status(f"Building the {ticker} research crew...")
            report = await analyze_stock(
                ticker,
                lambda message: self.call_from_thread(self._set_status, message),
            )
            self.current_report = report
            await self.query_one("#report", Markdown).update(report)
            self._set_status(f"{ticker} report complete. You can ask a follow-up.")
            self.notify(f"{ticker} research complete", title="GLM Stock Swarm")
        except Exception as exc:
            self._set_status(f"Analysis failed: {exc}")
            await self.query_one("#report", Markdown).update(
                "# Analysis failed\n\n"
                f"{exc}\n\nCheck the API variables and your network connection."
            )
            self.notify(str(exc), severity="error", title="Analysis failed")
        finally:
            self._set_busy(False)

    def _ask_question(self) -> None:
        question = self.query_one("#question-input", Input).value.strip()
        if not question:
            self._set_status("Enter a follow-up question first.")
            return
        self.run_follow_up(question)

    @on(Button.Pressed, "#ask-button")
    def ask_button_pressed(self) -> None:
        self._ask_question()

    @on(Input.Submitted, "#question-input")
    def question_submitted(self) -> None:
        self._ask_question()

    @work(exclusive=True, group="follow-up", exit_on_error=False)
    async def run_follow_up(self, question: str) -> None:
        self._set_busy(True)
        self._set_status("GLM-5.3-Flash is reviewing the report…")
        try:
            answer = await answer_follow_up(
                self.current_ticker, self.current_report, question
            )
            self.conversation += (
                f"\n\n---\n\n### You\n\n{question}\n\n"
                f"### Portfolio Manager\n\n{answer}"
            )
            await self.query_one("#report", Markdown).update(
                self.current_report + self.conversation
            )
            self.query_one("#question-input", Input).value = ""
            self._set_status("Follow-up answered. Ask another question or run a new ticker.")
        except Exception as exc:
            self._set_status(f"Follow-up failed: {exc}")
            self.notify(str(exc), severity="error", title="Follow-up failed")
        finally:
            self._set_busy(False)

    async def action_clear(self) -> None:
        if self.busy:
            self._set_status("Wait for the current request to finish before clearing.")
            return
        self.current_ticker = ""
        self.current_report = ""
        self.conversation = ""
        self.query_one("#question-input", Input).value = ""
        await self.query_one("#report", Markdown).update(
            "# Ready\n\nEnter a ticker above to start the four-agent analysis."
        )
        self._set_busy(False)
        self._set_status("Cleared. Ready for a new ticker.")
        self.query_one("#ticker-input", Input).focus()


def main() -> None:
    StockSwarmApp().run()


if __name__ == "__main__":
    main()
