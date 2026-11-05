from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (UniqueConstraint("trade_date", "symbol", "series", name="uq_daily_price"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_date: Mapped[object] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    series: Mapped[str] = mapped_column(String(12), default="EQ")
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    segment: Mapped[str] = mapped_column(String(12), default="MAINBOARD")
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    turnover_rupees: Mapped[float | None] = mapped_column(Float, nullable=True)

class Security(Base):
    __tablename__ = "securities"
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    company_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    series: Mapped[str] = mapped_column(String(12), default="EQ")
    segment: Mapped[str] = mapped_column(String(12), default="MAINBOARD")
    market_cap_cr: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap_as_of: Mapped[object | None] = mapped_column(Date, nullable=True)

class BenchmarkPrice(Base):
    __tablename__ = "benchmark_prices"
    trade_date: Mapped[object] = mapped_column(Date, primary_key=True)
    index_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    close: Mapped[float] = mapped_column(Float)

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trade_date: Mapped[object | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    mainboard_rows: Mapped[int] = mapped_column(Integer, default=0)
    sme_rows: Mapped[int] = mapped_column(Integer, default=0)
    benchmark_rows: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
