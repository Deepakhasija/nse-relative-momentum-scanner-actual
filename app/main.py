from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="NSE Relative Momentum Scanner", version="0.1.0")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

@app.get("/")
def dashboard():
    return FileResponse(BASE_DIR / "static" / "index.html")

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": "NSE Relative Momentum Scanner",
        "market_data_provider": os.getenv("MARKET_DATA_PROVIDER", "csv_upload"),
        "live_data_enabled": False,
        "message": "Web app is running. Live NSE ingestion must be configured and validated separately."
    }
