from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

import httpx
import numpy as np
import pandas as pd
from openai import RateLimitError
from textual.widgets import Button, Input, Label, Markdown, Static

from stock_swarm import (
    add_indicators,
    analyze_stock,
    build_crew,
    resolve_llm_settings,
    validate_ticker,
)
from tui import StockSwarmApp


class CoreTests(unittest.TestCase):
    def test_validate_ticker_normalizes_symbol(self) -> None:
        self.assertEqual(validate_ticker("  brk.b "), "BRK.B")

    def test_validate_ticker_rejects_unsafe_input(self) -> None:
        with self.assertRaises(ValueError):
            validate_ticker("NVDA; rm")

    def test_indicators_are_calculated(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2025-01-01", periods=250),
                "close": np.linspace(100, 200, 250),
            }
        )
        result = add_indicators(frame)
        self.assertFalse(pd.isna(result.iloc[-1]["SMA200"]))
        self.assertGreater(result.iloc[-1]["MACD"], 0)

    def test_agents_do_not_retry_failed_paid_requests(self) -> None:
        keys = {
            "ZAI_API_KEY": "test-zai",
            "FINNHUB_API_KEY": "test-finnhub",
            "TAVILY_API_KEY": "test-tavily",
        }
        with patch.dict(os.environ, keys):
            crew = build_crew("NVDA")
        self.assertTrue(all(agent.max_retry_limit == 0 for agent in crew.agents))

    def test_standard_zai_endpoint_is_always_selected(self) -> None:
        environment = {"ZAI_API_KEY": "test-zai"}
        with patch.dict(os.environ, environment, clear=True):
            settings = resolve_llm_settings()
        self.assertEqual(settings.base_url, "https://api.z.ai/api/paas/v4/")
        self.assertEqual(settings.api_model, "glm-5.3-flash")
        self.assertEqual(settings.api_key, "test-zai")

    def test_missing_zai_key_explains_standard_api_credit(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(EnvironmentError, r"\$3 API credit"):
                resolve_llm_settings()

    def test_balance_error_is_safe_and_actionable(self) -> None:
        class FailingCrew:
            async def kickoff_async(self):
                request = httpx.Request("POST", "https://api.z.ai/api/paas/v4/")
                response = httpx.Response(429, request=request)
                raise RateLimitError(
                    "Insufficient balance or no resource package.",
                    response=response,
                    body={"code": "1113"},
                )

        with patch("stock_swarm.build_crew", return_value=FailingCrew()):
            with self.assertRaisesRegex(RuntimeError, "insufficient balance"):
                asyncio.run(analyze_stock("NVDA"))


class TuiTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_runs_analysis_and_enables_follow_up(self) -> None:
        app = StockSwarmApp()
        report = "# NVDA\n\n**Signal:** HOLD\n\nEducational research only."

        async def fake_analysis(ticker: str, status) -> str:
            await asyncio.to_thread(status, "Fundamentals complete")
            return report

        with patch("tui.analyze_stock", new=fake_analysis):
            async with app.run_test(size=(72, 20)) as pilot:
                initial_status = app.query_one("#status", Label).render().plain
                self.assertIn("Ready", initial_status)
                self.assertGreaterEqual(app.query_one("#report", Markdown).size.height, 6)
                self.assertEqual(
                    app.query_one("#analyze-button", Button).outer_size.height, 3
                )
                self.assertEqual(app.query_one("#ask-button", Button).outer_size.height, 3)
                ticker = app.query_one("#ticker-input", Input)
                ticker.value = "nvda"
                await pilot.click("#analyze-button")
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()

                self.assertEqual(app.current_ticker, "NVDA")
                self.assertEqual(app.current_report, report)
                self.assertFalse(app.query_one("#ask-button", Button).disabled)
                agent_track = app.query_one("#agent-track", Static)
                self.assertTrue(agent_track.display)
                self.assertIn("Decision", agent_track.render().plain)
                status_text = app.query_one("#status", Label).render()
                self.assertIn("report complete", status_text.plain)
                self.assertIsInstance(app.query_one("#report", Markdown), Markdown)

                app.analysis_active = True
                app.agent_stage = 1
                app._set_busy(True)
                app._animate_busy()
                animated_label = str(app.query_one("#analyze-button", Button).label)
                self.assertIn("Analyze", animated_label)
                self.assertNotEqual(animated_label, "Analyze")
                self.assertIn("Technicals", agent_track.render().plain)
                app._set_busy(False)
                app.analysis_active = False


if __name__ == "__main__":
    unittest.main()
