# 2025-11-13 Dukascopy Ingest Attempt

## Summary
- Objective: Retry USDJPY conservative ingest via Dukascopy with sandbox dependencies installed.
- Outcome: `pip install dukascopy-python yfinance` blocked by proxy (HTTP 403). Workflow fell back to local CSV synthetic path; benchmark freshness remains stale.

## Command Log
```
pip install dukascopy-python yfinance
WARNING: Retrying (Retry(total=4, connect=None, read=None, redirect=None, status=None)) after connection broken by 'ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 403 Forbidden'))': /simple/dukascopy-python/
WARNING: Retrying (Retry(total=3, connect=None, read=None, redirect=None, status=None)) after connection broken by 'ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 403 Forbidden'))': /simple/dukascopy-python/
WARNING: Retrying (Retry(total=2, connect=None, read=None, redirect=None, status=None)) after connection broken by 'ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 403 Forbidden'))': /simple/dukascopy-python/
WARNING: Retrying (Retry(total=1, connect=None, read=None, redirect=None, status=None)) after connection broken by 'ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 403 Forbidden'))': /simple/dukascopy-python/
WARNING: Retrying (Retry(total=0, connect=None, read=None, redirect=None, status=None)) after connection broken by 'ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 403 Forbidden'))': /simple/dukascopy-python/
ERROR: Could not find a version that satisfies the requirement dukascopy-python (from versions: none)
ERROR: No matching distribution found for dukascopy-python
```

```
python3 scripts/run_daily_workflow.py --ingest --use-dukascopy --symbol USDJPY --mode conservative
[wf] fetching Dukascopy bars USDJPY 5m 2025-10-02T00:15:00 2025-10-02T03:54:11
[wf] Dukascopy unavailable, switching to yfinance fallback: fetch error: dukascopy_python is required for Dukascopy ingestion.
[wf] fetching yfinance bars JPY=X (fallback for USDJPY) 5m 2025-10-02T02:15:00 2025-10-02T03:54:11
[wf] local CSV fallback triggered: yfinance fallback failed: yfinance is required for yfinance ingestion
[wf] local_csv_ingest (local_csv:usdjpy_5m_2018-2024_utc.csv) rows=0 last_ts=2025-10-02T03:15:00
```

```
python3 scripts/check_benchmark_freshness.py --target USDJPY:conservative --max-age-hours 6
benchmarks.USDJPY_conservative stale by 24.82h (limit 6.0h)
benchmark_pipeline.USDJPY_conservative.latest_ts stale by 24.82h (limit 6.0h)
benchmark_pipeline.USDJPY_conservative.summary_generated_at stale by 15.53h (limit 6.0h)
```

## Observations
- Sandbox proxy still blocks PyPI; need ops to whitelist or provide wheel drop for `dukascopy-python` and `yfinance`.
- Workflow relies on synthetic/local CSV fallback; ingest snapshot unchanged at `2025-10-02T03:15:00`.
- Benchmark freshness remains outside 6h SLA (latest 24.82h, summary 15.53h).

## Next Steps
1. Escalate proxy/wheel provisioning to ops; attach this log as evidence.
2. Once dependencies available, rerun ingest + freshness check to confirm Dukascopy/yfinance path.
3. Plan to update validated snapshots after successful real-data ingest.

