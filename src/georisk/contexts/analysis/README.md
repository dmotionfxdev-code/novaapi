# Analysis Engine

**Populated in:** Roadmap Sprint 4 (Hazard Strategy Engine + FIRAS), Sprint 5 (execution pipeline + WRRAS).
**Design reference:** Domain Model §1 (`StageResult`), Platform Architecture §6 (`HazardStrategy`/`StageCalculator`/`StrategyRegistry`).

`strategies/` is where per-hazard-type calculator packages (`strategies/firas/`, `strategies/wrras/`, ...) land — one package per hazard type, each implementing the same `HazardStrategy` interface. No strategy package exists yet.

Empty by design — Sprint 0 provides only the folder and the import-boundary contract that will govern it.
