"""Logical schema names, one per bounded context (Infrastructure Architecture
§2). Every future model declares its schema explicitly via this module
rather than relying on the connection's default ``search_path`` — this keeps
the logical-schema-per-context boundary visible in code, not just in the
database.
"""

ASSESSMENT = "assessment"
GEOSPATIAL = "geospatial"
DATA_ACQUISITION = "data_acquisition"
ANALYSIS = "analysis"
PREDICTION = "prediction"
VALIDATION = "validation"
REPORTING = "reporting"
NOTIFICATION = "notification"
AUDIT = "audit"
IDENTITY = "identity"

ALL = (
    ASSESSMENT,
    GEOSPATIAL,
    DATA_ACQUISITION,
    ANALYSIS,
    PREDICTION,
    VALIDATION,
    REPORTING,
    NOTIFICATION,
    AUDIT,
    IDENTITY,
)
