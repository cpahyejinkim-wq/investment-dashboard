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
from kap.data.calendar import find_latest_trading_day
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
BELLWETHER_TICKER = "005930"  # 삼성전자 - used to probe FDR's actual latest date


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

    # Probe FDR's actual latest date with a bellwether ticker (Samsung). When
    # we run before market close (or on a holiday/weekend), the requested
    # ``window.end`` is in the future and probing avoids burning per-ticker
    # calls on a date FDR doesn't have.
    actual_latest = _probe_latest_date(fdr, window.end)
    if actual_latest is None:
        logger.warning("FDR bellwether probe failed - falling back to cache or synthetic")
        return cached if not cached.empty else _synthetic_ohlcv(window)

    if not cached.empty:
        cached_max = max(pd.to_datetime(cached["date"]).dt.date)
        if cached_max >= actual_latest:
            logger.info(
                "fdr cache hit: cached through {} >= FDR latest {}. No fetch needed.",
                cached_max, actual_latest,
            )
            return _slice_window(cached, window)
        # Fetch only from the day after the cache's max date.
        missing_start = cached_max + _dt.timedelta(days=1)
    else:
        missing_start = window.start

    effective_end = actual_latest
    if actual_latest < window.end:
        logger.info(
            "fdr probe: latest available date is {} (window end {}). Capping fetch to probed date.",
            actual_latest, window.end,
        )

    try:
        kospi_list = fdr.StockListing("KOSPI")  # type: ignore[attr-defined]
        kosdaq_list = fdr.StockListing("KOSDAQ")  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        logger.error("FDR StockListing failed: {}", exc)
        return cached if not cached.empty else _synthetic_ohlcv(window)

    universe, cap_map = _build_universe(kospi_list, kosdaq_list)
    logger.info(
        "fdr universe: {} tickers (KOSPI + KOSDAQ). fetching with {} threads...",
        len(universe),
        FDR_MAX_WORKERS,
    )

    def _fetch_one(tk: str, market: str) -> pd.DataFrame | None:
        try:
            df = fdr.DataReader(tk, missing_start, effective_end)  # type: ignore[attr-defined]
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
        mcap, shares = cap_map.get(tk, (np.nan, np.nan))
        df["market_cap"] = mcap if mcap is not None else np.nan
        df["shares"] = shares if shares is not None else np.nan
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


def _probe_latest_date(fdr: object, hint: _dt.date, max_lookback: int = 10) -> _dt.date | None:
    """Walk back from ``hint`` using Samsung as a bellwether to find FDR's latest
    available trading day. Cheap (one ticker, one DataReader call per probe).
    """
    def _probe(d: _dt.date) -> bool:
        try:
            df = fdr.DataReader(BELLWETHER_TICKER, d, d)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return False
        return df is not None and not df.empty

    return find_latest_trading_day(_probe, hint, max_lookback)


def _build_universe(
    kospi_list: pd.DataFrame, kosdaq_list: pd.DataFrame
) -> tuple[list[tuple[str, str]], dict[str, tuple[float | None, float | None]]]:
    """Return ((ticker, market) list, market_cap+shares map).

    FDR StockListing column names vary across versions:
      - ticker:  Code  | Symbol
      - cap:     Marcap | MarCap | MarketCap
      - shares:  Stocks | Shares
    """
    def _first(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _passes(name: str) -> bool:
        if not isinstance(name, str):
            return True
        if "스팩" in name or name.endswith("우") or "리츠" in name:
            return False
        return True

    out: list[tuple[str, str]] = []
    cap_map: dict[str, tuple[float | None, float | None]] = {}

    for df, mk in ((kospi_list, "KOSPI"), (kosdaq_list, "KOSDAQ")):
        code_col = _first(df, ("Code", "Symbol"))
        if code_col is None:
            logger.warning("FDR listing missing Code/Symbol column: {}", df.columns.tolist())
            continue
        name_col = _first(df, ("Name",))
        cap_col = _first(df, ("Marcap", "MarCap", "MarketCap"))
        shares_col = _first(df, ("Stocks", "Shares"))

        for _, r in df.iterrows():
            tk = str(r[code_col]).zfill(6)
            if name_col and not _passes(str(r[name_col])):
                continue
            mcap = float(r[cap_col]) if cap_col and pd.notna(r[cap_col]) else None
            shares = float(r[shares_col]) if shares_col and pd.notna(r[shares_col]) else None
            out.append((tk, mk))
            cap_map[tk] = (mcap, shares)

    if not any(v[0] is not None for v in cap_map.values()):
        logger.warning("FDR StockListing did not provide market cap - universe filter will use trade_value only")
    return out, cap_map


def fetch_index_ohlcv(window: CollectionWindow) -> pd.DataFrame:
    fdr = _try_import_fdr()
    if fdr is None:
        return _synthetic_index(window)
    frames: list[pd.DataFrame] = []
    # VKOSPI: FDR routes unknown symbols to Yahoo which doesn't host it.
    # We try a couple of aliases and silently fall back to NaN — the regime
    # filter already treats missing VKOSPI as a neutral 0 subscore.
    index_targets: list[tuple[str, tuple[str, ...]]] = [
        ("KOSPI", ("KS11",)),
        ("KOSDAQ", ("KQ11",)),
        ("VKOSPI", ("VKOSPI", "^VKOSPI", "VKOSPI.KS")),
    ]
    for name, codes in index_targets:
        df: pd.DataFrame | None = None
        for code in codes:
            try:
                cand = fdr.DataReader(code, window.start, window.end)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                continue
            if cand is not None and not cand.empty:
                df = cand
                break
        if df is None or df.empty:
            if name == "VKOSPI":
                logger.info("FDR: VKOSPI not available - regime volatility subscore will be 0")
            else:
                logger.warning("FDR index fetch failed for {} (tried {})", name, codes)
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
