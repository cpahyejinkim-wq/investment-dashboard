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

## Next stages (per PRD §13)

- Stage 2: Volume / Flow scores, Marathon mode, Mode Comparison widget, Soft
  Migration, Entry Signals (Breakout / VCP / Pullback), Sector Cap +
  Correlation Cluster.
- Stage 3: DART fundamentals, Quality Gate, Earnings Drift, Sector Power Score,
  Leader Score, Walk-Forward backtest.
- Stage 4: Scheduler, Slack/Email alerts, Paper Trading hand-off.
