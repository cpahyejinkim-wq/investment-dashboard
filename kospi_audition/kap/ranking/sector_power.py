"""Sector Power Score per PRD section 9.1.

  SectorPower = 0.50 * Sector_RS_pct
              + 0.30 * NewLeader_pct        (신규 S/A Tier 진입 종목 수 비율)
              + 0.20 * TradingAmountGrowth  (TV_20D / TV_60D)
  -> cross-sectional percentile per sector.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_sector_power(
    ranking: pd.DataFrame,
    ohlcv: pd.DataFrame,
    sector_col: str = "sector",
) -> pd.DataFrame:
    if ranking.empty or sector_col not in ranking.columns:
        return pd.DataFrame()

    df = ranking[[ "ticker", sector_col, "tier", "mode_score_pct"]].copy()

    # Sector RS = mean of constituent mode_score_pct.
    sector_rs = df.groupby(sector_col)["mode_score_pct"].mean().rename("sector_rs_pct")

    # New leader = current S or A tier count per sector.
    new_leader = (
        df[df["tier"].isin(["S", "A"])]
        .groupby(sector_col)["ticker"]
        .count()
        .rename("new_leader_count")
    )
    total_per_sector = df.groupby(sector_col)["ticker"].count().rename("total_count")
    new_leader_ratio = (new_leader / total_per_sector).rename("new_leader_ratio").fillna(0.0)

    # Trading amount growth = sector mean of TV_20D / TV_60D.
    ohlcv = ohlcv.copy()
    ohlcv["date"] = pd.to_datetime(ohlcv["date"])
    ohlcv = ohlcv.sort_values(["ticker", "date"])
    tv_short = (
        ohlcv.groupby("ticker")["trade_value"].apply(lambda s: s.tail(20).mean()).rename("tv_20d")
    )
    tv_long = (
        ohlcv.groupby("ticker")["trade_value"].apply(lambda s: s.tail(60).mean()).rename("tv_60d")
    )
    tv = pd.concat([tv_short, tv_long], axis=1).reset_index()
    tv["tv_growth"] = tv["tv_20d"] / tv["tv_60d"].replace(0.0, np.nan)
    tv = tv.merge(df[["ticker", sector_col]], on="ticker", how="left")
    sector_tv = tv.groupby(sector_col)["tv_growth"].mean().rename("trading_amount_growth")

    new_leader_count = new_leader.rename("new_leader_count")
    out = pd.concat(
        [sector_rs, new_leader_count, new_leader_ratio, sector_tv, total_per_sector],
        axis=1,
    ).reset_index()
    out["new_leader_count"] = out["new_leader_count"].fillna(0).astype(int)
    out["sector_rs_pct_norm"] = out["sector_rs_pct"].rank(pct=True, method="average") * 100.0
    out["new_leader_pct_norm"] = out["new_leader_ratio"].rank(pct=True, method="average") * 100.0
    out["tv_growth_pct_norm"] = (
        out["trading_amount_growth"].rank(pct=True, method="average") * 100.0
    )
    out[["sector_rs_pct_norm", "new_leader_pct_norm", "tv_growth_pct_norm"]] = (
        out[["sector_rs_pct_norm", "new_leader_pct_norm", "tv_growth_pct_norm"]].fillna(50.0)
    )
    out["sector_power"] = (
        0.50 * out["sector_rs_pct_norm"]
        + 0.30 * out["new_leader_pct_norm"]
        + 0.20 * out["tv_growth_pct_norm"]
    )
    return out.sort_values("sector_power", ascending=False)


def top_tickers_per_sector(
    ranking: pd.DataFrame, sector_col: str = "sector", top_k: int = 3
) -> dict[str, list[str]]:
    if ranking.empty or sector_col not in ranking.columns:
        return {}
    out: dict[str, list[str]] = {}
    for sector, g in ranking.sort_values("mode_score_pct", ascending=False).groupby(sector_col):
        out[str(sector)] = g["ticker"].head(top_k).tolist()
    return out
