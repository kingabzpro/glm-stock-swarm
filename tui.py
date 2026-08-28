"""Interactive terminal UI for the GLM Stock Swarm."""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.timer import Timer
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

from stock_swarm import (
    analyze_stock,
    answer_follow_up,
    validate_environment,
    validate_ticker,
)


class StockSwarmApp(App[None]):
    """Research stocks and discuss each report from the terminal."""

    TITLE = "GLM Stock Swarm"
    SUB_TITLE = ""

    CSS = """
    Screen {
        background: #08111f;
        color: #d9e7ff;
    }

    Header {
        background: #0c1c33;
        color: #80d8ff;
    }

    .control-row {
        height: 3;
        margin: 0 1;
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
        width: 12;
        min-width: 12;
        height: 3;
        margin-left: 1;
        background: #146c94;
        color: white;
        border: tall #2498c7;
        content-align: center middle;
        text-style: bold;
    }

    Button:hover {
        background: #1f95c8;
        border: tall #80d8ff;
    }

    Button:disabled {
        background: #102a40;
        color: #58738d;
        border: tall #183b57;
    }

    #status-row {
        height: 1;
        margin: 0 1;
        content-align: left middle;
    }

    #status {
        width: 1fr;
        color: #9ec5ef;
    }

    #spinner {
        display: none;
        width: 4;
        height: 1;
    }

    #agent-track {
        display: none;
        height: 1;
        margin: 0 1;
        color: #8fa9c9;
        content-align: left middle;
    }

    #report {
        height: 1fr;
        margin: 0 1;
        padding: 0 1;
        background: #0a1729;
        border: solid #284b75;
        overflow-y: auto;
    }

    #disclaimer {
        height: 1;
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
        self.analysis_active = False
        self.agent_stage = 0
        self.animation_frame = 0
        self.animation_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(classes="control-row"):
            yield Input(
                value="NVDA",
                placeholder="Ticker (NVDA)",
                id="ticker-input",
                max_length=10,
            )
            yield Button("Analyze", id="analyze-button", variant="primary")
        with Horizontal(id="status-row"):
            yield Label("Ready · Enter a ticker and press Analyze", id="status")
            yield LoadingIndicator(id="spinner")
        yield Static("", id="agent-track")
        yield Markdown(
            "**Ready.** Enter a ticker to start the four-agent analysis.",
            id="report",
        )
        with Horizontal(classes="control-row"):
            yield Input(
                placeholder="Ask about this report",
                id="question-input",
                disabled=True,
            )
            yield Button("Ask", id="ask-button", disabled=True)
        yield Static("Research only · Not financial advice", id="disclaimer")
        yield Footer()

    def on_mount(self) -> None:
        try:
            validate_environment()
            self._set_status("Ready · Enter a ticker and press Analyze")
        except (EnvironmentError, ValueError) as exc:
            self._set_status(f"Configuration error: {exc}")
        self.animation_timer = self.set_interval(
            0.35, self._animate_busy, pause=True
        )
        self.query_one("#ticker-input", Input).focus()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        analyze_button = self.query_one("#analyze-button", Button)
        analyze_button.disabled = busy
        self.query_one("#ticker-input", Input).disabled = busy
        self.query_one("#ask-button", Button).disabled = busy or not bool(
            self.current_report
        )
        self.query_one("#question-input", Input).disabled = busy or not bool(
            self.current_report
        )
        self.query_one("#spinner", LoadingIndicator).display = busy
        if busy:
            self.animation_frame = 0
            if self.animation_timer:
                self.animation_timer.resume()
        else:
            analyze_button.label = "Analyze"
            self.query_one("#ask-button", Button).label = "Ask"
            if self.animation_timer:
                self.animation_timer.pause()

    def _animate_busy(self) -> None:
        if not self.busy:
            return
        self.animation_frame = (self.animation_frame + 1) % 4
        spinner = ("◐", "◓", "◑", "◒")[self.animation_frame]
        if self.analysis_active:
            self.query_one("#analyze-button", Button).label = f"Analyze {spinner}"
            self._render_agent_track()
        else:
            self.query_one("#ask-button", Button).label = f"Ask {spinner}"

    def _render_agent_track(self) -> None:
        track = self.query_one("#agent-track", Static)
        labels = ("Fundamentals", "Technicals", "News", "Decision")
        active_icons = ("◉", "◎")
        parts = []
        for index, label in enumerate(labels):
            if index < self.agent_stage:
                parts.append(f"[green]●[/] {label}")
            elif index == self.agent_stage and self.agent_stage < len(labels):
                icon = active_icons[self.animation_frame % len(active_icons)]
                parts.append(f"[bold cyan]{icon} {label}[/]")
            else:
                parts.append(f"[dim]○ {label}[/]")
        track.update("  ".join(parts))
        track.display = True

    def _agent_status(self, message: str) -> None:
        self._set_status(message)
        if message.startswith("Fundamentals complete"):
            self.agent_stage = 1
        elif message.startswith("Technicals complete"):
            self.agent_stage = 2
        elif message.startswith("News complete"):
            self.agent_stage = 3
        elif message.startswith("Final report complete"):
            self.agent_stage = 4
        self._render_agent_track()

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
        self.analysis_active = True
        self.agent_stage = 0
        self._set_busy(True)
        self._render_agent_track()
        self.current_ticker = ticker
        self.current_report = ""
        self.conversation = ""
        await self.query_one("#report", Markdown).update(
            f"## Researching {ticker}\n\nCollecting fundamentals, technicals, and news…"
        )
        try:
            self._set_status(f"Building the {ticker} research crew...")
            report = await analyze_stock(
                ticker,
                lambda message: self.call_from_thread(self._agent_status, message),
            )
            self.current_report = report
            self.agent_stage = 4
            self._render_agent_track()
            await self.query_one("#report", Markdown).update(report)
            self._set_status(f"{ticker} report complete. You can ask a follow-up.")
            self.notify(f"{ticker} research complete", title="GLM Stock Swarm")
        except Exception as exc:
            self._set_status(f"Analysis failed: {exc}")
            self.query_one("#agent-track", Static).update(
                "[red]● Analysis stopped[/]"
            )
            await self.query_one("#report", Markdown).update(
                "# Analysis failed\n\n"
                f"{exc}\n\nCheck the API variables and your network connection."
            )
            self.notify(str(exc), severity="error", title="Analysis failed")
        finally:
            self._set_busy(False)
            self.analysis_active = False

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
        self.analysis_active = False
        self._set_busy(True)
        self.query_one("#ask-button", Button).label = "Ask ◐"
        self._set_status("Reviewing the report…")
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
        self.query_one("#agent-track", Static).display = False
        await self.query_one("#report", Markdown).update(
            "**Ready.** Enter a ticker to start the four-agent analysis."
        )
        self._set_busy(False)
        self._set_status("Cleared · Enter a ticker and press Analyze")
        self.query_one("#ticker-input", Input).focus()


def main() -> None:
    StockSwarmApp().run()


if __name__ == "__main__":
    main()
