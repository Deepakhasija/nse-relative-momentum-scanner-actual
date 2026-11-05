# NSE Relative Momentum Scanner

A GitHub-ready starter project for the NSE cross-sectional momentum dashboard.

## Current status

- Web dashboard served by FastAPI.
- Existing CSV upload, calculation and export workflow retained in the browser.
- Render deployment configuration included.
- Health endpoint: `/api/health`.
- **Live NSE data ingestion is not enabled yet.** The app does not claim that its data is live.
- Corporate-action adjustment, complete mainboard + SME coverage, and current market-cap reconciliation still need to be implemented and validated before relying on the output.

## Scanner rules currently implemented in the dashboard

- 63-session price return.
- 200-session simple moving average.
- 20-session average turnover based on close × volume.
- Market cap > ₹500 crore.
- Price > ₹10.
- Price > 200 DMA.
- Average turnover > ₹7 crore.
- Top 20 percentile by cross-sectional return rank among eligible stocks.

Percentile is calculated as `(N - rank + 1) / N × 100`, with stocks ranked by descending 3-month return.

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Deploy to Render using GitHub

1. Create a GitHub account at https://github.com if you do not already have one.
2. Create a new **public or private** repository named `nse-relative-momentum-scanner`.
3. Upload the contents of this ZIP to the repository root (not the containing folder).
4. In Render, choose **New → Blueprint** and connect that GitHub repository.
5. Render reads `render.yaml` and creates the web service.
6. Open the generated `onrender.com` URL. Check `/api/health` to confirm the service is running.

## Next engineering phase: reliable NSE data pipeline

Before enabling daily automatic rankings, implement and test:
1. NSE equity security master and separate SME universe ingestion.
2. Daily historical bhavcopy ingestion with sufficient history (target 270–300 sessions).
3. Identifier reconciliation using ISIN/symbol/series and symbol-change handling.
4. Corporate-action adjustment for splits, bonuses and other relevant actions.
5. Latest market-cap source and explicit handling of missing/suspended securities.
6. Data-quality checks, caching and a post-market-close refresh.
7. Protected refresh endpoint or scheduled GitHub Action, with secrets stored in GitHub/Render settings.

Do not enable the scheduled workflow until the data provider and refresh implementation are ready. Public NSE website downloads may have access/session constraints; check NSE data licensing terms before public redistribution or commercial use.

## Project structure

```text
app/
  main.py
  static/
    index.html
.github/workflows/
  daily-refresh.yml
render.yaml
requirements.txt
README.md
```
