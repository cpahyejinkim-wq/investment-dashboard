"""Sector cap + Correlation Cluster enforcement per PRD section 7.4.

  Single GICS sector  <= 30%
  Single KRX industry <= 25%
  60-day rolling correlation >= 0.80 -> treat group as single position cluster.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kap import config


def enforce_sector_cap(
    positions: pd.DataFrame,
    sector_col: str = "sector",
    weight_col: str = "weight",
    cap: float = config.RISK["sector_cap_krx"],
) -> pd.DataFrame:
    """Pro-rata downscale weights that breach the per-sector cap."""
    if positions.empty or sector_col not in positions.columns:
        return positions
    df = positions.copy()
    totals = df.groupby(sector_col)[weight_col].sum()
    scale = (totals.clip(upper=cap) / totals.replace(0, np.nan)).fillna(1.0)
    df["__scale"] = df[sector_col].map(scale).fillna(1.0)
    df[weight_col] = df[weight_col] * df["__scale"]
    return df.drop(columns="__scale")


def correlation_clusters(
    ohlcv: pd.DataFrame,
    tickers: list[str],
    threshold: float = config.RISK["correlation_threshold"],
    window: int = 60,
) -> dict[str, int]:
    """Return {ticker: cluster_id}. Cluster id is the index of its representative."""
    if not tickers:
        return {}
    df = ohlcv[ohlcv["ticker"].isin(tickers)].copy()
    df["date"] = pd.to_datetime(df["date"])
    wide = (
        df.pivot_table(index="date", columns="ticker", values="close")
        .sort_index()
        .pct_change()
        .tail(window)
    )
    if wide.empty:
        return {t: i for i, t in enumerate(tickers)}
    corr = wide.corr()

    cluster: dict[str, int] = {}
    next_id = 0
    for t in tickers:
        if t in cluster or t not in corr.index:
            continue
        cluster[t] = next_id
        for other in corr.columns:
            if other == t or other in cluster:
                continue
            c = float(corr.loc[t, other]) if not pd.isna(corr.loc[t, other]) else 0.0
            if c >= threshold:
                cluster[other] = next_id
        next_id += 1
    for t in tickers:
        cluster.setdefault(t, -1)
    return cluster


def apply_correlation_cap(
    positions: pd.DataFrame,
    ohlcv: pd.DataFrame,
    weight_col: str = "weight",
    cluster_cap: float | None = None,
) -> pd.DataFrame:
    """Within each correlation cluster, cap aggregate weight to ``cluster_cap``.

    Defaults ``cluster_cap`` to the same value as the KRX sector cap.
    """
    if positions.empty:
        return positions
    cap = cluster_cap if cluster_cap is not None else config.RISK["sector_cap_krx"]
    df = positions.copy()
    tickers = df["ticker"].tolist()
    clusters = correlation_clusters(ohlcv, tickers)
    df["__cluster"] = df["ticker"].map(clusters)
    totals = df.groupby("__cluster")[weight_col].sum()
    scale = (totals.clip(upper=cap) / totals.replace(0, np.nan)).fillna(1.0)
    df["__scale"] = df["__cluster"].map(scale).fillna(1.0)
    df[weight_col] = df[weight_col] * df["__scale"]
    return df.drop(columns=["__cluster", "__scale"])
