# state.json 運用ガイド

## 目的
EV ゲートや滑り学習などの内部状態を `state.json` として保存し、次回の実行時に引き継ぐことで、ウォームアップを短縮しつつ過去の統計を活用する。

## 保存手順
1. `BacktestRunner` 実行終了後、`runner.export_state()` を呼び出す。
2. 返却された辞書を JSON として保存する。`scripts/run_sim.py` は既定で `ops/state_archive/<strategy>/<symbol>/<mode>/` 以下へ時刻付きファイルを自動保存し、`--out-dir` 指定時は run フォルダにも `state.json` を残す。保存成功時には `scripts/aggregate_ev.py` が自動で呼び出され、EVプロファイル (YAML/CSV) を更新する。
3. 自動アーカイブを無効化したい場合は `--no-auto-state` を付ける。保存先を変えたいときは `--state-archive path/to/dir` を利用する。EVプロファイル更新をスキップしたい場合は `--no-aggregate-ev` を併用する。
4. 運用では日次または週次で最新の state を確認し、事故時に復元できるようバージョン管理する。

## ロード手順
- CLI 実行時に自動で最新 state が読み込まれる（`ops/state_archive/<strategy>/<symbol>/<mode>/` で最も新しい JSON）。
- 自動ロードを避けたい場合は `--no-auto-state` を指定する。
- コードから: `runner.load_state_file(path)` または `runner.load_state(state_dict)` を利用。

## オンデマンド起動フロー（ノートPC向け）
- PC 起動/ログイン時に以下の順で CLI を実行すると、停止中の期間を自動補完して通常運用へ復帰できます。

```
python3 scripts/run_daily_workflow.py --ingest --update-state --benchmarks --state-health --benchmark-summary
```

- 個別の実行例
  - 取り込み: `python3 scripts/pull_prices.py --source data/usdjpy_5m_2018-2024_utc.csv`
  - Dukascopy 経由（標準経路）: `python3 -m scripts.run_daily_workflow --ingest --use-dukascopy --symbol USDJPY --mode conservative`
  - API 直接取得（保留中）: `python3 -m scripts.run_daily_workflow --ingest --use-api --symbol USDJPY --mode conservative` ※ Alpha Vantage FX_INTRADAY がプレミアム専用のため 2025-10 時点では契約後に再開予定。
  - state更新: `python3 scripts/update_state.py --bars validated/USDJPY/5m.csv --chunk-size 20000`
  - 検証・集計: `python3 scripts/run_benchmark_runs.py --bars validated/USDJPY/5m.csv --windows 365,180,90` → `python3 scripts/report_benchmark_summary.py --plot-out reports/benchmark_summary.png`
  - ヘルスチェック: `python3 scripts/check_state_health.py`

## 推奨運用
- **バックアップ:** 自動アーカイブされた最新ファイル（例: `ops/state_archive/.../<timestamp>_runid.json`）を基準に、必要に応じて別途バックアップを取得する。
- **互換性:** RunnerConfig（特にゲート設定・戦略パラメータ）を大幅に変更した際は、古い state がバイアスになる場合がある。必要に応じてリセット（初期化）を検討する。
- **監査ログ:** `ops/state_archive/` など保存先を決め、保存日時・使った戦略パラメータと一緒にメタ情報を付与する。
- **EVプロファイル:** `scripts/aggregate_ev.py --strategy ... --symbol ... --mode ...` を使うと、アーカイブ済み state から長期/直近期の期待値統計を集約し、`configs/ev_profiles/` に YAML プロファイルを生成できます。`run_sim.py` は該当プロファイルを自動ロードして EV バケットをシードします（`--no-ev-profile` で無効化可能）。
- **アーカイブの整理（任意）:** `ops/state_archive/` は運用で増えていきます。最新 N 件のみ残す場合は `scripts/prune_state_archive.py --base ops/state_archive --keep 5` を実行してください。`--dry-run` で削除予定を確認できます。
- **ヘルスチェック:** `scripts/check_state_health.py` を日次（`run_daily_workflow.py --state-health`）で実行し、結果を `ops/health/state_checks.json` に追記する。勝率 LCB・バケット別サンプル・滑り係数を監視し、警告が出た場合は `--webhook` で Slack 等へ通知。`--fail-on-warning` を CI/バッチに組み込むと異常時にジョブを停止できる。
- **履歴保持:** 標準では直近 90 レコードを保持する。上限を変更する場合は `--history-limit` を調整する。履歴の可視化は Notebook or BI で `checked_at` を横軸に `ev_win_lcb` やワーニング件数をプロットする。
- **タスク同期:** `state.md` と `docs/todo_next.md` の整合を保つ際は `scripts/manage_task_cycle.py` を優先利用する。`start-task` で Ready 登録→In Progress 昇格を一括実行し、既存アンカー検知で重複記録を抑止する。完了時は `finish-task` でまとめてログとアーカイブへ送る。いずれも `--dry-run` でコマンド内容を確認してから本実行する。Codex セッションにおける具体的な開始前チェックや終了処理は [docs/codex_workflow.md](codex_workflow.md) を参照する。
- **API鍵管理:** REST インジェストを有効化する場合は `configs/api_keys.yml`（もしくは `configs/api_keys.local.yml`）にプレースホルダを用意し、実際の鍵はローカルで上書きする。CI/cron では `ALPHA_VANTAGE_API_KEY` のような環境変数を設定し、`scripts/_secrets.load_api_credentials` が YAML よりも優先して読み込む。鍵のローテーション履歴は別メモに残し、更新したら `docs/checklists/p1-04_api_ingest.md` のチェックボックスに反映する。
- **テンプレ適用:** `state.md` の `## Next Task` へ手動で項目を追加する場合は、必ず [docs/templates/next_task_entry.md](templates/next_task_entry.md) を貼り付けてアンカー・参照リンク・疑問点スロットを埋める。`scripts/manage_task_cycle.py start-task` を使うとテンプレが自動挿入されるため、手動調整より優先する。
- **DoD チェックリスト:** Ready へ昇格する際は [docs/templates/dod_checklist.md](templates/dod_checklist.md) をコピーし、`docs/checklists/<task-slug>.md` として保存する。テンプレート内の Ready チェック項目は昇格時点で状態を更新し、バックログ固有の DoD 箇条書きをチェックボックスへ転記する。進行中は該当タスクの `docs/todo_next.md` エントリからリンクし、完了後も `docs/checklists/` に履歴として保管する。

## 実装メモ
- `core/runner.py` の `_config_fingerprint` は state と RunnerConfig が一致しているか確認するためのハッシュ。必要に応じて起動時に照合を追加する余地あり。
- state には EV グローバル値・バケット別 EV・滑り学習情報・RV しきい値などが含まれる。
