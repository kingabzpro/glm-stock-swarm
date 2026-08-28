# GLM Stock Swarm

A local terminal app and Jupyter notebook that use GLM-5.3-Flash with CrewAI to coordinate fundamental, technical, news, and portfolio-manager agents.

## Setup

The required environment variables have already been added to the environment:

- `ZAI_API_KEY`
- `FINNHUB_API_KEY`
- `TAVILY_API_KEY`

### Z.ai endpoint and GLM Coding Plan

This stock-analysis application uses Z.ai's general API endpoint:

```text
https://api.z.ai/api/paas/v4/
```

The GLM Coding Plan has a separate endpoint, `https://api.z.ai/api/coding/paas/v4`, but Z.ai limits that subscription quota to supported coding tools and coding scenarios. A stock-research application is not a coding workload, so this project intentionally does **not** route stock analyses through the Coding Plan endpoint. Running the TUI requires prepaid balance or an appropriate model resource package for the general API.

Official references: [GLM Coding Plan quick start](https://docs.z.ai/devpack/quick-start), [supported tool policy](https://docs.z.ai/devpack/tool/others), and [GLM-5.3-Flash overview](https://docs.z.ai/guides/vlm/glm-5.3-flash).

Create the local environment and install the pinned packages:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Interactive terminal app

Start the TUI locally:

```powershell
python tui.py
```

Enter a ticker and select **Run research**. When the report finishes, use the second input to ask grounded follow-up questions. Shortcuts are `Ctrl+R` to research, `Ctrl+L` to clear, and `Ctrl+Q` to quit.

## Notebook

```powershell
jupyter notebook stock_analyst_crew.ipynb
```

Run all cells. The notebook defaults to `NVDA`; set `STOCK_TICKER` before launching Jupyter to use another symbol.

Finnhub supplies quotes and fundamentals. The notebook tries Finnhub for daily candles first and, when the account tier rejects that endpoint, falls back to Yahoo's public chart response so the technical analysis can still run. Tavily supplies current news, while GLM interprets the collected evidence.

> Educational research only. The generated BUY/HOLD/SELL signal is not financial advice.

## Tests

```powershell
python -m unittest discover -s tests -v
```
