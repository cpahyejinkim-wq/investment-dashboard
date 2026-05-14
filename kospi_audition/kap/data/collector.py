"""Data collector: pykrx -> parquet -> DuckDB.

The collector is intentionally tolerant of offline / missing pykrx environments:
when pykrx is not importable (e.g. tests or sandboxed CI), it falls back to
deterministic synthetic data so the rest of the pipeline remains testable.
"""

from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
from loguru import logger

from kap import config


@dataclass(frozen=True)
class CollectionWindow:
    start: _dt.date
    end: _dt.date

    def as_strings(self) -> tuple[str, str]:
        return self.start.strftime("%Y%m%d"), self.end.strftime("%Y%m%d")


def _try_import_pykrx() -> object | None:
    try:
        import pykrx.stock as stock  # type: ignore[import-not-found]
        return stock
    except Exception:  # noqa: BLE001
        return None


def _kospi_kosdaq_tickers(stock: object, date_str: str) -> dict[str, str]:
    """Return {ticker: market} for KOSPI + KOSDAQ on date_str."""
    out: dict[str, str] = {}
    for market in ("KOSPI", "KOSDAQ"):
        tickers = stock.get_market_ticker_list(date_str, market=market)  # type: ignore[attr-defined]
        for t in tickers:
            out[t] = market
    return out


def fetch_ohlcv(window: CollectionWindow) -> pd.DataFrame:
    """Fetch per-ticker OHLCV between window.start and window.end.

    Returns a long-form DataFrame with columns:
      ticker, date, market, open, high, low, close, volume, trade_value,
      market_cap, shares
    """
    stock = _try_import_pykrx()
    start_str, end_str = window.as_strings()

    if stock is None:
        logger.warning("pykrx unavailable - falling back to synthetic OHLCV")
        return _synthetic_ohlcv(window)

    ticker_market = _kospi_kosdaq_tickers(stock, end_str)
    logger.info("collected {} tickers across KOSPI/KOSDAQ", len(ticker_market))

    frames: list[pd.DataFrame] = []
    started = time.time()
    for i, (ticker, market) in enumerate(ticker_market.items(), 1):
        try:
            df = stock.get_market_ohlcv_by_date(start_str, end_str, ticker)  # type: ignore[attr-defined]
            cap = stock.get_market_cap_by_date(start_str, end_str, ticker)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.debug("skip {}: {}", ticker, exc)
            continue
        if df is None or df.empty:
            continue
        df = df.rename(
            columns={
                "시가": "open",
                "고가": "high",
                "저가": "low",
                "종가": "close",
                "거래량": "volume",
                "거래대금": "trade_value",
            }
        )
        df.index.name = "date"
        df = df.reset_index()
        df["ticker"] = ticker
        df["market"] = market
        if cap is not None and not cap.empty:
            cap = cap.rename(columns={"시가총액": "market_cap", "상장주식수": "shares"})
            df = df.merge(
                cap[["market_cap", "shares"]].reset_index().rename(columns={"날짜": "date"}),
                on="date",
                how="left",
            )
        frames.append(df)
        if i % 200 == 0:
            logger.info("ohlcv progress: {}/{} ({:.1f}s)", i, len(ticker_market), time.time() - started)

    if not frames:
        logger.error("No OHLCV data fetched - returning synthetic fallback")
        return _synthetic_ohlcv(window)

    out = pd.concat(frames, ignore_index=True)
    keep = [
        "ticker",
        "date",
        "market",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_value",
        "market_cap",
        "shares",
    ]
    for col in keep:
        if col not in out.columns:
            out[col] = np.nan
    out = out[keep]
    out["date"] = pd.to_datetime(out["date"]).dt.date
    logger.info("ohlcv assembled: {} rows", len(out))
    return out


def fetch_index_ohlcv(window: CollectionWindow) -> pd.DataFrame:
    """Fetch KOSPI / KOSDAQ / VKOSPI index OHLCV."""
    stock = _try_import_pykrx()
    start_str, end_str = window.as_strings()

    if stock is None:
        logger.warning("pykrx unavailable - falling back to synthetic index data")
        return _synthetic_index(window)

    frames: list[pd.DataFrame] = []
    for name, code in (("KOSPI", "1001"), ("KOSDAQ", "2001"), ("VKOSPI", "1995")):
        try:
            df = stock.get_index_ohlcv_by_date(start_str, end_str, code)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("index fetch failed for {}: {}", name, exc)
            continue
        if df is None or df.empty:
            continue
        df = df.rename(
            columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}
        )
        df.index.name = "date"
        df = df.reset_index()
        df["index_name"] = name
        frames.append(df)

    if not frames:
        return _synthetic_index(window)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.date
    return out


# ---------------------------------------------------------------------------
# Synthetic fallback (offline mode)
# ---------------------------------------------------------------------------


def _synthetic_dates(window: CollectionWindow) -> list[_dt.date]:
    cur = window.start
    out: list[_dt.date] = []
    while cur <= window.end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += _dt.timedelta(days=1)
    return out


def _synthetic_ohlcv(window: CollectionWindow) -> pd.DataFrame:
    """Deterministic synthetic OHLCV used in offline / test environments."""
    rng = np.random.default_rng(config.RANDOM_SEED)
    dates = _synthetic_dates(window)
    if not dates:
        return pd.DataFrame()

    n_tickers = 200
    tickers = [f"{i:06d}" for i in range(1, n_tickers + 1)]
    markets = ["KOSPI" if i % 2 == 0 else "KOSDAQ" for i in range(n_tickers)]

    rows: list[dict[str, object]] = []
    for tk, mk in zip(tickers, markets, strict=True):
        # heterogeneous drift per ticker
        drift = rng.normal(0.0005, 0.0008)
        vol = rng.uniform(0.012, 0.040)
        price = float(rng.uniform(3_000, 80_000))
        shares = float(rng.integers(5_000_000, 200_000_000))
        for d in dates:
            r = rng.normal(drift, vol)
            price = max(price * (1.0 + r), 100.0)
            high = price * (1.0 + abs(rng.normal(0, vol / 3)))
            low = price * (1.0 - abs(rng.normal(0, vol / 3)))
            open_ = price * (1.0 + rng.normal(0, vol / 4))
            volume = int(max(rng.normal(800_000, 200_000), 1_000))
            trade_value = float(volume * price)
            rows.append(
                {
                    "ticker": tk,
                    "date": d,
                    "market": mk,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": price,
                    "volume": volume,
                    "trade_value": trade_value,
                    "market_cap": price * shares,
                    "shares": shares,
                }
            )
    return pd.DataFrame(rows)


def _synthetic_index(window: CollectionWindow) -> pd.DataFrame:
    rng = np.random.default_rng(config.RANDOM_SEED + 1)
    dates = _synthetic_dates(window)
    rows: list[dict[str, object]] = []
    for name, base, vol in (("KOSPI", 2600.0, 0.011), ("KOSDAQ", 850.0, 0.018), ("VKOSPI", 20.0, 0.05)):
        price = base
        for d in dates:
            r = rng.normal(0.0003, vol)
            price = max(price * (1.0 + r), 1.0)
            rows.append(
                {
                    "date": d,
                    "index_name": name,
                    "open": price,
                    "high": price * 1.005,
                    "low": price * 0.995,
                    "close": price,
                    "volume": 0,
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_parquet(df: pd.DataFrame, name: str) -> None:
    path = config.DATA_PROCESSED / f"{name}.parquet"
    df.to_parquet(path, index=False)
    logger.info("wrote {} ({} rows)", path, len(df))


def load_parquet(name: str) -> pd.DataFrame:
    path = config.DATA_PROCESSED / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_parquet(path)
