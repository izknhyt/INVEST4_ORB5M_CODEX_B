# Architecture Migration Plan

This document will capture the strategy for migrating performance-critical I/O and execution paths to Rust or C++.

## Scope
- Define current Python-based system boundaries and identify FFI seams for candidate modules.
- Track profiling data that motivates each migration phase.
- Outline testing and rollout safeguards to preserve behaviour.
- Capture the ADR decisions that govern native integrations.

## Current Status
- **Owner**: _Unassigned_
- **Last Reviewed**: 2026-05-04 (Codex session)
- Existing ADR references and profiling measurements still need to be collated.
- Candidate ADRs: ADR-017 (runner refactor), ADR-020 (Artifacts Ledger), ADR-024 (FFI sandbox policy).

## Roadmap Alignment
- Long-term initiative tracked in [docs/development_roadmap.md](development_roadmap.md).
- Related backlog anchor: [docs/task_backlog.md#継続タスク--保守](task_backlog.md#継続タスク--保守).
- Success criteria include an agreed FFI boundary, migration playbooks, and regression coverage plans.

## Milestones
1. **Profiling & Candidate Selection** — Aggregate CPU/latency hotspots, decide migration priority, and document acceptance thresholds.
2. **FFI Boundary Design** — Define module interfaces, memory ownership rules, and safety contracts.
3. **Prototype & Benchmark** — Build a native prototype, compare performance, and record operational caveats.
4. **Rollout Plan** — Establish phased deployment steps, rollback levers, and documentation updates.

Each milestone should document scope, owners, risks, and required updates to tooling or documentation.

## Open Questions
- Which runner components should move first without disrupting CLI workflows?
- How will deployment packaging change once native extensions are introduced?
- What telemetry must remain available during and after the migration?

## Next Steps
- [ ] Compile baseline architecture diagrams and call graphs.
- [ ] Gather recent profiling snapshots that justify native rewrites.
- [ ] Propose phased milestones with validation criteria and fallback plans.
- [ ] Coordinate with docs/task_backlog.md owners to add dedicated tasks.
- [ ] Produce FFI risk assessment covering safety, packaging, and deployment constraints.

> **TODO**: Flesh out each section with concrete plans, ADR links, and decision history.
