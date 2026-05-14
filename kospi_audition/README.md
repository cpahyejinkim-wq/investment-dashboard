# KOSPI Audition Pyramid Dashboard (v2.1)

Stage 1 MVP of the dual-horizon (Sprint / Marathon) audition pyramiding system
defined in `KOSPI_Audition_Pyramid_v2_1_PRD.docx`.

## Stage 1 scope (implemented)

| Stage 1 deliverable | Status |
| --- | --- |
| Project skeleton (`pyproject.toml`, folders, `.gitignore`) | done |
| `kap/config.py` with full v2.1 `MODES` block | done |
| Data Collector (pykrx → parquet, synthetic offline fallback) | done |
| Universe filter (시총 / 거래대금 / 상장기간 / 가격) | done |
| Regime filter + recommended Audition Mode | done |
| RS factor over 5 / 20 / 60 / 120 / 252 day windows | done |
| Acceleration Score (RS 가속도 + 거래대금 가속도) | done |
| Rank Velocity (5D rank delta + percentile) | done |
| Sprint Mode score (PRD §2.4 weights) | done |
| Tier classification + Sprint pyramiding weights | done |
| Mode-aware Hard Stop / Trailing Stop / Time Stop | done |
| JSON exporter (`regime_data`, `ranking_sprint`, `risk_alerts`, `new_leaders`) | done |
| HTML dashboard skeleton + Mode Toggle (Marathon disabled until Stage 2) | done |
| `run_analysis.py` end-to-end runner | done |
| Pytest suite (11 tests) | passing |

## Run

```bash
cd kospi_audition
pip install -e .          # or pip install pandas numpy loguru pyarrow pytest
python run_analysis.py    # writes output/*.json
```

Open `dashboard/index.html` in a browser (served from this folder so that the
relative `../output/*.json` fetch works — e.g. `python -m http.server`).

## Offline mode

If `pykrx` cannot reach KRX (CI / sandbox), the collector emits deterministic
synthetic data so the rest of the pipeline still produces valid JSON. The log
clearly warns when synthetic data is being used.

## Stage 2 scope (implemented)

| Stage 2 deliverable | Status |
| --- | --- |
| Volume Score (TV spread / Up-Down volume / OBV slope) | done |
| Flow Score (외국인 / 기관 누적 순매수 percentile) | done (synthetic flow until pykrx flow wired) |
| Marathon Mode score + tier caps + base weights | done |
| Marathon Hard / Trailing / Time Stop (-10%/-12%, ATR×2.5, 30D) | done |
| Mode Toggle UI Sprint ↔ Marathon (regime recommendation pre-selects) | done |
| Mode Comparison widget (Top 10 intersection + health band) | done |
| Soft Migration position book (positions.json, entry-mode rules preserved) | done |
| Entry signals: Breakout / VCP / Pullback | done |
| Sector Cap (30%/25%) + Correlation Cluster (60D ≥ 0.80) | done |
| Stage 2 unit tests (10 additional) | passing |

## Outputs

```
output/
├── regime_data.json
├── ranking_sprint.json
├── ranking_marathon.json
├── mode_compare.json     # Stage 2 - Sprint vs Marathon Top 10 분기
├── risk_alerts.json
├── new_leaders.json
└── positions.json        # Stage 2 - Soft Migration position book + events
```

## Next stages (per PRD §13)

- Stage 3: DART fundamentals, Quality Gate, Earnings Drift, Sector Power Score,
  Leader Score, Volatility-Adjusted Weight, Walk-Forward backtest.
- Stage 4: Scheduler, Slack/Email alerts, Paper Trading hand-off.
