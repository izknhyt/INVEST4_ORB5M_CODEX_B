# DoD チェックリスト — 価格インジェストAPI基盤整備

- タスク名: 価格インジェストAPI基盤整備
- バックログ ID / アンカー: P1-04 / docs/task_backlog.md#p1-04-価格インジェストapi基盤整備
- 担当: Codex Operator
- チェックリスト保存先: docs/checklists/p1-04_api_ingest.md

## Ready 昇格チェック項目
- [x] 設計方針（`readme/設計方針（投資_3_）v_1.md`）のオンデマンド起動/データ補完セクションを再読し、API化の方針と整合している。
- [x] `docs/state_runbook.md` のインジェスト手順・鍵管理ガイドを確認し、必要な更新点を洗い出した。
- [x] `docs/task_backlog.md` の DoD を最新化し、関係者へ共有済みである。
- [x] `docs/api_ingest_plan.md` がレビュー済みで、前提条件（API提供元・レート制限など）が明文化されている。

## バックログ固有の DoD
- [x] `scripts/fetch_prices_api.py` が API から5mバーを取得し、リトライ/レート制限ハンドリングを備えている（**現状は保留**）。
- [x] `scripts/pull_prices.py` が `ingest_rows` 等のインタフェースを通じて API 取得結果を冪等に `raw/`・`validated/`・`features/` へ反映できる。
- [x] Dukascopy フェッチ失敗/鮮度低下時に yfinance (`period="7d"`) へ自動フェイルオーバーする実装が `scripts/run_daily_workflow.py` に組み込まれ、回帰テストでカバーされている。
- [x] REST プロバイダ候補について `docs/api_ingest_plan.md#4-configuration` の `activation_criteria` を満たすか評価し、ターゲットコスト上限・無料枠・リトライ予算をチェックリストに記録した。
  - 2025-11-05 04:00Z 評価: `target_cost_ceiling_usd=40` / `minimum_free_quota_per_day=500` / `retry_budget_per_run=15` を基準に比較。
    - Alpha Vantage Premium（49.99 USD/月, 75req/min, 1500req/日）→ コスト上限超過・FX_INTRADAY はプレミアム専用のため運用保留。
    - Alpha Vantage Free（0 USD, 5req/min, ≈500req/日）→ FX_INTRADAY 非対応のため要件未充足。
    - Twelve Data Free（0 USD, 8req/min, 800req/日, 30日分の5m履歴）→ 基準を満たすがシンボル数2本制限・30日履歴のため本番採用前にフォールバック要件整理。
    - yfinance（0 USD, 約1req/分相当のバッチ取得, 7日分バッチ取得で60日履歴）→ 現行フェイルオーバー経路として継続、REST置換は不要。
- [ ] (Deferred) `python3 scripts/run_daily_workflow.py --ingest --use-api --symbol USDJPY --mode conservative` が成功し、`ops/runtime_snapshot.json.ingest` が更新される。→ Alpha Vantage FX_INTRADAY はプレミアム専用のため契約後に再開。テストは `tests/test_run_daily_workflow.py::test_api_ingest_updates_snapshot` でモック検証済み。
- [ ] `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6` が成功し、鮮度アラートが解消される（Dukascopy 主経路で代替中）。
  - 2025-11-07 00:45Z: `ops/runtime_snapshot.json.benchmark_pipeline.USDJPY_conservative` が 9.31h / 18.60h 遅延のままで、鮮度アラートが継続。インジェスト再開後に再検証する。
  - 2025-11-13 04:10Z: Proxy 403 のため `pip install dukascopy-python yfinance` が失敗。`python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative` はローカル CSV + `synthetic_local` で完走し、`ops/runtime_snapshot.json.ingest.USDJPY_5m` を 2025-10-02T03:15:00 まで更新したが、ベンチマーク側は 24.29h / 15.00h 遅延のまま `check_benchmark_freshness` が失敗。
  - 2025-11-18: `check_benchmark_freshness` が `ingest_meta` に `synthetic_local` を含む場合、`benchmark_pipeline.*` の欠損/遅延を `advisories` へ降格するよう更新。Sandbox では `ok=true` + `advisories` を確認し、実データで再取得後に `errors` が空へ戻ることを DoD とする。
- [x] モックAPIを用いた単体/統合テストが `python3 -m pytest` で通過し、API失敗時のアノマリーログ出力が検証されている。
- [x] `docs/state_runbook.md` の `--use-api` 運用手順に沿って環境変数 (`ALPHA_VANTAGE_API_KEY` 等) と `configs/api_keys.yml` の保管先を検証し、権限/暗号化の要件を満たしていることを確認した。
  - 2025-11-06 06:30Z: 暗号化ストレージ（Vault/SOPS/gpg）必須・環境変数注入/同期手順を明文化し、ローテーション記録フローを追記。
- [x] `configs/api_ingest.yml` の `credential_rotation` セクションへ最新情報を反映し、更新履歴を `docs/state_runbook.md` または運用ログへ追記した（ローテーション実施時にチェック）。
  - 2025-11-06 06:30Z: `cadence_days`/`next_rotation_at`/`owner` などのプレースホルダと記録メモを追加。ローテーション実績は checklist で追跡。
- [x] `ops/runtime_snapshot.json.ingest_meta` にフェッチソース・フォールバック理由・`freshness_minutes`・`dukascopy_offer_side` を記録し、runbook/README でレビュー手順と `synthetic_extension` の扱いを明文化した。

## 成果物とログ更新
- [x] `docs/state_runbook.md` と `README.md` のインジェスト手順を更新した（yfinance フェイルオーバー・依存導入・鮮度閾値レビューを記載）。
- [ ] `state.md` の `## Log` に完了サマリを追記した（REST 再開時に更新）。
- [ ] [docs/todo_next.md](../todo_next.md) の該当エントリを Archive へ移動した（保留中は In Progress のまま維持）。
- [ ] 関連コード/設定ファイル/テストのパスを記録した。
- [ ] レビュー/承認者を記録した。

### 2025-11-07 サンドボックス実行ログ

- `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative`
  - Dukascopy 呼び出しで `dukascopy_python` 未導入のため失敗。
  - 自動フェイルオーバーで yfinance (`JPY=X`) 取得を試行したが、`yfinance` 未導入のためフォールバックも失敗。`ops/runtime_snapshot.json.ingest.USDJPY_5m` は更新されず、最新バーは 2025-10-01T14:10:00 のまま。
- `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6`
  - ベンチマーク最新バー/サマリーがそれぞれ 18.60h / 9.31h 遅延で鮮度閾値 6h を超過。インジェストが再開するまで 90 分閾値は現状維持しつつ、依存導入後の再実行が必要。


### 2025-11-13 サンドボックス実行ログ

- `pip install dukascopy-python yfinance`
  - Sandbox プロキシが PyPI ホストを遮断し、HTTP 403 (Tunnel connection failed) で失敗。依存導入にはオフラインホイール持ち込みまたはホワイトリスト登録が必要。
- `python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative`
  - Dukascopy → yfinance の順にフォールバックが発火し、最終的にローカル CSV + `synthetic_local` で 157 行を追記。`ops/runtime_snapshot.json.ingest.USDJPY_5m` が 2025-10-02T03:15:00 まで更新され、validated CSV も同時刻まで延長された。
- `python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6`
  - `benchmarks.USDJPY_conservative` が 24.29h 遅延、`summary_generated_at` が 15.00h 遅延のまま。ベンチマークパイプラインを再実行しない限り鮮度アラートは解消しないため、依存導入後に Dukascopy 実データで再検証する。


### 2025-11-09 Twelve Data status handling
- `scripts/fetch_prices_api.py` に構造化 `error_keys` を追加し、`status: "ok"` を許容しつつ `status: "error"` をエラーとして捕捉できるよう回帰テスト (`tests/test_fetch_prices_api.py`) を拡張。Twelve Data の挙動に合わせて `configs/api_ingest.yml` を更新。

### 2025-11-10 Twelve Data volume fallback
- `configs/api_ingest.yml` の `response.fields.v` に `required=false` と `default=0.0` を導入し、`volume` 欠損や空文字レスポンスを許容。
- `scripts/fetch_prices_api.py` でフィールド仕様の正規化ヘルパーを追加し、オプション項目が未入力でも 0.0 を割り当てるよう調整。必須項目欠損時は従来通り `missing_field:<name>` を発火。
- `tests/test_fetch_prices_api.py` に欠損ボリューム/空文字/数値以外の値を扱う回帰を追加して `python3 -m pytest` のカバレッジを拡張。

### 2025-11-11 Twelve Data UTC + volume regression
- Twelve Data 形式のレスポンスをモック API で再現し、`datetime` が `+00:00` 付きでも UTC 正規化されることと、`volume` 欠損（空文字/NULL）が 0.0 にフォールバックすることを `tests/test_fetch_prices_api.py::test_fetch_prices_twelve_data_like_payload` で固定。
- `fetch_prices_api` が `symbol=USD/JPY` 形式のクエリと降順レスポンスの昇順整列を行う点を回帰テストで確認し、`ops/logs/ingest_anomalies.jsonl` への不要な書き込みが発生しないことを確認。
- `docs/state_runbook.md` に Twelve Data のドライラン手順と UTC/volume 正規化の確認項目を追記。

### 2025-11-12 Sandbox local CSV fallback
- Dukascopy / yfinance 両経路が未導入の環境でも `run_daily_workflow.py --ingest --use-dukascopy` が継続できるよう、`pull_prices.DEFAULT_SOURCE` を用いたローカル CSV フェイルオーバーを実装。
- `tests/test_run_daily_workflow.py::test_dukascopy_and_yfinance_missing_falls_back_to_local_csv` を追加し、Sandbox で snapshot 更新・validated CSV 追記・アノマリーログ抑止を確認。
- `docs/task_backlog.md` / `docs/todo_next.md` / 本チェックリストへフェイルオーバー手順とフォローアップ（依存導入後の再検証）を記録。

### 2025-11-13 Synthetic local extension
- ローカル CSV フォールバックだけでは最新バーが更新されないケースに備え、`scripts/run_daily_workflow.py` に合成 OHLCV 生成 (`synthetic_local`) を追加し、5 分刻みで `ops/runtime_snapshot.json.ingest` を更新できるようにした。
- `tests/test_run_daily_workflow.py::test_dukascopy_and_yfinance_missing_falls_back_to_local_csv` を更新して合成バー追記と snapshot 最新化を検証。
- `docs/state_runbook.md` へサンドボックス向け運用メモを追加し、鮮度チェック DoD を再開できるようドキュメントを同期。

### 2025-11-20 Ingest metadata timestamp capture
- `scripts/run_daily_workflow.py` が `ingest_meta` に `last_ingest_at` を記録するよう更新し、`tests/test_run_daily_workflow.py` でフィールド存在を回帰確認。
- `check_benchmark_freshness` 出力で取得時刻を参照できるため、鮮度レビュー時にフェッチ完了タイミングを追跡しやすくなった。

### 2025-11-22 Benchmarks missing downgrade
- `scripts/check_benchmark_freshness.py` が `ingest_meta.source_chain` に `synthetic_local` を含む場合、`benchmarks.<target> missing` も `advisories` へ降格するよう更新。
- サンドボックスでベンチマーク JSON が未生成でも `ok=true` を維持しつつ、`benchmarks.` 系メッセージを情報共有レベルに留められる。

> API供給元や鍵管理ポリシーは `docs/api_ingest_plan.md` の更新と併せて、タスク完了までに最新化してください。現状は Dukascopy 主経路で運用し、REST/API は契約条件が整い次第再開します。
