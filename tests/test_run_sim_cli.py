import json
import os
import tempfile
import unittest

from scripts.run_sim import load_bars_csv, main as run_sim_main


CSV_CONTENT = """timestamp,symbol,tf,o,h,l,c,v,spread
2024-01-01T08:00:00Z,USDJPY,5m,150.00,150.10,149.90,150.02,0,0.02
2024-01-01T08:05:00Z,USDJPY,5m,150.01,150.11,149.91,150.03,0,0.02
2024-01-01T08:10:00Z,USDJPY,5m,150.02,150.12,149.92,150.04,0,0.02
2024-01-01T08:15:00Z,USDJPY,5m,150.03,150.13,149.93,150.05,0,0.02
2024-01-01T08:20:00Z,USDJPY,5m,150.04,150.14,149.94,150.06,0,0.02
2024-01-01T08:25:00Z,USDJPY,5m,150.05,150.15,149.95,150.07,0,0.02
2024-01-01T08:30:00Z,USDJPY,5m,150.06,150.30,149.95,150.10,0,0.02
"""


class TestRunSimCLI(unittest.TestCase):
    def test_load_bars_csv(self):
        path = os.path.join(os.path.dirname(__file__), "_tmp_bars.csv")
        with open(path, "w") as f:
            f.write(CSV_CONTENT)
        try:
            bars = load_bars_csv(path)
            self.assertGreaterEqual(len(bars), 7)
            self.assertEqual(bars[0]["tf"], "5m")
            self.assertEqual(bars[0]["symbol"], "USDJPY")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def test_run_sim_outputs_extended_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "bars.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_CONTENT)
            json_out = os.path.join(tmpdir, "metrics.json")
            args = [
                "--csv", csv_path,
                "--symbol", "USDJPY",
                "--mode", "conservative",
                "--equity", "100000",
                "--json-out", json_out,
                "--dump-max", "0",
                "--no-auto-state",
                "--no-ev-profile",
                "--no-aggregate-ev",
            ]
            rc = run_sim_main(args)
            self.assertEqual(rc, 0)
            with open(json_out, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("sharpe", data)
            self.assertIn("max_drawdown", data)


if __name__ == "__main__":
    unittest.main()

