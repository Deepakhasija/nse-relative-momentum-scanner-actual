"""Parsers and database persistence for NSE cash-market EOD files.

Supports NSE CM-UDiFF ZIP (mainboard EQ series) and NSE SME CSV reports.
Market capitalisation is intentionally not inferred from bhavcopy.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from .db import SessionLocal
from .models import DailyPrice, Security, IngestionRun


ALIASES = {
    "symbol": ("TckrSymb", "SYMBOL", "Symbol", "Security", "SctySymb"),
    "series": ("SctySrs", "SERIES", "Series"),
    "isin": ("ISIN", "Isin", "ISINCode"),
    "date": ("TradDt", "TIMESTAMP", "TRADE_DATE", "TradeDate", "BizDt", "DATE"),
    "open": ("OpnPric", "OPEN", "Open", "OPEN_PRICE"),
    "high": ("HghPric", "HIGH", "High", "HIGH_PRICE"),
    "low": ("LwPric", "LOW", "Low", "LOW_PRICE"),
    "close": ("ClsPric", "CLOSE", "Close", "CLOSE_PRICE"),
    "volume": ("TtlTradgVol", "TOTTRDQTY", "TOTTRD QTY", "TOTAL TRADED QUANTITY", "Volume", "NET_TRDQTY"),
    "turnover": ("TtlTrfVal", "TOTTRDVAL", "TOTAL TRADED VALUE", "Turnover", "NET_TRDVAL"),
    "company_name": ("FinInstrmNm", "SECURITY", "COMPANY_NAME"),
}


def _key(value: str) -> str:
    return "".join(ch.lower() for ch in str(value).strip() if ch.isalnum())


def _pick(row: dict[str, Any], aliases: tuple[str, ...], required: bool = False):
    normalized = {_key(k): v for k, v in row.items()}
    for alias in aliases:
        value = normalized.get(_key(alias))
        if value is not None and str(value).strip() != "":
            return value
    if required:
        raise ValueError(f"Missing required column; expected one of: {', '.join(aliases)}")
    return None


def _number(value, required=False):
    if value is None or str(value).strip() in ("", "-", "NA", "N/A"):
        if required:
            raise ValueError("Required numeric value is blank")
        return None
    number = float(str(value).replace(",", "").strip())
    return number


def _date(value) -> date:
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d", "%d%m%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported trade date: {raw}")


def _filename_date(filename: str) -> date | None:
    # NSE SME filenames use smeDDMMYYYY.csv; CM UDiFF filenames use YYYYMMDD.
    match = re.search(r"(?<!\\d)(\\d{8})(?!\\d)", filename)
    if not match:
        return None
    token = match.group(1)
    for fmt in ("%Y%m%d", "%d%m%Y"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def _csv_rows(payload: bytes, filename: str):
    if filename.lower().endswith(".zip") or payload[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            candidates = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if len(candidates) != 1:
                raise ValueError(f"Expected exactly one CSV in ZIP; found {len(candidates)}")
            raw = archive.read(candidates[0])
    else:
        raw = payload
    text = raw.decode("utf-8-sig", errors="strict")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    return list(reader)


def parse_report(payload: bytes, filename: str, segment: str):
    segment = segment.upper()
    if segment not in ("MAINBOARD", "SME"):
        raise ValueError("segment must be MAINBOARD or SME")
    rows = _csv_rows(payload, filename)
    parsed, rejected = [], []
    seen = set()
    filename_trade_date = _filename_date(filename)

    for line_no, row in enumerate(rows, start=2):
        try:
            symbol = str(_pick(row, ALIASES["symbol"], True)).strip().upper()
            series = str(_pick(row, ALIASES["series"]) or ("EQ" if segment == "MAINBOARD" else "")).strip().upper()
            if segment == "MAINBOARD" and series != "EQ":
                continue
            if segment == "SME" and series not in ("SM", "ST", "SZ"):
                raise ValueError(f"Unsupported SME series: {series or '(blank)'}")

            raw_date = _pick(row, ALIASES["date"])
            if raw_date:
                trade_date = _date(raw_date)
            elif filename_trade_date:
                trade_date = filename_trade_date
            else:
                raise ValueError("Trade date missing from row and filename")

            close = _number(_pick(row, ALIASES["close"], True), True)
            volume = _number(_pick(row, ALIASES["volume"], True), True)
            if close <= 0 or volume < 0:
                raise ValueError("Close must be positive and volume cannot be negative")
            open_price = _number(_pick(row, ALIASES["open"]))
            high = _number(_pick(row, ALIASES["high"]))
            low = _number(_pick(row, ALIASES["low"]))
            if high is not None and low is not None and high < low:
                raise ValueError("High price is below low price")

            row_key = (trade_date, symbol, series)
            if row_key in seen:
                raise ValueError(f"Duplicate symbol/series/date: {symbol}/{series}/{trade_date}")
            seen.add(row_key)
            parsed.append({
                "trade_date": trade_date, "symbol": symbol, "series": series,
                "isin": _pick(row, ALIASES["isin"]),
                "company_name": _pick(row, ALIASES["company_name"]),
                "segment": segment,
                "open": open_price, "high": high, "low": low,
                "close": close, "volume": volume,
                "turnover_rupees": _number(_pick(row, ALIASES["turnover"])),
            })
        except Exception as exc:
            rejected.append({"line": line_no, "reason": str(exc)})

    if not parsed:
        sample_headers = ", ".join(rows[0].keys()) if rows else "no data rows"
        raise ValueError(f"No valid rows parsed. CSV headers: {sample_headers}")
    dates = {item["trade_date"] for item in parsed}
    if len(dates) != 1:
        raise ValueError(f"Report must contain exactly one trade date; found {len(dates)}")
    report_date = next(iter(dates))
    if report_date > date.today():
        raise ValueError("Report trade date is in the future")
    if filename_trade_date and filename_trade_date != report_date:
        raise ValueError(f"Filename date {filename_trade_date} does not match report date {report_date}")
    return parsed, rejected, report_date


def persist_report(records, filename: str, rejected):
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is not configured")
    trade_date = records[0]["trade_date"]
    segment = records[0]["segment"]
    run = IngestionRun(trade_date=trade_date, status="running", message=f"File: {filename}")
    with SessionLocal() as session:
        session.add(run)
        session.flush()
        try:
            price_records = []
            for record in records:
                symbol = record["symbol"]
                security = session.get(Security, symbol)
                if security is None:
                    security = Security(symbol=symbol, isin=record["isin"], series=record["series"], segment=segment)
                    session.add(security)
                else:
                    if record["isin"]:
                        security.isin = record["isin"]
                    if record.get("company_name"):
                        security.company_name = str(record["company_name"]).strip()
                    security.series = record["series"]
                    security.segment = segment
                if record.get("company_name") and security.company_name is None:
                    security.company_name = str(record["company_name"]).strip()
                price_records.append({k: v for k, v in record.items() if k != "company_name"})

            session.flush()
            # Keep each INSERT comfortably below PostgreSQL's bind-parameter limit.
            for offset in range(0, len(price_records), 500):
                batch = price_records[offset:offset + 500]
                stmt = pg_insert(DailyPrice).values(batch)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_daily_price",
                    set_={
                        "isin": stmt.excluded.isin, "segment": stmt.excluded.segment,
                        "open": stmt.excluded.open, "high": stmt.excluded.high,
                        "low": stmt.excluded.low, "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                        "turnover_rupees": stmt.excluded.turnover_rupees,
                    },
                )
                session.execute(stmt)

            run.status = "success"
            run.mainboard_rows = len(records) if segment == "MAINBOARD" else 0
            run.sme_rows = len(records) if segment == "SME" else 0
            run.message = f"{filename}: {len(records)} rows stored; {len(rejected)} rows rejected"
            run.finished_at = datetime.utcnow()
            session.commit()
        except Exception as exc:
            session.rollback()
            raise RuntimeError(f"Database ingestion failed: {exc}") from exc
    return {
        "trade_date": trade_date.isoformat(), "rows_stored": len(records),
        "rows_rejected": len(rejected), "rejected_sample": rejected[:20], "status": "success",
    }
