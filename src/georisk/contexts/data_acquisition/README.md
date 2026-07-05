# Data Acquisition

**Populated in:** Roadmap Sprint 9 (GEE, weather, sensors, user variables).
**Design reference:** Domain Model §1 (`DatasetSource`, `AcquisitionJob`, `SensorStation`, `SensorReading`, `UserVariable`), Infrastructure Architecture §16/§17/§18 (GEE/weather/sensor integration — anticorruption-layer adapters live in this context's `infrastructure/` layer only).

Empty by design — Sprint 0 provides only the folder and the import-boundary contract that will govern it. The `forbidden` import-linter contract in `pyproject.toml` already ensures `ee` (Earth Engine) and `requests` are only ever imported from `infrastructure/` here, never from another context.
