# Architecture Migration Plan

This document will capture the strategy for migrating performance-critical I/O and execution paths to Rust or C++.

## Scope
- Define current Python-based system boundaries and identify FFI seams for candidate modules.
- Track profiling data that motivates each migration phase.
- Outline testing and rollout safeguards to preserve behaviour.

## Current Status
- **Owner**: _Unassigned_
- **Last Reviewed**: _TODO_
- Existing ADR references and profiling measurements still need to be collated.

## Open Questions
- Which runner components should move first without disrupting CLI workflows?
- How will deployment packaging change once native extensions are introduced?
- What telemetry must remain available during and after the migration?

## Next Steps
- [ ] Compile baseline architecture diagrams and call graphs.
- [ ] Gather recent profiling snapshots that justify native rewrites.
- [ ] Propose phased milestones with validation criteria and fallback plans.
- [ ] Coordinate with docs/task_backlog.md owners to add dedicated tasks.

> **TODO**: Flesh out each section with concrete plans, ADR links, and decision history.
