import os
import unittest
from datetime import datetime, timedelta, timezone

from scripts.run_grid import run_grid


def make_bar(ts, symbol, o, h, l, c, spread):
    return {
        "timestamp": ts.isoformat(),
        "symbol": symbol,
        "tf": "5m",
        "o": o,
        "h": h,
        "l": l,
        "c": c,
        "v": 0.0,
        "spread": spread,
    }


class TestRunGrid(unittest.TestCase):
    def test_grid_minimal(self):
        symbol = "USDJPY"
        t0 = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
        bars = []
        price = 150.00
        for i in range(6):
            bars.append(make_bar(t0 + timedelta(minutes=5*i), symbol, price, price+0.10, price-0.10, price+0.02, 0.02))
            price += 0.01
        or_high = max(b["h"] for b in bars)
        bars.append(make_bar(t0 + timedelta(minutes=5*6), symbol, price, or_high + 0.10, price-0.05, price, 0.02))
        path = os.path.join(os.path.dirname(__file__), "_tmp_grid.csv")
        with open(path, "w") as f:
            f.write("timestamp,symbol,tf,o,h,l,c,v,spread\n")
            for b in bars:
                f.write(",".join([
                    b["timestamp"], symbol, "5m",
                    f"{b['o']}", f"{b['h']}", f"{b['l']}", f"{b['c']}", "0", f"{b['spread']}"
                ]) + "\n")

        try:
            out = run_grid([
                "--csv", path, "--symbol", symbol, "--equity", "100000",
                "--or-n", "6", "--k-tp", "1.0", "--k-sl", "0.8",
                "--out-dir", os.path.join(os.path.dirname(__file__), "runs_grid")
            ])
            self.assertGreaterEqual(out.get("runs", 0), 1)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()

