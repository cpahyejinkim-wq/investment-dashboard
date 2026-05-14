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

## Stage 3 scope (implemented)

| Stage 3 deliverable | Status |
| --- | --- |
| 3-1 DART fundamentals connector (synthetic fallback) | done |
| 3-2 Quality Score Gate (Sprint lenient on S, Marathon strict on S/A) | done |
| 3-3 Earnings Drift (PEAD) for Marathon weight 5% | done |
| 3-4 Sector Power Score (RS 50% + NewLeader 30% + TV growth 20%) + widget | done |
| 3-5 New Leaders widget (이미 Stage 1에서 활성) | done |
| 3-6 Leader Score 통합지표 (0.7 mode_score + 0.3 survival_weighted) | done |
| 3-7 Volatility-Adjusted Weight (opt-in via config) | done |
| 3-8 Backtest Engine: kospi_bh / kosdaq_bh / sprint / marathon / dynamic | done |
| 3-9 Walk-Forward harness (train 24m / test 6m / step 3m) | done |
| 3-10 Out-of-Sample (2023+ cutoff) | done |
| Stage 3 unit tests (9 additional) | passing |

### Stage 3 outputs

```
output/sector_power.json        # 섹터별 power + top tickers
output/backtest_results.json    # 5개 전략 metrics
```

Run with `python run_analysis.py --with-backtest` (또는 `--with-walk-forward`).

## Next stage (per PRD §13.4)

- Stage 4: scheduler.py + Slack/Email alerts + Paper Trading mode + 운영 매뉴얼.
