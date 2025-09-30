from datetime import datetime
import sys, pandas as pd
import dukascopy_python
from dukascopy_python.instruments import INSTRUMENT_FX_MAJORS_USD_JPY

# 使い方: python3 fetch_month.py 2025 01  (← 年 月)
year = int(sys.argv[1]); month = int(sys.argv[2])
start = datetime(year, month, 1)
# 月末は雑に翌月1日の直前でOK（12月の翌月＝翌年1月）
if month == 12:
    end = datetime(year+1, 1, 1)
else:
    end = datetime(year, month+1, 1)

it = dukascopy_python.live_fetch(
    INSTRUMENT_FX_MAJORS_USD_JPY,
    5,  # 5分
    dukascopy_python.TIME_UNIT_MIN,
    dukascopy_python.OFFER_SIDE_BID,
    start,
    end,
)

df_last = None
for df in it:
    df_last = df

if df_last is None:
    print(f"[warn] no data for {year}-{month:02d}")
    sys.exit(0)

df_last.sort_index().to_csv(f"USDJPY_{year}{month:02d}_5min.csv")
print(f"[done] USDJPY_{year}{month:02d}_5min.csv rows={len(df_last)}")
