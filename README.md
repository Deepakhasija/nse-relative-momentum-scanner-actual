# NSE Relative Momentum Scanner

A GitHub-ready starter project for the NSE cross-sectional momentum dashboard.

## Current status

- Web dashboard served by FastAPI.
- Existing CSV upload, calculation and export workflow retained in the browser.
- Render deployment configuration included.
- Health endpoint: `/api/health`.
- Manual NSE EOD CSV/ZIP ingestion endpoint is available on the feature branch; automated historical backfill and scheduled refresh are not enabled.
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

## Manual EOD ingestion (feature branch)

The API accepts one single-date NSE CM-UDiFF Common Bhavcopy Final ZIP/CSV or SME Bhavcopy CSV per upload. It parses EQ rows, validates the trade date and price/volume fields, upserts daily prices into Neon, and records an ingestion run. It creates security master placeholders only; it does not fabricate market capitalisation.

1. Set `NSE_INGEST_TOKEN` as a secret environment variable in Render (use a long random value).
2. Deploy the feature branch to a staging Render service, not the production service.
3. Open `/docs`, select `POST /api/ingest/upload`, choose segment `MAINBOARD` for CM-UDiFF or `SME` for the SME report, and attach the report file.
4. Add the header `X-Ingest-Token` with the same secret.
5. Verify `/api/status` and the response's trade date, stored rows and rejected rows.

The ingestion route returns 503 until the server token is configured and rejects unauthorised requests. Never commit the token to GitHub or put it in frontend JavaScript. Current parser supports header aliases for common UDiFF and legacy SME fields; validate each new report variant before bulk loading. The database currently stores unadjusted bhavcopy closes, so split/bonus adjustments remain a separate required step before trusting long lookbacks.

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
