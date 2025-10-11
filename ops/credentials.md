# Observability Credentials Reference

## Webhook Secrets
| Secret | Description | Storage | Rotation Owner | Rotation Cadence | Notes |
| --- | --- | --- | --- | --- | --- |
| `OBS_WEEKLY_WEBHOOK_URL` | Webhook endpoint for weekly observability payload delivery. | Scheduler secret store (`invest3/observability/weeklies/url`). | Trading Ops (primary), Research Ops (secondary). | Quarterly or on destination change. | Injected at runtime; never committed. Smoke test with dry-run URL before rotation. |
| `OBS_WEBHOOK_SECRET` | HMAC signing secret for weekly payload webhook. | Scheduler secret store (`invest3/observability/weeklies/secret`). | Trading Ops (primary), Research Ops (secondary). | Rotate quarterly; keep previous secret active for 7 days overlap. | Update receiving service allow-list, refresh `ops/weekly_report_history/*.sig` after rotation. |

## Rotation Procedure
1. Export current secret metadata (owner, expiry) into the scheduler secret store audit trail.
2. Generate new secret and update the store entries, retaining the previous secret until post-rotation verification completes.
3. Run the following smoke test from the repository root with staging endpoints:
   ```bash
   PYTHONPATH=. OBS_WEEKLY_WEBHOOK_URL=https://hooks-staging.example.com/observability \
   OBS_WEBHOOK_SECRET=new-secret-value \
   python3 scripts/run_daily_workflow.py \
       --observability \
       --dry-run \
       --observability-config configs/observability/automation.yaml
   ```
4. Confirm `ops/automation_runs.log` records `status: "dry_run"` for weekly job, validate signatures via `python3 scripts/verify_observability_job.py --check-secrets --check-log ops/automation_runs.log`.
5. Promote the new secret to production endpoints, then revoke the previous secret after verifying two consecutive cron runs.

## Incident & Escalation
- Immediate contact: Trading Ops oncall (`@trading-ops-oncall`).
- Secondary: Research Ops automation maintainer (`@research-ops`).
- Log issues in `ops/automation_runs.log` and attach failing job IDs to the incident tracker under `ops/incidents/`.
