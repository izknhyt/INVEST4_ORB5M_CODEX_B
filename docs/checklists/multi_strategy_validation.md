# マルチ戦略比較チェックリスト

Day ORB (`configs/strategies/day_orb_5m.yaml`) と Mean Reversion (`configs/strategies/mean_reversion.yaml`) を同一 CSV で比較し、EV ゲートや RV バンドの影響を検証するための手順をまとめる。2026-04-05 以降は `run_sim.py --manifest ...` に統一されているため、以下のコマンド例も manifest-first 想定で記載する。

## 前提条件
- 入力 CSV に Day ORB で利用しているカラム（`timestamp, symbol, tf, o, h, l, c, v, spread`）が揃っていること。
- Mean Reversion が参照する `zscore`（および必要なら `rv_band`）が feature パイプラインで供給されること。
- `python3 scripts/run_sim.py` を実行でき、`runs/` 以下に成果物を書き込める環境であること。
- manifest の `runner.cli_args` で `auto_state` / `aggregate_ev` / `use_ev_profile` が期待する値になっていること。EV プロファイル無効化の比較を行う場合は manifest をコピーして `use_ev_profile: false` を設定する。

## 手順
1. **共通ディレクトリの作成**
   ```bash
   mkdir -p runs/multi_strategy
   ```

2. **Day ORB のベースライン実行**
   ```bash
   python3 scripts/run_sim.py \
     --manifest configs/strategies/day_orb_5m.yaml \
     --csv data/sample_orb.csv \
     --json-out runs/multi_strategy/day_orb.json \
     --out-dir runs/multi_strategy
   ```
   - `day_orb.json` の `run_dir` フィールドに成果物フォルダ（例: `runs/multi_strategy/USDJPY_conservative_20260405_123000`）が記録される。
   - フォルダ内には `params.json` / `metrics.json` / `state.json`（auto_state=true の場合）が保存され、トレードが存在すれば `records.csv`、日次集計があれば `daily.csv` が生成される。

3. **Mean Reversion の実行**
   ```bash
   python3 scripts/run_sim.py \
     --manifest configs/strategies/mean_reversion.yaml \
     --csv data/sample_orb.csv \
     --json-out runs/multi_strategy/reversion.json \
     --out-dir runs/multi_strategy
   ```
   - `reversion.json` にも `run_dir` が出力されるので、Day ORB と同様に `metrics.json`・`records.csv`・`daily.csv` を取得する。

4. **EV プロファイル適用有無の比較**
   - プロファイル無効化用に `configs/strategies/mean_reversion_no_ev.yaml` を用意済み。既定 manifest と `run_dir` を比較し、EV シード有無の差分を確認する。
   - 実行例:
     ```bash
     python3 scripts/run_sim.py \
       --manifest configs/strategies/mean_reversion_no_ev.yaml \
       --csv data/sample_orb.csv \
       --json-out runs/multi_strategy/reversion_no_profile.json \
       --out-dir runs/multi_strategy
     ```
   - `reversion_no_profile.json` と既存結果を比較し、`debug.ev_reject` や `daily.csv` の差異を確認する。

5. **ゲート/EV 指標の比較**
   ```bash
   python3 - <<'PY'
import csv, json
from pathlib import Path

base = Path('runs/multi_strategy')

def load_run_json(name: str):
    with open(base / f"{name}.json", 'r', encoding='utf-8') as f:
        return json.load(f)

day = load_run_json('day_orb')
rev = load_run_json('reversion')

print('Day ORB trades:', day.get('trades'), 'EV rejects:', day.get('debug', {}).get('ev_reject', 'n/a'))
print('Reversion trades:', rev.get('trades'), 'EV rejects:', rev.get('debug', {}).get('ev_reject', 'n/a'))

for name in ('day_orb', 'reversion'):
    run_dir = Path(load_run_json(name)['run_dir'])
    daily_path = run_dir / 'daily.csv'
    if not daily_path.exists():
        print(name, 'daily.csv missing')
        continue
    rows = list(csv.DictReader(open(daily_path, encoding='utf-8')))
    gate_pass = sum(float(r.get('gate_pass', 0)) for r in rows)
    ev_reject = sum(float(r.get('ev_reject', 0)) for r in rows)
    print(name, 'gate_pass', gate_pass, 'ev_reject', ev_reject)
PY
   ```
   - `records.csv` を開き、RV バンドやシグナル方向の対応を spot チェックする。

6. **結果サマリの共有**
   - 差分（ゲート通過数、EV リジェクト数、期待値ギャップなど）を箇条書きにまとめ、`docs/todo_next.md` もしくはレポートへ記録する。
   - EV プロファイル有無で挙動が変わる場合は、`configs/ev_profiles/` の更新計画を backlog へ登録する。

## 評価指標テンプレート
| 指標 | Day ORB | Mean Reversion | メモ |
| --- | --- | --- | --- |
| Trades | — | — | `metrics.json` の `trades` |
| Gate Pass / Gate Block | — | — | `run_dir/daily.csv` 集計 |
| EV Pass / EV Reject | — | — | `run_dir/daily.csv` の `ev_pass` / `ev_reject` |
| Wins / Win Rate | — | — | `metrics.json` の `wins`・`win_rate` |
| Total PnL (pips) | — | — | `metrics.json` の `total_pips` |
| Debug Counters | — | — | `metrics.json` の `debug` セクション |

（`—` の箇所には実測値を入力し、比較コメントをまとめる。）

## チェックリスト
- [ ] Day ORB / Mean Reversion の manifest を用いたコマンドが成功し、各 `run_dir` に `metrics.json` と必要な CSV が生成された。
- [ ] Mean Reversion manifest の EV プロファイル適用有無（`use_ev_profile`）を切り替え、差分を取得した。
- [ ] `metrics.json` と `daily.csv` を比較し、ゲート通過数 (`gate_pass`/`gate_block`) と EV リジェクト (`ev_reject`) の差異を説明できる。
- [ ] 主要指標（Trades, Win Rate, Total PnL, Gate/Ev カウント）を表に転記し、レビュー用ドキュメントへ共有した。

## 実測サマリ（テンプレ）
- Day ORB: `trades=...`, `gate_block=...`, `ev_reject=...`。主なブロック理由: ...
- Mean Reversion: `trades=...`, `gate_block=...`, `ev_reject=...`。`use_ev_profile` 無効時との差分: ...
- 重要な気付き・次のアクション: ...
