# KOSPI Audition Pyramid Dashboard (v2.1)

Decision-support dashboard for KOSPI/KOSDAQ. Selects strong names by Audition
Mode (**Sprint** for short-term momentum, **Marathon** for medium-term trend)
when the market Regime is favorable, applies pyramiding weights with
mode-differentiated stop-loss rules.

Built per `KOSPI_Audition_Pyramid_v2_1_PRD.docx`.

## Stage 1 (current) — Sprint MVP end-to-end

- Data collector (pykrx primary, deterministic synthetic fallback when KRX
  network is unavailable).
- Universe filter (market cap / 20D trade value / listing age / price).
- Regime filter: Trend / Breadth / Volatility → state + recommended Audition Mode.
- Factors: RS (5/20/60/120/252D), Acceleration, Rank Velocity, Volume, Flow.
- Sprint **and** Marathon scores side-by-side (PRD §2.4).
- S/A/B/C/D tiering with per-mode thresholds and caps.
- Mode-aware initial stop-loss levels (Sprint -6% KOSPI / -8% KOSDAQ).
- JSON exports: `regime_data.json`, `ranking_sprint.json`,
  `ranking_marathon.json`, `new_leaders.json`, `sector_data.json`, `risk_alerts.json`.
- HTML dashboard with mode toggle, Pyramid widget, Mode Comparison, New Leaders,
  Sector Summary, Risk Alerts.

## Run

```bash
pip install pandas numpy pyarrow loguru duckdb pykrx pytest

# 첫 실행 — pykrx로 실데이터 수집 (~2-3분)
python scripts/run_analysis.py --refresh

# 그 다음부터는 캐시 사용 (~5초)
python scripts/run_analysis.py

# 대시보드 서버 (프로젝트 루트에서)
python -m http.server 8765
# 브라우저: http://localhost:8765/dashboard/
```

`--refresh` 없이 실행하면 12시간 이내의 parquet 캐시(`data/processed/`)를 재사용합니다.
pykrx 실패 시 자동으로 합성(synthetic) 데이터로 폴백합니다. 캐시 정책은
`kap/config.py`의 `DATA_FETCH` 블록에서 조정.

## Tests

```bash
pip install pytest
pytest tests/
```

## Layout

```
kap/
  config.py         # all magic numbers, MODES, weights, thresholds
  data/             # collector + universe
  regime/           # regime filter + recommended mode
  factors/          # rs, acceleration, rank_velocity, volume, flow
  modes/            # sprint, marathon score
  ranking/          # tier classification, leader score
  risk/             # mode-aware stop loss
  export/           # JSON exporter
dashboard/          # HTML / CSS / JS
scripts/            # run_analysis.py
tests/              # pytest suite
```

## Roadmap

- **Stage 2** (next): full Volume/Flow refinement, Soft Migration on mode switch,
  Entry Signal classification (Breakout / VCP / Pullback), Sector Cap with
  Correlation Cluster.
- **Stage 3**: DART fundamentals, Quality Gate, Earnings Drift, Sector Power
  Score, Vol-adjusted weights, Walk-Forward backtest.
- **Stage 4**: scheduler, alerts, paper-trading mode.
