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

## 推奨運用
- **バックアップ:** 自動アーカイブされた最新ファイル（例: `ops/state_archive/.../<timestamp>_runid.json`）を基準に、必要に応じて別途バックアップを取得する。
- **互換性:** RunnerConfig（特にゲート設定・戦略パラメータ）を大幅に変更した際は、古い state がバイアスになる場合がある。必要に応じてリセット（初期化）を検討する。
- **監査ログ:** `ops/state_archive/` など保存先を決め、保存日時・使った戦略パラメータと一緒にメタ情報を付与する。
- **EVプロファイル:** `scripts/aggregate_ev.py --strategy ... --symbol ... --mode ...` を使うと、アーカイブ済み state から長期/直近期の期待値統計を集約し、`configs/ev_profiles/` に YAML プロファイルを生成できます。`run_sim.py` は該当プロファイルを自動ロードして EV バケットをシードします（`--no-ev-profile` で無効化可能）。
- **ヘルスチェック:** `scripts/check_state_health.py` を日次（`run_daily_workflow.py --state-health`）で実行し、結果を `ops/health/state_checks.json` に追記する。勝率 LCB・バケット別サンプル・滑り係数を監視し、警告が出た場合は `--webhook` で Slack 等へ通知。`--fail-on-warning` を CI/バッチに組み込むと異常時にジョブを停止できる。
- **履歴保持:** 標準では直近 90 レコードを保持する。上限を変更する場合は `--history-limit` を調整する。履歴の可視化は Notebook or BI で `checked_at` を横軸に `ev_win_lcb` やワーニング件数をプロットする。
- **タスク同期:** `state.md` と `docs/todo_next.md` の整合を保つ際は `scripts/manage_task_cycle.py` を優先利用する。`start-task` で Ready 登録→In Progress 昇格を一括実行し、既存アンカー検知で重複記録を抑止する。完了時は `finish-task` でまとめてログとアーカイブへ送る。いずれも `--dry-run` でコマンド内容を確認してから本実行する。
- **DoD チェックリスト:** Ready へ昇格する際は [docs/templates/dod_checklist.md](templates/dod_checklist.md) をコピーし、`docs/checklists/<task-slug>.md` として保存する。テンプレート内の Ready チェック項目は昇格時点で状態を更新し、バックログ固有の DoD 箇条書きをチェックボックスへ転記する。進行中は該当タスクの `docs/todo_next.md` エントリからリンクし、完了後も `docs/checklists/` に履歴として保管する。

## 実装メモ
- `core/runner.py` の `_config_fingerprint` は state と RunnerConfig が一致しているか確認するためのハッシュ。必要に応じて起動時に照合を追加する余地あり。
- state には EV グローバル値・バケット別 EV・滑り学習情報・RV しきい値などが含まれる。
