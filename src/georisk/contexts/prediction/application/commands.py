"""Commands for the Prediction context. Plain dataclasses — no behavior,
just the data a handler needs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunPredictionCommand:
    tenant_id: str
    assessment_id: str
    variable_selection_id: str
    sampling_campaign_id: str
    method: str
    issued_by: str
