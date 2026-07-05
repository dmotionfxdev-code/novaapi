"""Composition-root glue for Data Acquisition's Sprint 14 read into
Geospatial's ``AreaOfInterest`` (requirement #5, AOI-based Processing) —
Data Acquisition's first cross-context read; Sprint 7/13 never needed
one. Lives here, under ``api/``, for the identical peer-independence
reason as every prior composition root (``api/reporting_ports.py``,
``api/notification_ports.py``, etc.): the import-linter's peer-
independence contract forbids ``contexts.data_acquisition`` from
importing ``contexts.geospatial`` directly.
"""

from __future__ import annotations

from georisk.contexts.data_acquisition.application.ports import AoiGeometryInfo
from georisk.contexts.geospatial.domain.value_objects import AoiId
from georisk.contexts.geospatial.infrastructure.repositories import (
    SqlAlchemyAreaOfInterestRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.session import Database


class CompositionRootAoiReader:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_aoi_geometry(
        self, *, tenant_id: TenantId, aoi_id: str
    ) -> AoiGeometryInfo | None:
        async with self._db.session() as session:
            repo = SqlAlchemyAreaOfInterestRepository(session)
            aoi = await repo.get_by_id(AoiId.from_string(aoi_id))
            if aoi is None or str(aoi.tenant_id) != str(tenant_id):
                return None
            return AoiGeometryInfo(aoi_id=str(aoi.id), geometry=aoi.geometry.geojson)
