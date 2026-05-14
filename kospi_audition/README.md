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

## Stage 4 scope (implemented)

| Stage 4 deliverable | Status |
| --- | --- |
| 4-1 `scheduler.py` (cron-friendly `once` + standalone `loop` mode) | done |
| 4-2 Slack/Email alerts (Risk / Regime change / Mode mismatch ≥ N days) | done |
| 4-3 Paper Trading book (`output/paper_trading.json`, slippage + commission) | done |
| 4-4 Retry decorator (exponential back-off) on data + notification calls | done |
| 4-5 Performance pass on `volume_score` (per-ticker loops → vectorised groupby) | done |
| 4-6 Operations manual (이 README 하단 섹션) | done |
| Stage 4 unit tests (10 additional) | passing |

### Stage 4 outputs

```
output/paper_trading.json   # NAV history + holdings + trade log
output/run_history.json     # 이전 regime / mode mismatch streak (알림용)
```

---

## 운영 매뉴얼

### 1. 일일 운영 흐름

```
15:30 KST  → scheduler 가 run_analysis.py 트리거 (또는 crontab)
             ├── pykrx 데이터 수집 (실패 시 3회 재시도, 모두 실패 시 synthetic)
             ├── Regime → Factors → Mode Scores → Tier → Stops
             ├── Soft Migration position book 갱신
             ├── (옵션) 백테스트 / Paper Trading 갱신
             └── (옵션) Slack/Email 알림 dispatch
15:35 KST  → output/*.json 갱신, dashboard 자동 반영
```

### 2. 권장 crontab (예: KST 시스템)

```
30 15 * * 1-5  cd /opt/kap && /usr/bin/python3 scheduler.py once --paper-trading --notify
```

### 3. 알림 채널 환경변수

| 변수 | 설명 |
| --- | --- |
| `KAP_SLACK_WEBHOOK` | Slack incoming-webhook URL (필요 시) |
| `KAP_SMTP_HOST` / `KAP_SMTP_PORT` | SMTP 서버 |
| `KAP_SMTP_USER` / `KAP_SMTP_PASSWORD` | 인증 (선택) |
| `KAP_SMTP_FROM` / `KAP_SMTP_TO` | 발신/수신 주소 |

채널이 하나도 설정되지 않으면 알림은 무음 처리되고 로그에만 기록됩니다.

### 4. 알림 트리거

- **Risk Alert**: Hard Stop 도달 (당일 종가 ≤ stop_loss)
- **Regime Transition**: regime state 변경 (예: risk_on → risk_off)
- **Mode Mismatch**: 권장 모드와 실제 모드가 `MODE_TRANSITION.alert_mismatch_days`일 (기본 3일) 연속 불일치

### 5. Paper Trading 운영 (PRD §13.4-3)

```
python run_analysis.py --paper-trading
```

- 초기 자본 1억원
- 매 실행마다 active mode 의 weight target 으로 리밸런싱
- 슬리피지/수수료 적용 (`config.BACKTEST.slippage_pct`, `commission_pct`)
- `output/paper_trading.json` 에 NAV / 보유종목 / 체결로그 유지
- PRD 권고: 실전 투입 전 최소 3개월 운용 후 결과 검토

### 6. 에러 복구

- `kap.ops.retry` 데코레이터: 3회 재시도, 백오프 2 → 4 → 8초
- 데이터 fetch 실패 → 결정론적 synthetic 데이터로 자동 폴백 (개발/테스트에서만 사용)
- 알림 dispatch 실패 → 로그만 남기고 파이프라인은 정상 종료

### 7. 성능 가이드

| 단계 | 측정 (200종목 / 400일) |
| --- | --- |
| 데이터 수집 + 파케이 저장 | < 1초 (synthetic) |
| 팩터 + 모드 점수 + Tier | ~1초 |
| Stage 1+2+3 (백테스트 제외) | ~3초 |
| 백테스트 5종 (Sprint/Marathon/Dynamic/2 BH) | ~2분 |
| Walk-Forward (--with-walk-forward) | 수 분 ~ 십수 분 |

운영 모드에서는 백테스트는 주말 1회 실행을 권장합니다.

### 8. 검증 체크리스트 (PRD §16)

- [ ] `run_analysis.py` 5분 이내 정상 완료
- [ ] Mode Toggle 정상 작동 + Soft Migration 검증
- [ ] Sprint/Marathon 백테스트 합리적 결과 (Sprint Sharpe ≥ 1.2)
- [ ] Dynamic 전략이 단일 모드보다 우수한가 검증
- [ ] Risk Alert 시나리오 (Hard stop / Regime stop / Time stop) 정상 동작
- [ ] Paper Trading 3개월 운용 결과 검토 후 실전 인계
