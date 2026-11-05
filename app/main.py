from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy import text, select, func
from datetime import date
import csv, io, os
from .db import engine, SessionLocal
from .models import Base, DailyPrice, Security, IngestionRun
from .scanner import scan
from .ingestion import parse_report, persist_report

BASE_DIR=Path(__file__).resolve().parent
app=FastAPI(title='NSE Relative Momentum Scanner',version='0.2.0')
app.mount('/static',StaticFiles(directory=BASE_DIR/'static'),name='static')

@app.on_event('startup')
def startup():
    if engine is not None: Base.metadata.create_all(engine)

@app.get('/')
def dashboard(): return FileResponse(BASE_DIR/'static'/'index.html')

@app.get('/api/health')
def health():
    db='not_configured'
    if engine is not None:
        try:
            with engine.connect() as c: c.execute(text('SELECT 1'))
            db='connected'
        except Exception: db='error'
    has_data=False
    if db=='connected':
        try:
            with SessionLocal() as s: has_data=(s.query(func.count(DailyPrice.id)).scalar() or 0)>0
        except Exception: pass
    return {'status':'ok' if db in ('connected','not_configured') else 'degraded','app':'NSE Relative Momentum Scanner','database':db,'live_data_enabled':has_data,'market_data_provider':'NSE EOD reports','message':'Raw NSE EOD prices are stored; market-cap and corporate-action data require separate validated inputs.'}

@app.get('/api/status')
def status():
    if SessionLocal is None: return {'database':'not_configured','price_rows':0,'symbols':0,'latest_date':None,'last_run':None}
    with SessionLocal() as s:
        return {'database':'connected','price_rows':s.query(func.count(DailyPrice.id)).scalar() or 0,'symbols':s.query(func.count(func.distinct(DailyPrice.symbol))).scalar() or 0,'latest_date':s.query(func.max(DailyPrice.trade_date)).scalar(),'last_run':s.query(IngestionRun).order_by(IngestionRun.id.desc()).first().status if s.query(IngestionRun).count() else None}

@app.post('/api/ingest/upload')
async def ingest_upload(
    file: UploadFile = File(...),
    segment: str = Query("MAINBOARD", pattern="^(MAINBOARD|SME)$"),
):
    """Upload one NSE daily CM-UDiFF or SME bhavcopy CSV/ZIP into Neon."""
    if SessionLocal is None:
        raise HTTPException(503, "DATABASE_URL is not configured")
    filename = file.filename or "nse-report.csv"
    if not filename.lower().endswith((".csv", ".zip")):
        raise HTTPException(400, "Upload a CSV or ZIP report")
    payload = await file.read()
    if not payload:
        raise HTTPException(400, "Uploaded file is empty")
    try:
        records, rejected, trade_date = parse_report(payload, filename, segment)
        result = persist_report(records, filename, rejected)
        result["segment"] = segment
        return result
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))

@app.get('/api/scanner')
def scanner(min_cap:float=500,min_price:float=10,min_turnover:float=7,percentile:float=80):
    try: return scan(min_cap,min_price,min_turnover,percentile)
    except Exception as e: raise HTTPException(status_code=503,detail=str(e))

@app.get('/api/history.csv')
def history_csv():
    if SessionLocal is None: raise HTTPException(503,'DATABASE_URL is not configured')
    output=io.StringIO(); w=csv.writer(output); w.writerow(['symbol','date','close','volume','market_cap_cr'])
    with SessionLocal() as s:
        rows=s.execute(select(DailyPrice,Security).join(Security,DailyPrice.symbol==Security.symbol).order_by(DailyPrice.trade_date)).all()
        for p,sec in rows: w.writerow([p.symbol,p.trade_date.isoformat(),p.close,p.volume,sec.market_cap_cr or ''])
    return StreamingResponse(iter([output.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=nse_history.csv'})
