from datetime import date
from sqlalchemy import select
from .db import SessionLocal
from .models import DailyPrice, Security, BenchmarkPrice

def scan(min_cap=500, min_price=10, min_turnover=7, percentile_cutoff=80):
    if SessionLocal is None: raise RuntimeError('DATABASE_URL is not configured')
    with SessionLocal() as s:
        rows=s.execute(select(DailyPrice,Security).join(Security,DailyPrice.symbol==Security.symbol).where(DailyPrice.series=="EQ").order_by(DailyPrice.symbol,DailyPrice.trade_date)).all()
        by_symbol={}
        for p,sec in rows:
            by_symbol.setdefault(p.symbol,[]).append((p,sec))
        benchmark=s.execute(select(BenchmarkPrice).where(BenchmarkPrice.index_name=='NIFTY 500').order_by(BenchmarkPrice.trade_date)).scalars().all()
        bench={x.trade_date:x.close for x in benchmark}
        out=[]
        for symbol,items in by_symbol.items():
            # only keep latest identity/cap; price series must have 200+ sessions
            prices=[x[0] for x in items]
            if len(prices)<200: continue
            latest=prices[-1]; cap=items[-1][1].market_cap_cr
            if cap is None or latest.close<=min_price: continue
            last200=prices[-200:]; last20=prices[-20:]
            dma=sum(x.close for x in last200)/200
            turnover=sum((x.close*x.volume) for x in last20)/20/1e7
            base=prices[-64]
            ret3=(latest.close/base.close-1)*100
            # Match benchmark close on stock's latest date and 63-session-earlier date.
            b_dates=sorted(d for d in bench if d<=latest.trade_date)
            rs3=None
            if len(b_dates)>=64:
                b_now=bench[b_dates[-1]]; b_then=bench[b_dates[-64]]
                if b_then>0: rs3=((latest.close/base.close)/(b_now/b_then)-1)*100
            if cap>min_cap and latest.close>dma and turnover>min_turnover:
                out.append({'symbol':symbol,'price':latest.close,'market_cap_cr':cap,'return_3m_pct':ret3,'rs_3m_pct':rs3,'dma_200':dma,'avg_turnover_cr':turnover,'date':latest.trade_date.isoformat(),'segment':items[-1][1].segment,'market_cap_as_of':items[-1][1].market_cap_as_of.isoformat() if items[-1][1].market_cap_as_of else None})
        out.sort(key=lambda x:(x['rs_3m_pct'] is not None,x['rs_3m_pct'] if x['rs_3m_pct'] is not None else x['return_3m_pct']),reverse=True)
        n=len(out)
        for i,r in enumerate(out,1): r['rank']=i; r['percentile']=(n-i+1)/n*100 if n else 0
        return {'as_of':max((x['date'] for x in out),default=None),'eligible_count':n,'results':[x for x in out if x['percentile']>=percentile_cutoff]}
