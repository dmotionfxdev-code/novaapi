"""``IndicatorInputProvider`` — the seam supplying raw indicator inputs for
the "leaf" stages (Hazard, Exposure, Vulnerability, and any hazard type's
non-gating supporting-analysis stages), which have no prior ``StageResult``
to read from. In the full platform these values come from Geospatial
(AOI-derived rasters) and Data Acquisition (sensor readings, user-entered
variables) — neither context exists yet. ``StubIndicatorInputProvider`` is
this sprint's honest placeholder, the identical pattern already used for
Sprint 3's ``ImmediateSuccessStageExecutor`` and Sprint 4's
``StubValidationSubjectResolver``: it proves the calculator wiring and the
downstream (Risk/Resilience reading prior results) data flow are correct,
without pretending this platform has real GIS/sensor ingestion yet.

Sprint 6 added ``hazard_type`` to the signature — an architecture defect
found onboarding WRRAS as a second registrant: ``stage_type`` alone (e.g.
``HAZARD``) can't disambiguate which hazard's raw inputs to return once
more than one strategy registers a stage of the same name. A real
Geospatial/Data-Acquisition-backed provider would need this same parameter
for the same reason (different hazard types read different raster
layers), so this isn't a stub-only concession.
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.analysis.domain.value_objects import HazardType, StageType


class IndicatorInputProvider(Protocol):
    async def provide_raw_inputs(
        self, *, hazard_type: HazardType, stage_type: StageType, assessment_id: str
    ) -> dict: ...


class RiskLayerGenerationPort(Protocol):
    """Sprint C — the seam ``AnalysisStageExecutor`` calls after a
    successful RISK-stage completion to (best-effort) produce a real
    spatial ``RiskLayer``. Implemented by the composition-root
    ``CompositionRootRiskLayerService`` (``api/risk_layer_ports.py``),
    since resolving a genuine Shapefile-sourced geometry dataset requires
    reading Data Acquisition — a peer context ``contexts.analysis`` may
    not import directly. A missing/non-Shapefile geometry source is an
    expected, benign outcome (no layer generated), never surfaced as an
    exception from this port — see that module's own docstring."""

    async def generate_if_possible(
        self,
        *,
        tenant_id: str,
        assessment_id: str,
        hazard_type: str,
        stage_result_id: str,
        issued_by: str,
    ) -> None: ...


class StubIndicatorInputProvider:
    """Fixed, physically-plausible dummy values per hazard type's leaf
    stage — not a single "always perfect" dataset, so the ported formulas'
    actual weighting/combination logic is genuinely exercised end-to-end.
    """

    async def provide_raw_inputs(
        self, *, hazard_type: HazardType, stage_type: StageType, assessment_id: str
    ) -> dict:
        if hazard_type is HazardType.FLOOD:
            return self._firas_inputs(stage_type)
        if hazard_type is HazardType.WILDFIRE:
            return self._wrras_inputs(stage_type)
        raise ValueError(
            f"StubIndicatorInputProvider has no stub inputs for hazard type {hazard_type}"
        )

    def _firas_inputs(self, stage_type: StageType) -> dict:
        if stage_type is StageType.HAZARD:
            return {
                "rainfall_index": 0.65,
                "water_level_index": 0.55,
                "slope_index": 0.40,
                "drainage_index": 0.50,
                "land_use_index": 0.60,
                "soil_index": 0.70,
            }
        if stage_type is StageType.EXPOSURE:
            return {
                "asset_data": {
                    "population": {"total": 10000, "exposed": 4000},
                    "houses": {"total": 2000, "exposed": 900},
                    "roads": {"total": 150, "exposed": 60},
                    "schools": {"total": 20, "exposed": 8},
                    "hospitals": {"total": 5, "exposed": 2},
                    "power_infrastructure": {"total": 30, "exposed": 10},
                    "agricultural_land": {"total": 500, "exposed": 200},
                    "livestock": {"total": 3000, "exposed": 1200},
                }
            }
        if stage_type is StageType.VULNERABILITY:
            # Sprint 5.2: flat — the 12 approved vulnerability indicators
            # plus the 16 insecurity indicators, all at the top level (no
            # social/physical/economic/insecurity grouping). This is the
            # exact shape ``FIRASVulnerabilityCalculator`` now expects, and
            # the exact shape a persisted ``StageResult``'s snapshot uses,
            # so historical lookups round-trip without translation.
            return {
                "population_density": 0.60,
                "elderly_population": 0.30,
                "children_population": 0.35,
                "disability_status": 0.20,
                "education_level": 0.50,
                "poverty_level": 0.40,
                "housing_quality": 0.40,
                "building_materials": 0.50,
                "infrastructure_condition": 0.45,
                "household_income": 0.30,
                "livelihood_dependence": 0.55,
                "crop_dependence": 0.60,
                "emergency_plans": 0.50,
                "community_training": 0.40,
                "evacuation_preparedness": 0.45,
                "resource_availability": 0.50,
                "warning_timeliness": 0.60,
                "warning_accuracy": 0.55,
                "warning_accessibility": 0.50,
                "flood_awareness": 0.65,
                "previous_experience": 0.70,
                "understanding_of_risk": 0.60,
                "response_speed": 0.50,
                "relief_distribution": 0.45,
                "coordination": 0.55,
                "economic_recovery": 0.40,
                "infrastructure_recovery": 0.45,
                "social_recovery": 0.50,
            }
        raise ValueError(f"StubIndicatorInputProvider has no stub inputs for stage {stage_type}")

    def _wrras_inputs(self, stage_type: StageType) -> dict:
        if stage_type is StageType.HAZARD:
            return {
                "temperature": 0.70,
                "wind_speed": 0.55,
                "drought_index": 0.60,
                "fuel_load": 0.65,
                "vegetation_density": 0.60,
                "slope": 0.40,
                "human_activity": 0.35,
                "rainfall": 0.30,
            }
        if stage_type is StageType.EXPOSURE:
            return {
                "population_exposed": 3500,
                "population_total": 10000,
                "infrastructure_exposed": 800,
                "infrastructure_total": 2000,
                "environmental_exposed": 150,
                "environmental_total": 500,
                "economic_exposed": 400,
                "economic_total": 1000,
            }
        if stage_type is StageType.VULNERABILITY:
            # Flat — the 14 approved vulnerability indicators plus the 16
            # insecurity indicators, matching FIRAS's Sprint 5.2 flat-shape
            # precedent (no social/physical/environmental/economic
            # grouping in the gathered/persisted inputs dict).
            return {
                "poverty_rate": 0.45,
                "literacy_level": 0.65,
                "age_dependency_ratio": 0.40,
                "disability_ratio": 0.15,
                "building_flammability": 0.55,
                "roof_material_index": 0.50,
                "building_density": 0.45,
                "access_road_quality": 0.60,
                "fuel_accumulation_index": 0.60,
                "ecosystem_sensitivity": 0.50,
                "forest_condition": 0.55,
                "tourism_dependence": 0.35,
                "forest_livelihood_dependence": 0.50,
                "agricultural_dependence": 0.45,
                "firebreak_coverage": 0.45,
                "community_training": 0.40,
                "fire_committee_presence": 0.35,
                "equipment_availability": 0.40,
                "warning_timeliness": 0.55,
                "warning_accessibility": 0.50,
                "warning_accuracy": 0.55,
                "fire_awareness": 0.60,
                "fire_prevention_knowledge": 0.50,
                "evacuation_knowledge": 0.45,
                "response_time_index": 0.50,
                "suppression_efficiency": 0.45,
                "resource_adequacy": 0.40,
                "forest_restoration": 0.40,
                "economic_recovery": 0.35,
                "community_recovery": 0.45,
            }
        if stage_type is StageType.FIRE_REGIME:
            return {
                "observation_years": 10.0,
                "fire_count": 15,
                "area_km2": 250.0,
                "repeated_burned_pixels": 800,
                "total_burned_pixels": 2000,
                "burned_area_ha": 1500.0,
                "first_fire_date": "2015-06-01",
                "last_fire_date": "2025-09-15",
                "high_severity_fires": 4,
                "temperature": 0.70,
                "wind_speed": 0.55,
                "relative_humidity": 0.40,
                "fuel_load": 0.65,
                "drought_index": 0.60,
                "human_activity": 0.35,
            }
        if stage_type is StageType.BURN_OCCURRENCE_PROBABILITY:
            return {
                "temperature": 0.70,
                "wind_speed": 0.55,
                "relative_humidity": 0.40,
                "fuel_load": 0.65,
                "drought_index": 0.60,
                "human_activity": 0.35,
                "historical_fire_index": 0.50,
            }
        if stage_type is StageType.BURN_SEVERITY:
            return {
                "nir_pre": 0.45,
                "swir_pre": 0.20,
                "nir_post": 0.25,
                "swir_post": 0.30,
                "red_pre": 0.08,
                "red_post": 0.18,
            }
        raise ValueError(f"StubIndicatorInputProvider has no stub inputs for stage {stage_type}")
