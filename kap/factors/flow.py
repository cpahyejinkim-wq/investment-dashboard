"""Flow Score (PRD §6.7).

Foreign + institutional 20-day cumulative net buying as a share of market cap.
"""

from __future__ import annotations

import pandas as pd
from loguru import logger


def _percentile_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average") * 100.0


def compute_flow(flow: pd.DataFrame, ohlcv: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    tickers = set(universe["ticker"])
    f = flow[flow["ticker"].isin(tickers)].copy().sort_values(["ticker", "date"])
    last_cap = ohlcv.sort_values("date").groupby("ticker").tail(1).set_index("ticker")["market_cap"]

    last20 = f.groupby("ticker").tail(20)
    foreign_cum = last20.groupby("ticker")["foreign_net_buy"].sum()
    inst_cum = last20.groupby("ticker")["inst_net_buy"].sum()

    foreign_rate = (foreign_cum / last_cap).reindex(foreign_cum.index)
    inst_rate = (inst_cum / last_cap).reindex(inst_cum.index)

    f_pct = _percentile_rank(foreign_rate)
    i_pct = _percentile_rank(inst_rate)
    score = (f_pct * 0.5 + i_pct * 0.5)

    # 5-day streak flags
    streak_foreign = (
        f.groupby("ticker").tail(5).groupby("ticker")["foreign_net_buy"].apply(lambda s: bool((s > 0).all()))
    )
    streak_inst = (
        f.groupby("ticker").tail(5).groupby("ticker")["inst_net_buy"].apply(lambda s: bool((s > 0).all()))
    )

    out = pd.DataFrame({
        "ticker": foreign_rate.index,
        "foreign_cum_rate_20d": foreign_rate.values,
        "inst_cum_rate_20d": inst_rate.values,
        "flow_score": score.values,
        "flow_pct": _percentile_rank(score).values,
        "foreign_5d_streak": streak_foreign.reindex(foreign_rate.index).fillna(False).values,
        "inst_5d_streak": streak_inst.reindex(foreign_rate.index).fillna(False).values,
    }).reset_index(drop=True)
    logger.info("Flow score computed for {} tickers", len(out))
    return out
