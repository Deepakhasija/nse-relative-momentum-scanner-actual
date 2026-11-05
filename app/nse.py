"""NSE end-of-day report downloader and tolerant CSV normalizer.

Raw NSE exchange prices are stored unchanged. No corporate-action adjustment is
silently applied. Reports may be unavailable on weekends/holidays or temporarily
blocked; callers must treat a missing report as a skipped date, not zero prices.
"""
from __future__ import annotations
import io, zipfile, time
from datetime import date
from typing import Iterable
import pandas as pd
import requests

BASE = "https://nsearchives.nseindia.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    "Accept": "text/csv,application/zip,application/octet-stream,*/*",
    "Referer": "https://www.nseindia.com/all-reports",
}
SESSION = requests.Session(); SESSION.headers.update(HEADERS)

ALIASES = {
 "symbol": ["TckrSymb", "SYMBOL", "Symbol", "Scrip", "SCRIP"],
 "series": ["SctySrs", "SERIES", "Series"],
 "isin": ["ISIN", "ISINCode", "ISIN Code"],
 "date": ["TradDt", "TIMESTAMP", "TRADE_DATE", "Trade Date", "Date"],
 "open": ["OpnPric", "OPEN", "Open", "Open Price"],
 "high": ["HghPric", "HIGH", "High", "High Price"],
 "low": ["LwPric", "LOW", "Low", "Low Price"],
 "close": ["ClsPric", "CLOSE", "Close", "Closing Price"],
 "volume": ["TtlTradgVol", "TOTTRDQTY", "TOTTRDQTY", "Total Traded Quantity", "Volume"],
 "turnover": ["TtlTrfVal", "TOTTRDVAL", "Total Traded Value", "Turnover"],
}

def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().replace('"','') for c in df.columns]
    return df

def _find_col(df, key, required=True):
    normalized = {str(c).strip().lower(): c for c in df.columns}
    for alias in ALIASES[key]:
        if alias.lower() in normalized: return normalized[alias.lower()]
    if required: raise ValueError(f"NSE report missing {key} column. Found: {list(df.columns)}")
    return None

def _read_csv_bytes(content: bytes) -> pd.DataFrame:
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names=[n for n in zf.namelist() if n.lower().endswith('.csv')]
            if not names: raise ValueError("ZIP contains no CSV")
            with zf.open(names[0]) as f: return _clean_columns(pd.read_csv(f, dtype=str))
    return _clean_columns(pd.read_csv(io.BytesIO(content), dtype=str))

def _download(url: str) -> bytes:
    last=None
    for attempt in range(3):
        try:
            r=SESSION.get(url, timeout=35)
            if r.status_code == 404: raise FileNotFoundError(url)
            r.raise_for_status()
            if not r.content or r.content[:100].lstrip().lower().startswith((b'<!doctype html',b'<html')):
                raise ValueError("NSE returned an HTML page instead of a data file (possible access block)")
            return r.content
        except FileNotFoundError: raise
        except Exception as exc:
            last=exc; time.sleep(1.5*(attempt+1))
    raise RuntimeError(f"NSE download failed: {last}")

def normalize_prices(df: pd.DataFrame, trade_date: date, segment: str) -> pd.DataFrame:
    cols={k:_find_col(df,k,required=(k in ['symbol','close','volume'])) for k in ALIASES}
    out=pd.DataFrame()
    out['symbol']=df[cols['symbol']].astype(str).str.strip().str.upper()
    out['series']=df[cols['series']].astype(str).str.strip().str.upper() if cols['series'] else ('SM' if segment=='SME' else 'EQ')
    out['isin']=df[cols['isin']].astype(str).str.strip().replace({'nan':None,'':None}) if cols['isin'] else None
    for key in ['open','high','low','close','volume','turnover']:
        c=cols[key]
        out[key]=pd.to_numeric(df[c].astype(str).str.replace(',','',regex=False),errors='coerce') if c else None
    out['trade_date']=[trade_date] * len(out)
    out['segment']=segment
    out=out[(out.symbol!='') & out.close.notna() & (out.close>0) & out.volume.notna()]
    out['volume']=out.volume.fillna(0)
    out=out.drop_duplicates(['trade_date','symbol','series'],keep='last')
    return out

def fetch_mainboard(d: date) -> pd.DataFrame:
    ymd=d.strftime('%Y%m%d')
    url=f"{BASE}/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
    return normalize_prices(_read_csv_bytes(_download(url)),d,'MAINBOARD')

def fetch_sme(d: date) -> pd.DataFrame:
    ddmmyyyy=d.strftime('%d%m%Y')
    urls=[f"{BASE}/archives/sme/sme{ddmmyyyy}.csv", f"{BASE}/content/equities/sme{ddmmyyyy}.csv"]
    last=None
    for url in urls:
        try: return normalize_prices(_read_csv_bytes(_download(url)),d,'SME')
        except FileNotFoundError as e: last=e
    raise last or FileNotFoundError("SME report unavailable")

def fetch_nifty500(d: date) -> pd.DataFrame:
    ddmmyyyy=d.strftime('%d%m%Y')
    url=f"{BASE}/content/indices/ind_close_all_{ddmmyyyy}.csv"
    df=_read_csv_bytes(_download(url))
    cols={str(c).strip().lower():c for c in df.columns}
    name=next((cols[k] for k in ['index name','indexname'] if k in cols),None)
    close=next((cols[k] for k in ['closing index value','closingindexvalue','close'] if k in cols),None)
    if not name or not close: raise ValueError(f"Index report schema changed: {list(df.columns)}")
    matched=df[df[name].astype(str).str.strip().str.upper().eq('NIFTY 500')]
    if matched.empty: raise ValueError("NIFTY 500 not present in NSE index close report")
    return pd.DataFrame([{'trade_date':d,'index_name':'NIFTY 500','close':float(pd.to_numeric(matched.iloc[0][close]))}])
