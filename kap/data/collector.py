"""Data Collector for KOSPI/KOSDAQ.

Primary source: pykrx (real KRX market data).
Fallback: deterministic synthetic data so the full pipeline can be developed
and tested in environments without KRX network access.

Produces parquet files in data/processed/:
  - ohlcv.parquet      (ticker, date, market, open, high, low, close, volume, trade_value, market_cap, shares)
  - flow.parquet       (ticker, date, foreign_net_buy, foreign_holding, inst_net_buy, individual_net_buy)
  - index.parquet      (date, kospi_close, kosdaq_close, vkospi)
  - metadata.parquet   (ticker, name, market, sector, listing_date)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from kap.config import DATA_FETCH, PROCESSED_DIR, RANDOM_SEED

try:  # pragma: no cover - optional dependency
    from pykrx import stock as pykrx_stock  # type: ignore[import-not-found]

    _HAS_PYKRX = True
except Exception:  # pragma: no cover
    pykrx_stock = None  # type: ignore[assignment]
    _HAS_PYKRX = False

try:  # pragma: no cover - optional dependency
    import FinanceDataReader as fdr  # type: ignore[import-not-found]

    _HAS_FDR = True
except Exception:  # pragma: no cover
    fdr = None  # type: ignore[assignment]
    _HAS_FDR = False


@dataclass(frozen=True)
class CollectorResult:
    ohlcv: pd.DataFrame
    flow: pd.DataFrame
    index: pd.DataFrame
    metadata: pd.DataFrame
    source: str  # "pykrx" or "synthetic"


SECTORS_KOSPI = [
    "반도체", "자동차", "2차전지", "바이오", "방산", "조선", "철강",
    "화학", "건설", "유통", "은행", "보험", "통신", "엔터", "게임",
]
SECTORS_KOSDAQ = [
    "바이오", "2차전지", "반도체", "엔터", "게임", "소프트웨어",
    "의료기기", "신재생에너지", "로봇", "AI",
]


def _try_fdr(end_date: date, lookback_days: int) -> CollectorResult | None:
    """FinanceDataReader 기반 실데이터 수집. pykrx 인증 이슈 우회용 primary 경로."""
    if not _HAS_FDR:
        logger.info("FinanceDataReader not installed; skipping FDR path")
        return None
    try:
        from kap.config import UNIVERSE

        t0 = time.time()
        logger.info("Fetching KRX stock listing via FinanceDataReader…")
        listing = fdr.StockListing("KRX")  # type: ignore[union-attr]
        # 컬럼 정규화 (FDR 버전별 차이 흡수)
        col_map = {
            "Code": "ticker", "Symbol": "ticker", "종목코드": "ticker",
            "Name": "name", "종목명": "name",
            "Market": "market", "시장": "market",
            "MarketCap": "market_cap", "Marcap": "market_cap", "시가총액": "market_cap",
            "Stocks": "shares", "상장주식수": "shares",
        }
        listing = listing.rename(columns={k: v for k, v in col_map.items() if k in listing.columns})
        # ticker는 6자리 zero-padded string로 통일
        listing["ticker"] = listing["ticker"].astype(str).str.zfill(6)
        # 시장 필터 (KOSPI/KOSDAQ만)
        listing = listing[listing["market"].isin(["KOSPI", "KOSDAQ"])].copy()
        if "market_cap" not in listing.columns:
            logger.warning("FDR listing has no market_cap column; cannot filter universe")
            return None
        listing["market_cap"] = pd.to_numeric(listing["market_cap"], errors="coerce")
        listing = listing.dropna(subset=["market_cap"])

        # 유니버스 필터 (시총 + 상위 N)
        min_kp = int(UNIVERSE["min_market_cap_kospi"])
        min_kd = int(UNIVERSE["min_market_cap_kosdaq"])
        mask = (
            ((listing["market"] == "KOSPI") & (listing["market_cap"] >= min_kp))
            | ((listing["market"] == "KOSDAQ") & (listing["market_cap"] >= min_kd))
        )
        eligible = listing[mask].sort_values("market_cap", ascending=False)
        max_universe = int(DATA_FETCH.get("pykrx_max_universe", 200))  # type: ignore[union-attr]
        eligible = eligible.head(max_universe).reset_index(drop=True)
        logger.info(
            "FDR listing: {} rows total, {} eligible after cap filter (top {} kept)",
            len(listing), int(mask.sum()), len(eligible),
        )

        # OHLCV 수집 (per-ticker)
        start_str = (end_date - timedelta(days=int(lookback_days * 1.7))).strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        ohlcv_frames: list[pd.DataFrame] = []
        n_total = len(eligible)
        t_ohlcv = time.time()
        for i, row in enumerate(eligible.itertuples(), start=1):
            tk = getattr(row, "ticker")
            try:
                df = fdr.DataReader(tk, start_str, end_str)  # type: ignore[union-attr]
            except Exception as e:
                logger.debug("FDR DataReader failed for {}: {}", tk, e)
                continue
            if df is None or df.empty:
                continue
            df = df.reset_index()
            df.columns = [str(c) for c in df.columns]
            # FDR 응답 컬럼 정규화
            df = df.rename(columns={
                "Date": "date", "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume", "Change": "change",
            })
            df["date"] = pd.to_datetime(df["date"])
            df["ticker"] = tk
            df["market"] = row.market
            df["trade_value"] = df["volume"].astype(float) * df["close"].astype(float)
            shares = int(getattr(row, "shares", 0) or 0)
            if shares == 0:
                # market_cap / close로 역산
                shares = int(float(row.market_cap) / float(df["close"].iloc[-1])) if len(df) else 0
            df["shares"] = shares
            df["market_cap"] = df["close"].astype(float) * shares
            ohlcv_frames.append(df[["ticker", "date", "market", "open", "high", "low",
                                     "close", "volume", "trade_value", "market_cap", "shares"]])
            if i % 25 == 0 or i == n_total:
                elapsed = time.time() - t_ohlcv
                remaining = elapsed / i * (n_total - i)
                logger.info("  OHLCV progress (FDR): {}/{} ({:.0f}%, {:.1f}s, ~{:.0f}s remaining)",
                            i, n_total, i / n_total * 100, elapsed, remaining)
        if not ohlcv_frames:
            logger.warning("FDR returned no OHLCV — falling back further")
            return None
        ohlcv = pd.concat(ohlcv_frames, ignore_index=True)
        logger.info("FDR OHLCV combined: {:,} rows, elapsed={:.1f}s",
                    len(ohlcv), time.time() - t_ohlcv)

        # 지수 (KOSPI=KS11, KOSDAQ=KQ11)
        logger.info("Fetching index history via FDR…")
        kospi_idx = fdr.DataReader("KS11", start_str, end_str)  # type: ignore[union-attr]
        kosdaq_idx = fdr.DataReader("KQ11", start_str, end_str)  # type: ignore[union-attr]
        idx_df = pd.DataFrame({
            "date": pd.to_datetime(kospi_idx.index),
            "kospi_close": kospi_idx["Close"].values,
            "kosdaq_close": kosdaq_idx["Close"].reindex(kospi_idx.index).ffill().values,
            "vkospi": 20.0,  # FDR엔 VKOSPI가 없어 안전 디폴트 (Regime 계산에는 영향 적음)
        })

        # 메타데이터
        metadata = pd.DataFrame({
            "ticker": eligible["ticker"].values,
            "name": eligible["name"].astype(str).values,
            "market": eligible["market"].values,
            "sector": "기타",  # FDR도 안정적 섹터 매핑 미제공 → Stage 2 보강
            "listing_date": [pd.Timestamp(end_date) - pd.Timedelta(days=365 * 5)
                              for _ in range(len(eligible))],
        })

        # Flow zero-fill (Stage 1)
        flow_dates = sorted(ohlcv["date"].unique())
        flow_rows = []
        for tk in metadata["ticker"]:
            for d in flow_dates:
                flow_rows.append({
                    "ticker": tk, "date": d,
                    "foreign_net_buy": 0.0, "foreign_holding": 0.15,
                    "inst_net_buy": 0.0, "individual_net_buy": 0.0,
                })
        flow = pd.DataFrame(flow_rows)

        logger.info("FDR collection complete: source=fdr, total_elapsed={:.1f}s",
                    time.time() - t0)
        return CollectorResult(ohlcv=ohlcv, flow=flow, index=idx_df,
                                metadata=metadata, source="fdr")
    except Exception as exc:  # pragma: no cover
        logger.warning("FDR collection failed: {} — trying next source", exc)
        return None


def _nearest_trading_day_str(end_date: date) -> str:
    """KRX는 주말/공휴일 휴장. 가까운 거래일을 찾되, 최대 7일 전까지 시도."""
    for delta in range(0, 7):
        d = end_date - timedelta(days=delta)
        if d.weekday() < 5:
            return d.strftime("%Y%m%d")
    return end_date.strftime("%Y%m%d")


def _try_pykrx(end_date: date, lookback_days: int) -> CollectorResult | None:
    """Fetch real KRX data via pykrx. Returns None on any failure."""
    if not _HAS_PYKRX:
        logger.info("pykrx not installed; using synthetic fallback")
        return None
    try:
        start_str = (end_date - timedelta(days=int(lookback_days * 1.7))).strftime("%Y%m%d")

        # KRX 서버에 데이터가 있는 가장 가까운 거래일을 찾는다.
        # 오늘이 장중이거나 휴장일이면 시총 스냅샷이 비어 나올 수 있음.
        t0 = time.time()
        cap_all = None
        end_str = None
        for delta in range(0, 10):
            d = end_date - timedelta(days=delta)
            if d.weekday() >= 5:  # 주말 스킵
                continue
            candidate = d.strftime("%Y%m%d")
            try:
                cap_kospi = pykrx_stock.get_market_cap_by_ticker(candidate, market="KOSPI")
                cap_kosdaq = pykrx_stock.get_market_cap_by_ticker(candidate, market="KOSDAQ")
            except Exception as inner:
                logger.debug("Snapshot {} failed: {}", candidate, inner)
                continue
            if (cap_kospi is None or cap_kospi.empty
                    or "시가총액" not in cap_kospi.columns
                    or cap_kosdaq is None or cap_kosdaq.empty
                    or "시가총액" not in cap_kosdaq.columns):
                logger.info("No KRX snapshot data for {}; trying previous trading day…",
                            candidate)
                continue
            cap_kospi["market"] = "KOSPI"
            cap_kosdaq["market"] = "KOSDAQ"
            cap_all = pd.concat([cap_kospi, cap_kosdaq])
            end_str = candidate
            logger.info("Using KRX market snapshot for trading day {}", candidate)
            break

        if cap_all is None or end_str is None:
            logger.warning("No usable KRX snapshot within past 10 days — falling back")
            return None

        cap_all = cap_all.reset_index().rename(columns={"티커": "ticker"})
        logger.info(
            "pykrx snapshot fetched: KOSPI={}, KOSDAQ={}, elapsed={:.1f}s",
            (cap_all["market"] == "KOSPI").sum(),
            (cap_all["market"] == "KOSDAQ").sum(),
            time.time() - t0,
        )

        # 1차 유니버스 필터 (시총만, 거래대금/상장일은 OHLCV 받은 뒤 다시 확인)
        from kap.config import UNIVERSE
        min_kp = int(UNIVERSE["min_market_cap_kospi"])
        min_kd = int(UNIVERSE["min_market_cap_kosdaq"])
        mask = (
            ((cap_all["market"] == "KOSPI") & (cap_all["시가총액"] >= min_kp))
            | ((cap_all["market"] == "KOSDAQ") & (cap_all["시가총액"] >= min_kd))
        )
        eligible = cap_all[mask].copy()
        # 추가로 시총 큰 순으로 상위 N개만 — 첫 실행 시간을 줄이기 위해
        max_universe = int(DATA_FETCH.get("pykrx_max_universe", 200))  # type: ignore[union-attr]
        eligible = eligible.sort_values("시가총액", ascending=False).head(max_universe)
        logger.info("Eligible universe after cap filter: {}", len(eligible))

        # 종목명 조회
        logger.info("Resolving stock names…")
        names: dict[str, str] = {}
        for tk in eligible["ticker"]:
            try:
                names[tk] = pykrx_stock.get_market_ticker_name(tk)
            except Exception:
                names[tk] = tk

        # 섹터 — pykrx에 직접 매핑이 없음 → 시총 기반 그룹/"기타"로 분류
        sectors: dict[str, str] = {}
        try:
            # 'KRX 업종' 분류 (있는 경우)
            sec_df = pykrx_stock.get_index_portfolio_deposit_file  # noqa  # pragma: no cover
        except Exception:
            pass
        for tk in eligible["ticker"]:
            sectors[tk] = "기타"  # 단순 fallback; Stage 2에서 보강

        # OHLCV 수집 (per-ticker)
        ohlcv_frames: list[pd.DataFrame] = []
        n_total = len(eligible)
        t_ohlcv = time.time()
        for i, (tk, row) in enumerate(eligible.iterrows(), start=1):
            try:
                df = pykrx_stock.get_market_ohlcv_by_date(start_str, end_str, row["ticker"])
            except Exception as e:
                logger.warning("OHLCV fetch failed for {}: {}", row["ticker"], e)
                continue
            if df is None or df.empty:
                continue
            df = df.reset_index().rename(columns={
                "날짜": "date", "시가": "open", "고가": "high", "저가": "low",
                "종가": "close", "거래량": "volume", "거래대금": "trade_value",
            })
            df["ticker"] = row["ticker"]
            df["market"] = row["market"]
            df["shares"] = int(row["상장주식수"])
            df["market_cap"] = df["close"].astype(float) * df["shares"]
            ohlcv_frames.append(df[["ticker", "date", "market", "open", "high", "low",
                                     "close", "volume", "trade_value", "market_cap", "shares"]])
            if i % 25 == 0 or i == n_total:
                elapsed = time.time() - t_ohlcv
                logger.info(
                    "  OHLCV progress: {}/{} ({:.0f}%, {:.1f}s, ~{:.1f}s remaining)",
                    i, n_total, i / n_total * 100, elapsed,
                    elapsed / i * (n_total - i),
                )
        if not ohlcv_frames:
            logger.warning("pykrx returned no OHLCV — falling back to synthetic")
            return None
        ohlcv = pd.concat(ohlcv_frames, ignore_index=True)
        ohlcv["date"] = pd.to_datetime(ohlcv["date"])
        logger.info("OHLCV combined: {:,} rows, elapsed={:.1f}s", len(ohlcv), time.time() - t_ohlcv)

        # KOSPI/KOSDAQ index history
        logger.info("Fetching index history…")
        idx_kospi = pykrx_stock.get_index_ohlcv_by_date(start_str, end_str, "1001")  # 코스피
        idx_kosdaq = pykrx_stock.get_index_ohlcv_by_date(start_str, end_str, "2001") # 코스닥
        idx_df = pd.DataFrame({
            "date": pd.to_datetime(idx_kospi.index),
            "kospi_close": idx_kospi["종가"].values,
            "kosdaq_close": idx_kosdaq["종가"].reindex(idx_kospi.index).ffill().values,
        })
        # VKOSPI (V-KOSPI 지수, 코드: 1497)
        try:
            vk = pykrx_stock.get_index_ohlcv_by_date(start_str, end_str, "1497")
            idx_df["vkospi"] = vk["종가"].reindex(idx_kospi.index).ffill().values
        except Exception:
            idx_df["vkospi"] = 20.0  # 안전 디폴트

        # 종목 메타데이터
        metadata = pd.DataFrame({
            "ticker": list(eligible["ticker"]),
            "name": [names.get(tk, tk) for tk in eligible["ticker"]],
            "market": list(eligible["market"]),
            "sector": [sectors.get(tk, "기타") for tk in eligible["ticker"]],
            "listing_date": [pd.Timestamp(end_date) - pd.Timedelta(days=365 * 5)
                              for _ in eligible["ticker"]],
        })

        # Flow 데이터는 비용이 커서 Stage 1에서는 zero-fill (Flow 점수는 중립 50%)
        flow_dates = sorted(ohlcv["date"].unique())
        flow_rows = []
        for tk in metadata["ticker"]:
            for d in flow_dates:
                flow_rows.append({
                    "ticker": tk, "date": d,
                    "foreign_net_buy": 0.0, "foreign_holding": 0.15,
                    "inst_net_buy": 0.0, "individual_net_buy": 0.0,
                })
        flow = pd.DataFrame(flow_rows)

        logger.info("pykrx collection complete: source=pykrx, total_elapsed={:.1f}s", time.time() - t0)
        return CollectorResult(ohlcv=ohlcv, flow=flow, index=idx_df, metadata=metadata, source="pykrx")

    except Exception as exc:  # pragma: no cover - network failures
        logger.warning("pykrx collection failed: {} — falling back to synthetic", exc)
        return None


def _synthetic_dataset(end_date: date, lookback_days: int) -> CollectorResult:
    """Generate a deterministic synthetic KOSPI/KOSDAQ dataset.

    Uses geometric Brownian motion per ticker with sector-correlated drift,
    plus a market regime that shifts mid-history. Produces realistic-shape
    data for end-to-end pipeline testing.
    """
    rng = np.random.default_rng(RANDOM_SEED)
    n_kospi = int(DATA_FETCH["synthetic_n_kospi"])  # type: ignore[arg-type]
    n_kosdaq = int(DATA_FETCH["synthetic_n_kosdaq"])  # type: ignore[arg-type]

    # Business-day calendar
    dates = pd.bdate_range(end=pd.Timestamp(end_date), periods=lookback_days)

    # Market index path (KOSPI): three regimes — early choppy, mid uptrend, late strong
    # so the *current* (last day) regime is clearly Risk-On / Strong Risk-On.
    n = len(dates)
    n_early = int(n * 0.35)
    n_mid = int(n * 0.40)
    n_late = n - n_early - n_mid
    drift_early = rng.normal(-0.0001, 0.014, n_early)
    drift_mid = rng.normal(0.0008, 0.011, n_mid)
    drift_late = rng.normal(0.0014, 0.009, n_late)  # strong recent uptrend
    kospi_returns = np.concatenate([drift_early, drift_mid, drift_late])
    kospi_close = 2500 * np.exp(np.cumsum(kospi_returns))
    kosdaq_close = 850 * np.exp(np.cumsum(kospi_returns * 1.3 + rng.normal(0, 0.004, n)))
    # VKOSPI: low in recent uptrend (Risk-On signal)
    vkospi = 17 + 6 * np.abs(rng.normal(0, 1, n)) + 8 * (kospi_returns < -0.01)
    vkospi[-n_late:] = np.clip(vkospi[-n_late:] * 0.7, 12, 20)

    index_df = pd.DataFrame({
        "date": dates,
        "kospi_close": kospi_close,
        "kosdaq_close": kosdaq_close,
        "vkospi": vkospi,
    })

    def make_tickers(market: str, count: int, sectors: list[str], code_prefix: str) -> pd.DataFrame:
        rows = []
        for i in range(count):
            code = f"{code_prefix}{i:04d}"
            sector = sectors[i % len(sectors)]
            name = f"종목{market}{i:03d}"
            listing = pd.Timestamp(end_date) - pd.Timedelta(days=int(rng.integers(200, 3000)))
            rows.append({
                "ticker": code, "name": name, "market": market,
                "sector": sector, "listing_date": listing,
            })
        return pd.DataFrame(rows)

    meta_kospi = make_tickers("KOSPI", n_kospi, SECTORS_KOSPI, "00")
    meta_kosdaq = make_tickers("KOSDAQ", n_kosdaq, SECTORS_KOSDAQ, "10")
    metadata = pd.concat([meta_kospi, meta_kosdaq], ignore_index=True)

    # Sector-level drift (creates rotation patterns)
    sector_universe = list(set(SECTORS_KOSPI + SECTORS_KOSDAQ))
    sector_drift = {s: rng.normal(0, 0.0008, n) for s in sector_universe}
    # Add a "hot" sector that accelerates in the last 30 days
    hot = rng.choice(sector_universe)
    sector_drift[hot][-30:] += 0.004
    sector_drift[hot][-60:-30] += 0.002

    ohlcv_rows: list[pd.DataFrame] = []
    flow_rows: list[pd.DataFrame] = []

    for _, row in metadata.iterrows():
        ticker = row["ticker"]
        sector = row["sector"]
        market = row["market"]

        # idiosyncratic vol higher for KOSDAQ
        idio_vol = 0.022 if market == "KOSDAQ" else 0.016
        idio_drift = rng.normal(0.0002, 0.0006)
        eps = rng.normal(0, idio_vol, n)
        beta = rng.uniform(0.6, 1.4)
        rets = beta * kospi_returns + sector_drift[sector] + idio_drift + eps

        start_price = float(rng.uniform(3000, 80000))
        close = start_price * np.exp(np.cumsum(rets))
        open_ = close * (1 + rng.normal(0, 0.005, n))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.008, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.008, n)))

        shares = int(rng.integers(5_000_000, 500_000_000))
        base_vol = int(rng.integers(50_000, 2_000_000))
        volume = (base_vol * (1 + 0.5 * np.abs(rets) / idio_vol)).astype(np.int64)
        trade_value = volume * close
        market_cap = shares * close

        ohlcv_rows.append(pd.DataFrame({
            "ticker": ticker,
            "date": dates,
            "market": market,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "trade_value": trade_value,
            "market_cap": market_cap,
            "shares": shares,
        }))

        # Flow data: foreign/institutional/individual net buying
        foreign_net = rng.normal(0, trade_value.mean() * 0.05, n)
        inst_net = rng.normal(0, trade_value.mean() * 0.04, n)
        individual_net = -(foreign_net + inst_net) + rng.normal(0, trade_value.mean() * 0.02, n)
        foreign_holding = np.clip(
            0.15 + np.cumsum(foreign_net) / (market_cap + 1e-9) * 50, 0.01, 0.65
        )
        flow_rows.append(pd.DataFrame({
            "ticker": ticker,
            "date": dates,
            "foreign_net_buy": foreign_net,
            "foreign_holding": foreign_holding,
            "inst_net_buy": inst_net,
            "individual_net_buy": individual_net,
        }))

    ohlcv = pd.concat(ohlcv_rows, ignore_index=True)
    flow = pd.concat(flow_rows, ignore_index=True)

    logger.info(
        "Synthetic dataset built: {} tickers × {} days = {:,} OHLCV rows",
        len(metadata), n, len(ohlcv),
    )
    return CollectorResult(ohlcv=ohlcv, flow=flow, index=index_df, metadata=metadata, source="synthetic")


def _cache_is_fresh() -> bool:
    """캐시된 parquet 파일이 모두 있고 cache_max_age_hours 이내이며,
    합성(synthetic) 데이터 캐시는 prefer_pykrx=True일 때 무효 처리."""
    if not bool(DATA_FETCH.get("cache_parquet", True)):
        return False
    required = ["ohlcv.parquet", "flow.parquet", "index.parquet", "metadata.parquet"]
    files = [PROCESSED_DIR / f for f in required]
    if not all(f.exists() for f in files):
        return False
    # 합성 데이터 캐시는 prefer_pykrx 모드에서 재사용 금지 (다음 실행에서 실데이터 재시도)
    src_file = PROCESSED_DIR / ".source"
    if src_file.exists() and bool(DATA_FETCH.get("prefer_pykrx", True)):
        src = src_file.read_text(encoding="utf-8").strip()
        if src not in ("pykrx", "fdr"):
            logger.info("Cached data is '{}' but prefer_pykrx=True → will re-fetch", src)
            return False
    import os
    max_age = float(DATA_FETCH.get("cache_max_age_hours", 12)) * 3600  # type: ignore[arg-type]
    newest = max(os.path.getmtime(f) for f in files)
    age = time.time() - newest
    return age <= max_age


def collect(
    end_date: date | None = None,
    lookback_days: int | None = None,
    force_refresh: bool = False,
) -> CollectorResult:
    """Main entry point.

    Priority: fresh parquet cache → pykrx (if prefer_pykrx) → synthetic fallback.
    force_refresh=True 면 캐시 무시.
    """
    end_date = end_date or date.today()
    lookback_days = lookback_days or int(DATA_FETCH["synthetic_history_days"])  # type: ignore[arg-type]
    t0 = time.time()

    if not force_refresh and _cache_is_fresh():
        logger.info("Reusing cached parquet (within {}h)", DATA_FETCH.get("cache_max_age_hours"))
        result = load_parquet()
        logger.info("Cached load complete: source={}, elapsed={:.1f}s",
                    result.source, time.time() - t0)
        return result

    prefer_pykrx = bool(DATA_FETCH.get("prefer_pykrx", True))
    result: CollectorResult | None = None
    # 1순위: FinanceDataReader (KRX 인증 불필요, Naver Finance 경유)
    if prefer_pykrx:
        result = _try_fdr(end_date, lookback_days)
    # 2순위: pykrx (인증 환경변수 설정된 경우)
    if result is None and prefer_pykrx:
        result = _try_pykrx(end_date, lookback_days)
    # 3순위: 합성 데이터 (네트워크 차단 환경 대비)
    if result is None:
        if not bool(DATA_FETCH["use_synthetic_fallback"]):
            raise RuntimeError("Real data collection failed and synthetic fallback is disabled")
        result = _synthetic_dataset(end_date, lookback_days)

    logger.info("Data collection complete: source={}, elapsed={:.1f}s", result.source, time.time() - t0)
    return result


def write_parquet(result: CollectorResult, out_dir: Path = PROCESSED_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    result.ohlcv.to_parquet(out_dir / "ohlcv.parquet", index=False)
    result.flow.to_parquet(out_dir / "flow.parquet", index=False)
    result.index.to_parquet(out_dir / "index.parquet", index=False)
    result.metadata.to_parquet(out_dir / "metadata.parquet", index=False)
    # 데이터 출처를 사이드카로 기록 (다음 실행에서 캐시 유효성 판단에 사용).
    (out_dir / ".source").write_text(result.source, encoding="utf-8")
    logger.info("Wrote parquet files to {} (source={})", out_dir, result.source)


def load_parquet(out_dir: Path = PROCESSED_DIR) -> CollectorResult:
    ohlcv = pd.read_parquet(out_dir / "ohlcv.parquet")
    flow = pd.read_parquet(out_dir / "flow.parquet")
    index = pd.read_parquet(out_dir / "index.parquet")
    metadata = pd.read_parquet(out_dir / "metadata.parquet")
    return CollectorResult(ohlcv=ohlcv, flow=flow, index=index, metadata=metadata, source="parquet")
