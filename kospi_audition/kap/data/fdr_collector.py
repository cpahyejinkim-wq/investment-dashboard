"""FinanceDataReader-based collector — backup for when pykrx is broken.

`FinanceDataReader` (FDR) wraps multiple data sources (Yahoo, Naver, KRX
directly) and historically stays operational even when pykrx breaks on KRX
site changes. This module exposes the same `fetch_ohlcv_fast` /
`fetch_index_ohlcv` interface as the pykrx collector so the rest of the
pipeline can swap backends transparently.

Activation::

    pip install finance-datareader
    python run_analysis.py --collector fdr

Or via env var::

    set KAP_COLLECTOR=fdr            (Windows)
    export KAP_COLLECTOR=fdr         (macOS/Linux)

First-run performance: per-ticker fetch is parallelised across
``FDR_MAX_WORKERS`` threads. Subsequent runs hit the parquet cache and only
pull the missing business day(s) — typically <30s.
"""

from __future__ import annotations

import datetime as _dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
from loguru import logger

from kap import config
from kap.data.collector import (
    CollectionWindow,
    _ensure_columns,
    _load_cache,
    _slice_window,
    _synthetic_index,
    _synthetic_ohlcv,
    save_parquet,
)

FDR_MAX_WORKERS = 8


def _try_import_fdr() -> object | None:
    try:
        import FinanceDataReader as fdr  # type: ignore[import-not-found]
        return fdr
    except Exception:  # noqa: BLE001
        return None


def fetch_ohlcv_fast(
    window: CollectionWindow, cache_name: str = "ohlcv"
) -> pd.DataFrame:
    """Pull OHLCV via FDR for the entire universe in the window.

    FDR's `StockListing` gives all KOSPI/KOSDAQ tickers, then `DataReader`
    pulls the time series per ticker (slower than pykrx by_ticker but
    reliable). Increment-cache logic is identical to the pykrx fast path.
    """
    fdr = _try_import_fdr()
    if fdr is None:
        logger.warning("FinanceDataReader unavailable - synthetic fallback")
        return _synthetic_ohlcv(window)

    cache_path = config.DATA_PROCESSED / f"{cache_name}.parquet"
    cached = _load_cache(cache_path)

    bdays = pd.bdate_range(window.start, window.end).date.tolist()
    if cached.empty:
        missing_start = window.start
    else:
        have = set(pd.to_datetime(cached["date"]).dt.date.unique())
        missing_days = [d for d in bdays if d not in have]
        if not missing_days:
            logger.info("fdr cache hit: 0 dates to fetch")
            return _slice_window(cached, window)
        missing_start = min(missing_days)

    try:
        kospi_list = fdr.StockListing("KOSPI")  # type: ignore[attr-defined]
        kosdaq_list = fdr.StockListing("KOSDAQ")  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        logger.error("FDR StockListing failed: {}", exc)
        return cached if not cached.empty else _synthetic_ohlcv(window)

    universe: list[tuple[str, str]] = _build_universe(kospi_list, kosdaq_list)
    logger.info(
        "fdr universe: {} tickers (KOSPI + KOSDAQ). fetching with {} threads...",
        len(universe),
        FDR_MAX_WORKERS,
    )

    def _fetch_one(tk: str, market: str) -> pd.DataFrame | None:
        try:
            df = fdr.DataReader(tk, missing_start, window.end)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.debug("FDR DataReader({}): {}", tk, exc)
            return None
        if df is None or df.empty:
            return None
        df = df.rename(
            columns={
                "Open": "open", "High": "high", "Low": "low", "Close": "close",
                "Volume": "volume",
            }
        )
        df["trade_value"] = (df["close"] * df["volume"]).astype(float)
        df["ticker"] = tk
        df["market"] = market
        df["market_cap"] = np.nan
        df["shares"] = np.nan
        df.index.name = "date"
        df = df.reset_index()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df[["ticker", "date", "market", "open", "high", "low", "close",
                   "volume", "trade_value", "market_cap", "shares"]]

    frames: list[pd.DataFrame] = []
    done = 0
    with ThreadPoolExecutor(max_workers=FDR_MAX_WORKERS) as ex:
        futures = {ex.submit(_fetch_one, tk, market): tk for tk, market in universe}
        for fut in as_completed(futures):
            done += 1
            res = fut.result()
            if res is not None:
                frames.append(res)
            if done % 200 == 0 or done == len(universe):
                logger.info("fdr progress: {}/{}", done, len(universe))

    if not frames:
        logger.error("FDR returned no rows - keeping cache")
        return cached if not cached.empty else _synthetic_ohlcv(window)

    new_rows = pd.concat(frames, ignore_index=True)
    combined = pd.concat([cached, new_rows], ignore_index=True) if not cached.empty else new_rows
    combined = combined.drop_duplicates(subset=["ticker", "date"], keep="last")
    combined = combined.sort_values(["ticker", "date"]).reset_index(drop=True)
    _ensure_columns(combined)
    save_parquet(combined, cache_name)
    return _slice_window(combined, window)


def _build_universe(
    kospi_list: pd.DataFrame, kosdaq_list: pd.DataFrame
) -> list[tuple[str, str]]:
    """Extract (ticker, market) pairs from FDR StockListing frames.

    Column naming differs across FDR versions: ``Code`` (older) vs ``Symbol``
    (newer). We tolerate both. Filters out ETFs / preferred shares by simple
    name suffix heuristics so the universe size stays manageable.
    """
    def _col(df: pd.DataFrame) -> str:
        for c in ("Code", "Symbol"):
            if c in df.columns:
                return c
        raise KeyError(f"neither Code nor Symbol in FDR listing columns: {df.columns.tolist()}")

    def _passes(name: str) -> bool:
        if not isinstance(name, str):
            return True
        if "스팩" in name or name.endswith("우") or "리츠" in name:
            return False
        return True

    out: list[tuple[str, str]] = []
    for df, mk in ((kospi_list, "KOSPI"), (kosdaq_list, "KOSDAQ")):
        code_col = _col(df)
        name_col = "Name" if "Name" in df.columns else None
        for _, r in df.iterrows():
            tk = str(r[code_col]).zfill(6)
            if name_col and not _passes(str(r[name_col])):
                continue
            out.append((tk, mk))
    return out


def fetch_index_ohlcv(window: CollectionWindow) -> pd.DataFrame:
    fdr = _try_import_fdr()
    if fdr is None:
        return _synthetic_index(window)
    frames: list[pd.DataFrame] = []
    for name, code in (("KOSPI", "KS11"), ("KOSDAQ", "KQ11"), ("VKOSPI", "VKOSPI")):
        try:
            df = fdr.DataReader(code, window.start, window.end)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("FDR index fetch failed for {}: {}", name, exc)
            continue
        if df is None or df.empty:
            continue
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                "Close": "close", "Volume": "volume"})
        df.index.name = "date"
        df = df.reset_index()
        df["index_name"] = name
        df["date"] = pd.to_datetime(df["date"]).dt.date
        frames.append(df)
    if not frames:
        return _synthetic_index(window)
    return pd.concat(frames, ignore_index=True)
