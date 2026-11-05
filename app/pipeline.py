from __future__ import annotations
import argparse, logging, time
from datetime import date, datetime, timedelta, timezone
import pandas as pd
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert
from .db import Base, SessionLocal, require_database
from .models import DailyPrice, Security, BenchmarkPrice, IngestionRun
from .nse import fetch_mainboard, fetch_sme, fetch_nifty500

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log=logging.getLogger('nse-pipeline')

def init_db():
    engine=require_database(); Base.metadata.create_all(engine)

def _upsert_prices(session, df):
    if df.empty: return 0
    records=[]
    for r in df.to_dict('records'):
        records.append({
            'trade_date':r['trade_date'],'symbol':r['symbol'],'series':r['series'],
            'isin':r['isin'],'segment':r['segment'],'open':None if pd.isna(r['open']) else r['open'],
            'high':None if pd.isna(r['high']) else r['high'],'low':None if pd.isna(r['low']) else r['low'],
            'close':float(r['close']),'volume':float(r['volume']),
            'turnover_rupees':None if pd.isna(r['turnover']) else float(r['turnover'])})
    stmt=insert(DailyPrice).values(records)
    stmt=stmt.on_conflict_do_update(constraint='uq_daily_price',set_={k:getattr(stmt.excluded,k) for k in ['isin','segment','open','high','low','close','volume','turnover_rupees']})
    session.execute(stmt)
    # Refresh security identity metadata without overwriting cap data.
    sec=[]
    for r in df[['symbol','isin','series','segment']].drop_duplicates('symbol').to_dict('records'):
        sec.append({'symbol':r['symbol'],'isin':r['isin'],'series':r['series'],'segment':r['segment']})
    if sec:
        sec_stmt=insert(Security).values(sec)
        sec_stmt=sec_stmt.on_conflict_do_update(index_elements=['symbol'],set_={'isin':sec_stmt.excluded.isin,'series':sec_stmt.excluded.series,'segment':sec_stmt.excluded.segment})
        session.execute(sec_stmt)
    return len(records)

def ingest_date(d: date):
    init_db(); started=datetime.now(timezone.utc)
    with SessionLocal() as session:
        run=IngestionRun(trade_date=d,status='RUNNING'); session.add(run); session.commit()
        main=sme=bench=0; errors=[]
        for name,fn in [('mainboard',fetch_mainboard),('sme',fetch_sme)]:
            try:
                df=fn(d); n=_upsert_prices(session,df)
                if name=='mainboard': main=n
                else: sme=n
                log.info('%s %s: %s rows',name,d,n)
            except FileNotFoundError:
                log.info('%s report not published for %s',name,d)
            except Exception as e:
                errors.append(f'{name}: {e}'); log.exception('%s ingestion failed',name)
        try:
            b=fetch_nifty500(d)
            stmt=insert(BenchmarkPrice).values(b.to_dict('records')).on_conflict_do_update(index_elements=['trade_date','index_name'],set_={'close':insert(BenchmarkPrice).excluded.close})
            session.execute(stmt); bench=len(b)
        except FileNotFoundError: log.info('Index report unavailable for %s',d)
        except Exception as e: errors.append(f'benchmark: {e}'); log.exception('Benchmark ingestion failed')
        run.status='PARTIAL' if errors else ('SUCCESS' if main+sme+bench else 'NO_DATA')
        run.mainboard_rows=main; run.sme_rows=sme; run.benchmark_rows=bench
        run.message='; '.join(errors)[:990] if errors else None
        run.finished_at=datetime.now(timezone.utc)
        session.commit()
        return {'date':d.isoformat(),'mainboard_rows':main,'sme_rows':sme,'benchmark_rows':bench,'status':run.status,'errors':errors}

def backfill(days:int=460, end:date|None=None):
    end=end or date.today(); start=end-timedelta(days=days)
    cur=start; summary=[]
    while cur<=end:
        if cur.weekday()<5:
            try: summary.append(ingest_date(cur))
            except Exception as e: log.exception('Date failed %s: %s',cur,e)
            time.sleep(0.35)
        cur+=timedelta(days=1)
    return summary

def import_market_caps(path:str, as_of:date):
    """CSV columns: symbol,market_cap_cr. Cap is current/as-of supplied date."""
    df=pd.read_csv(path,dtype={'symbol':str})
    required={'symbol','market_cap_cr'}
    if not required.issubset({c.strip().lower() for c in df.columns}): raise ValueError('CSV requires symbol,market_cap_cr columns')
    df.columns=[c.strip().lower() for c in df.columns]
    init_db()
    with SessionLocal() as s:
        for r in df.to_dict('records'):
            symbol=str(r['symbol']).strip().upper(); cap=pd.to_numeric(r['market_cap_cr'],errors='coerce')
            if symbol and pd.notna(cap) and cap>0:
                obj=s.get(Security,symbol)
                if obj is None: obj=Security(symbol=symbol,series='EQ',segment='UNKNOWN'); s.add(obj)
                obj.market_cap_cr=float(cap); obj.market_cap_as_of=as_of
        s.commit()

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('init-db')
    one=sub.add_parser('ingest-date'); one.add_argument('--date',type=date.fromisoformat,default=date.today())
    bf=sub.add_parser('backfill'); bf.add_argument('--days',type=int,default=460)
    mc=sub.add_parser('import-market-caps'); mc.add_argument('--file',required=True); mc.add_argument('--as-of',type=date.fromisoformat,required=True)
    a=p.parse_args()
    if a.cmd=='init-db': init_db(); print('Database tables created')
    elif a.cmd=='ingest-date': print(ingest_date(a.date))
    elif a.cmd=='backfill': print({'processed_dates':len(backfill(a.days))})
    elif a.cmd=='import-market-caps': import_market_caps(a.file,a.as_of); print('Market caps imported')
if __name__=='__main__': main()
