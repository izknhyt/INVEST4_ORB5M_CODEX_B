# マルチ戦略比較チェックリスト

Day ORB と Mean Reversion (reversion_stub) を同一 CSV で比較し、EV ゲートや RV バンドの影響を検証するための手順をまとめる。CLI での実行・出力確認・評価観点を順番に消化し、チームへ結果を共有する。

## 前提条件
- 入力 CSV に Day ORB で利用しているカラム（timestamp, symbol, tf, o, h, l, c, v, spread）が揃っていること。
- `features/` もしくは事前処理で Mean Reversion が参照する `zscore` フィールドと、`core.runner` が生成する `rv_band` ラベルが供給されること。
- `python3 scripts/run_sim.py` が実行できるローカル環境であり、`runs/` 以下への書き込み権限があること。
- 既存の Day ORB EV プロファイル（例: `configs/ev_profiles/day_orb_5m.yaml`）が利用可能で、必要に応じて `--no-ev-profile` で無効化できること。

## 手順
1. **共通出力ディレクトリの作成**
   ```bash
   mkdir -p runs/multi_strategy && rm -f runs/multi_strategy/day_orb.json runs/multi_strategy/reversion.json
   ```

2. **Day ORB のベースライン実行**
   ```bash
   python3 scripts/run_sim.py --csv data/sample_orb.csv --symbol USDJPY \
       --mode conservative --equity 100000 --json-out runs/multi_strategy/day_orb.json \
       --dump-csv runs/multi_strategy/day_orb_records.csv --dump-daily runs/multi_strategy/day_orb_daily.csv \
       --out-dir runs/multi_strategy --debug
   ```
   - 期待出力: `runs/multi_strategy/day_orb.json` に `trades`・`fills`・`debug` カウント、`dump_csv`/`dump_daily` パスが含まれる。
   - チェック: `dump-csv` と `dump-daily` で指定したファイルが作成され、`gate_pass`/`ev_reject` など日次カラムが出力されていること。

3. **Mean Reversion (reversion_stub) の実行**
   ```bash
   python3 scripts/run_sim.py --csv data/sample_orb.csv --symbol USDJPY \
       --mode conservative --equity 100000 --strategy reversion_stub.MeanReversionStrategy \
       --json-out runs/multi_strategy/reversion.json \
       --dump-csv runs/multi_strategy/reversion_records.csv --dump-daily runs/multi_strategy/reversion_daily.csv \
       --out-dir runs/multi_strategy --debug
   ```
   - 期待出力: JSON に `ev_profile_path` が記録され、Day ORB と同じディレクトリ配下にランフォルダが生成される。
   - チェック: `reversion_records.csv` の `zscore` カラムが埋まっていること、`reversion_daily.csv` で `gate_block` が RV ハイで増えていないかを確認。

4. **EV プロファイル適用有無の確認**
   - **適用あり**: 上記コマンドの JSON に `ev_profile_path` が含まれているか、`runs/multi_strategy/*/metrics.json` で確認する。
   - **適用なし比較**:
     ```bash
     python3 scripts/run_sim.py --csv data/sample_orb.csv --symbol USDJPY \
         --mode conservative --equity 100000 --strategy reversion_stub.MeanReversionStrategy \
         --json-out runs/multi_strategy/reversion_no_profile.json --no-ev-profile --debug
     ```
     出力 JSON に `ev_profile_path` が無いこと、`debug` の `ev_reject` が増減していないかを比較する。

5. **ゲート/EV 指標の比較**
   ```bash
   python3 - <<'PY'
import csv, json
from pathlib import Path
base = Path('runs/multi_strategy')
with open(base/'day_orb.json') as f:
    day = json.load(f)
with open(base/'reversion.json') as f:
    rev = json.load(f)
print('Day ORB trades:', day.get('trades'), 'EV rejects:', day.get('debug', {}).get('ev_reject', 'n/a'))
print('Reversion trades:', rev.get('trades'), 'EV rejects:', rev.get('debug', {}).get('ev_reject', 'n/a'))
for name in ['day_orb_daily.csv', 'reversion_daily.csv']:
    rows = list(csv.DictReader(open(base/name)))
    gate_pass = sum(float(r.get('gate_pass', 0)) for r in rows)
    ev_reject = sum(float(r.get('ev_reject', 0)) for r in rows)
    print(name, 'gate_pass', gate_pass, 'ev_reject', ev_reject)
PY
   ```
   - 比較観点: `gate_pass`/`gate_block`/`ev_reject` の総数、`debug` セクションの `rv_high_block` や `ev_reject_lcb` などの差分。
   - 補足: `--dump-csv` により取得した詳細レコードで、RV バンドとシグナル方向の対応を spot チェックする。

6. **結果サマリの共有**
   - 差分（ゲート通過数、EV リジェクト数、期待値ギャップなど）を箇条書きにまとめ、`docs/todo_next.md` もしくはレポートに貼り付ける。
   - EV プロファイル適用の有無で挙動が変化した場合は、`configs/ev_profiles/` の更新計画を backlog へ登録する。

## 評価指標テンプレート
| 指標 | Day ORB | Mean Reversion | メモ |
| --- | --- | --- | --- |
| Trades |  |  | 主要エントリー数の差異 |
| Gate Pass / Gate Block |  |  | RV バンドでの抑制状況 |
| EV Pass / EV Reject |  |  | LCB 閾値でのフィルタリング |
| Wins / Win Rate |  |  | `metrics.json` の `wins`・`win_rate` を利用 |
| Total PnL (pips) |  |  | `metrics.json` の `total_pips` |
| Debug Counters |  |  | `debug` セクションの `ev_reject_*` など |

## チェックリスト
- [ ] Day ORB / Mean Reversion それぞれで `--dump-csv` / `--dump-daily` の出力が生成され、列構成が期待どおりか確認した。
- [ ] `--strategy reversion_stub.MeanReversionStrategy` 指定で Day ORB のコマンドラインを流用できることを確認した。
- [ ] `ev_profile_path` の有無を確認し、`--no-ev-profile` 実行結果との差分を記録した。
- [ ] `debug` と `daily.csv` のゲート通過数 (`gate_pass`/`gate_block`) と EV リジェクト数 (`ev_reject`) を比較し、差異を説明できる。
- [ ] 主要指標（Trades, Win Rate, Total PnL, Gate/Ev カウント）を表に転記し、レビュー用ドキュメントへ共有した。
