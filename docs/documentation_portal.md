# Documentation Portal

This portal groups every maintained document into a small set of entry points so new contributors can understand "what to build" and "how we work" without hunting through the repository. Follow the categories below in order.

## Start Here
1. Read the project overview in [../README.md](../README.md) to understand the product goal, strategy assumptions, and how Codex sessions are structured.
2. Walk through the checklist in [codex_quickstart.md](codex_quickstart.md) to align on the session routine.
3. Review the active priorities inside [task_backlog.md](task_backlog.md#p0-12-codex-first-documentation-cleanup) and confirm `state.md` / [todo_next.md](todo_next.md) share the same anchors before making changes.
4. Skim [logic_overview.md](logic_overview.md) and [simulation_plan.md](simulation_plan.md) to understand the execution model and analytical expectations.

> **Tip:** Keep this page open while working. Every relevant runbook, roadmap, or checklist is referenced below with a short description and when to use it.

## Workflow & Coordination
| Document | Purpose | When to use |
| --- | --- | --- |
| [codex_workflow.md](codex_workflow.md) | Full Codex session lifecycle, including how to sync `state.md` / docs with `scripts/manage_task_cycle.py`. | Before starting a session or whenever workflow questions arise. |
| [state_runbook.md](state_runbook.md) | Action checklists for state snapshots, incident replays, and archival hygiene. | During wrap-up or when restoring/replaying states. |
| [todo_next.md](todo_next.md) | Near-term task queue kept in sync with `state.md`. | While updating task status or planning the next block of work. |
| [todo_next_archive.md](todo_next_archive.md) | Historical record of completed tasks and references to past work. | When reviewing precedent or retrieving archived context. |
| [codex_cloud_notes.md](codex_cloud_notes.md) | Sandbox and approval guardrails for remote or restricted environments. | When running in constrained environments or requesting approvals. |

## Development & Architecture
| Document | Purpose | When to use |
| --- | --- | --- |
| [development_roadmap.md](development_roadmap.md) | Immediate, mid-term, and long-term improvements linked to backlog priorities. | Before taking on roadmap-scale work or aligning deliverables. |
| [logic_overview.md](logic_overview.md) | High-level explanation of the trading system, components, and risk constraints. | When orienting new collaborators or validating architectural assumptions. |
| [simulation_plan.md](simulation_plan.md) | Expected analytics, KPIs, and validation flows for simulation work. | Prior to designing experiments or adding new evaluation hooks. |
| [architecture_migration.md](architecture_migration.md) | Pending refactors and migration plans for core systems. | When planning structural refactors or large code migrations. |
| [progress_phase0.md](progress_phase0.md) / [phase1](progress_phase1.md) / [phase2](progress_phase2.md) / [phase3](progress_phase3.md) / [phase4](progress_phase4.md) | Phase-by-phase history and milestones for previous initiatives. | For historical context and to avoid duplicating earlier work. |

## Operations & Runbooks
| Document | Purpose | When to use |
| --- | --- | --- |
| [benchmark_runbook.md](benchmark_runbook.md) | Daily/weekly benchmark pipeline execution and troubleshooting. | Running or reviewing benchmark jobs and alerts. |
| [signal_ops.md](signal_ops.md) | Signal latency monitoring and SLO enforcement procedures. | Responding to latency issues or maintaining signal health. |
| [api_ingest_plan.md](api_ingest_plan.md) | Data ingestion workflow, fallbacks, and monitoring metadata. | When maintaining ingestion pipelines or onboarding new data sources. |
| [observability_dashboard.md](observability_dashboard.md) | Dashboard refresh procedures and expected telemetry exports. | To refresh observability dashboards or audit metrics. |
| [observability_plan.md](observability_plan.md) | Long-term observability roadmap and instrumentation priorities. | Planning monitoring improvements or aligning roadmap items. |
| [audit_playbook.md](audit_playbook.md) | Evidence gathering and compliance-ready audit steps. | During audits or retroactive investigations. |
| [router_architecture.md](router_architecture.md) | Router scoring, telemetry, and governance description. | Modifying router behaviour or interpreting routing outputs. |

## Reference & Templates
| Resource | Purpose | When to use |
| --- | --- | --- |
| [checklists/](checklists) | DoD templates per major initiative (router, manifests, incidents, etc.). | Whenever promoting a task to Ready/In Progress. |
| [templates/](templates) | Reusable DoD and note templates for new tasks. | To bootstrap documentation for fresh tasks. |
| [dependencies.md](dependencies.md) | Runtime and tooling dependencies with optional installs. | Setting up local environments or verifying tooling requirements. |
| [go_nogo_checklist.md](go_nogo_checklist.md) | Release readiness and go/no-go decision criteria. | Before major releases or operational cutovers. |
| [progress_ev_hybrid.md](progress_ev_hybrid.md) | Notes on EV hybridisation experiments and outcomes. | When evaluating EV gating strategies. |
| [broker_oco_matrix.md](broker_oco_matrix.md) | Broker-specific OCO/trailing behaviours. | For broker integration or strategy adjustments. |

## Keeping Documentation in Sync
- Update documentation within the same commit as the code change and mention affected runbooks in the PR description.
- Use `python3 scripts/manage_task_cycle.py --dry-run ...` to preview updates before touching `state.md` or `docs/todo_next.md`.
- When new documents are created, add them to the appropriate table above so the portal stays comprehensive.

By following this portal first, newcomers can immediately locate the correct checklist or runbook, and long-term contributors can keep the knowledge base tidy and traceable.
