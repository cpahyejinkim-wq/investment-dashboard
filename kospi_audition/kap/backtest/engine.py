"""Backtest engine per PRD section 10.

Strategies (PRD §10.1):
  - kospi_bh       : KOSPI buy & hold (benchmark)
  - kosdaq_bh      : KOSDAQ buy & hold (benchmark)
  - sprint_only    : Sprint mode + risk + regime
  - marathon_only  : Marathon mode + risk + regime
  - dynamic        : Regime-recommended mode auto-rotation (v2.1 최종형)

The engine is intentionally compact — it operates on the long-form OHLCV
already produced by Stage 1/2 and on the benchmark index series, rebalancing
on a fixed cadence (default monthly, ~21 trading days).

Reported metrics (PRD §10.2):
  CAGR, MDD, Sharpe, Sortino, Calmar, monthly_win_rate, annual_turnover,
  cagr_after_costs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from kap import config
from kap.factors import acceleration, rank_velocity, rs, volume as volume_mod, flow as flow_mod
from kap.modes import marathon as marathon_mode
from kap.modes import sprint as sprint_mode
from kap.ranking import tier as tier_mod
from kap.regime import compute_regime


REBALANCE_INTERVAL = 21  # ~1 trading month


@dataclass
class BacktestResult:
    name: str
    equity_curve: pd.Series
    daily_returns: pd.Series
    annual_turnover: float
    n_rebalances: int

    def metrics(
        self, commission_pct: float = 0.0, slippage_pct: float = 0.0
    ) -> dict[str, float]:
        eq = self.equity_curve
        rets = self.daily_returns.dropna()
        if eq.empty or rets.empty:
            return {}
        years = (eq.index[-1] - eq.index[0]).days / 365.25
        cagr = float(eq.iloc[-1]) ** (1.0 / max(years, 1e-6)) - 1.0
        peak = eq.cummax()
        mdd = float((eq / peak - 1.0).min())
        std = float(rets.std())
        sharpe = float(np.sqrt(252) * rets.mean() / std) if std > 0 else 0.0
        downside = rets[rets < 0].std()
        sortino = float(np.sqrt(252) * rets.mean() / downside) if downside and downside > 0 else 0.0
        calmar = cagr / abs(mdd) if mdd < 0 else 0.0
        monthly = (1.0 + rets).resample("ME").prod() - 1.0
        monthly_win = float((monthly > 0).mean()) if len(monthly) else 0.0
        cost_drag = (commission_pct + slippage_pct) * self.annual_turnover
        cagr_after = cagr - cost_drag
        return {
            "cagr": cagr,
            "mdd": mdd,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "monthly_win_rate": monthly_win,
            "annual_turnover": self.annual_turnover,
            "cagr_after_costs": cagr_after,
        }


def _build_kospi_series(index_df: pd.DataFrame, name: str = "KOSPI") -> pd.Series:
    s = index_df[index_df["index_name"] == name].copy()
    s["date"] = pd.to_datetime(s["date"])
    return s.set_index("date")["close"].sort_index()


def _pivot_close(ohlcv: pd.DataFrame) -> pd.DataFrame:
    df = ohlcv.copy()
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot_table(index="date", columns="ticker", values="close").sort_index()


def buy_and_hold(index_df: pd.DataFrame, name: str = "KOSPI") -> BacktestResult:
    s = _build_kospi_series(index_df, name)
    rets = s.pct_change().fillna(0.0)
    equity = (1.0 + rets).cumprod()
    return BacktestResult(
        name=f"{name.lower()}_bh",
        equity_curve=equity,
        daily_returns=rets,
        annual_turnover=0.0,
        n_rebalances=0,
    )


def _ranking_at(
    ohlcv: pd.DataFrame, bench: pd.Series, as_of: pd.Timestamp, mode: str
) -> pd.DataFrame:
    """Compute the ranking using the price history up to ``as_of``."""
    sub = ohlcv[pd.to_datetime(ohlcv["date"]) <= as_of].copy()
    if sub.empty:
        return pd.DataFrame()
    bench_sub = bench.loc[:as_of]
    if bench_sub.empty:
        return pd.DataFrame()

    rs_df = rs.compute_rs(sub, bench_sub)
    if rs_df.empty:
        return pd.DataFrame()
    accel = acceleration.compute_acceleration(sub, bench_sub)
    score_hist = _wide_rs_history(sub, bench_sub)
    rv = rank_velocity.compute_rank_velocity(score_hist)
    vol = volume_mod.compute_volume_score(sub)
    fl = flow_mod.compute_flow_score(flow_mod.synthetic_flow(sub))

    if mode == "sprint":
        scored = sprint_mode.compute_sprint_score(rs_df, accel, rv, volume=vol, flow=fl)
        col = "sprint_score_pct"
    else:
        scored = marathon_mode.compute_marathon_score(rs_df, accel, rv, volume=vol, flow=fl)
        col = "marathon_score_pct"

    tiered = tier_mod.assign_tiers(scored, mode=mode, score_pct_col=col)
    tiered = tier_mod.assign_weights(
        tiered,
        mode=mode,
        regime_multiplier=1.0,
        allowed_tiers=["S", "A", "B"],
    )
    tiered = tiered[tiered["tier"].isin(["S", "A", "B"])]
    return tiered[["ticker", "weight", "tier"]]


def _wide_rs_history(ohlcv: pd.DataFrame, bench: pd.Series, n_days: int = 10) -> pd.DataFrame:
    wide = _pivot_close(ohlcv)
    bench = bench.copy()
    bench.index = pd.to_datetime(bench.index)
    window = 20
    rows: dict[pd.Timestamp, pd.Series] = {}
    for d in wide.index[-n_days:]:
        if d not in bench.index:
            continue
        i = wide.index.get_indexer([d])[0]
        if i < window:
            continue
        past = wide.index[i - window]
        if past not in bench.index:
            continue
        b_now = float(bench.loc[d])
        b_past = float(bench.loc[past])
        if b_past == 0:
            continue
        rows[d] = (wide.loc[d] / wide.loc[past]) / (b_now / b_past) - 1.0
    return pd.DataFrame(rows).T.sort_index() if rows else pd.DataFrame()


def run_strategy(
    ohlcv: pd.DataFrame,
    index_df: pd.DataFrame,
    mode_selector,
    name: str,
    start: pd.Timestamp | None = None,
    rebalance: int = REBALANCE_INTERVAL,
) -> BacktestResult:
    """Backtest a long-only momentum strategy.

    ``mode_selector(as_of, regime) -> "sprint" | "marathon" | "cash"``
    """
    close = _pivot_close(ohlcv)
    bench = _build_kospi_series(index_df)
    if start is not None:
        close = close.loc[start:]
    if close.empty:
        return BacktestResult(name=name, equity_curve=pd.Series(dtype=float),
                              daily_returns=pd.Series(dtype=float),
                              annual_turnover=0.0, n_rebalances=0)

    weights: pd.Series = pd.Series(dtype=float)
    equity = [1.0]
    rets: list[float] = [0.0]
    dates = list(close.index)
    turnover_sum = 0.0
    n_rebalances = 0

    for i, today in enumerate(dates):
        # Daily PnL from the previous weights vs. today's close.
        if i > 0 and not weights.empty:
            prev_close = close.iloc[i - 1]
            today_close = close.iloc[i]
            day_ret = ((today_close / prev_close - 1.0) * weights).reindex(weights.index).sum()
            if pd.isna(day_ret):
                day_ret = 0.0
            equity.append(equity[-1] * (1.0 + float(day_ret)))
            rets.append(float(day_ret))
        else:
            if i > 0:
                equity.append(equity[-1])
                rets.append(0.0)

        # Rebalance at first day and every ``rebalance`` days.
        if i % rebalance == 0:
            regime = compute_regime(index_df=index_df, market_ohlcv=ohlcv[pd.to_datetime(ohlcv["date"]) <= today])
            mode = mode_selector(today, regime)
            if mode == "cash" or not regime.allow_new_entry:
                new_weights = pd.Series(dtype=float)
            else:
                ranking = _ranking_at(ohlcv, bench, today, mode)
                if ranking.empty:
                    new_weights = pd.Series(dtype=float)
                else:
                    new_weights = ranking.set_index("ticker")["weight"]
                    invested = float(new_weights.sum())
                    cap = 1.0 - config.MODES[mode]["min_cash"]
                    if invested > cap and invested > 0:
                        new_weights = new_weights * (cap / invested)
            # Turnover = sum of absolute weight changes / 2.
            combined = pd.concat([weights, new_weights], axis=1).fillna(0.0)
            turnover = float((combined.iloc[:, 0] - combined.iloc[:, 1]).abs().sum() / 2.0)
            turnover_sum += turnover
            weights = new_weights
            n_rebalances += 1

    eq_series = pd.Series(equity, index=dates[: len(equity)])
    ret_series = pd.Series(rets, index=dates[: len(rets)])
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-6)
    annual_turnover = turnover_sum / years
    return BacktestResult(
        name=name,
        equity_curve=eq_series,
        daily_returns=ret_series,
        annual_turnover=annual_turnover,
        n_rebalances=n_rebalances,
    )


def sprint_only(today: pd.Timestamp, regime) -> str:  # noqa: ARG001
    return "sprint" if regime.allow_new_entry else "cash"


def marathon_only(today: pd.Timestamp, regime) -> str:  # noqa: ARG001
    return "marathon" if regime.allow_new_entry else "cash"


def dynamic(today: pd.Timestamp, regime) -> str:  # noqa: ARG001
    return regime.recommended_mode


def run_all(
    ohlcv: pd.DataFrame, index_df: pd.DataFrame, start: pd.Timestamp | None = None
) -> dict[str, BacktestResult]:
    return {
        "kospi_bh": buy_and_hold(index_df, "KOSPI"),
        "kosdaq_bh": buy_and_hold(index_df, "KOSDAQ"),
        "sprint_only": run_strategy(ohlcv, index_df, sprint_only, "sprint_only", start=start),
        "marathon_only": run_strategy(ohlcv, index_df, marathon_only, "marathon_only", start=start),
        "dynamic": run_strategy(ohlcv, index_df, dynamic, "dynamic", start=start),
    }
