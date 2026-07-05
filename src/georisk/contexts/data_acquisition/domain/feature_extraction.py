"""Sprint 14 requirement #4 — the Feature Extraction Pipeline. Pure
Python band-math over AOI-aggregate band statistics (a ``{gee_band_name:
mean_value}`` dict — what Earth Engine's own ``reduceRegion(ee.Reducer.
mean())`` already returns), never per-pixel raster arrays: this platform
has no GDAL/rasterio dependency (a deliberate, longstanding choice, same
as Geospatial's Sprint 7 pure-Python geometry math), and GEE doing the
per-pixel reduction server-side is exactly the point of using it. Values
arriving in ``band_statistics`` are assumed already radiometrically
corrected (scaled to physical reflectance/temperature units) by
``infrastructure/gee_connector.py``'s preprocessing step — these formulas
never apply a DN scale factor themselves.

Two documented simplifications (named, not hidden, matching this
project's established discipline — e.g. Sprint 8's ``MAX_KENDALL_
OBSERVATIONS`` cap):

1. LST is only ever computed for sources with a real thermal band
   (Landsat's ``ST_B10`` in this supported set) — Sentinel-1/2, MODIS
   (surface-reflectance product used here has no thermal band), CHIRPS,
   and ERA5 do not carry a comparable satellite thermal-emission band, so
   LST is honestly skipped for them rather than approximated from an
   unrelated quantity (e.g. ERA5's 2m air temperature is a REANALYSIS
   near-surface air temperature, a physically different quantity from
   satellite-observed land *surface* temperature).
2. SPEI here is a genuine, real Thornthwaite-family water-balance
   computation (precipitation minus a Thornthwaite potential-
   evapotranspiration estimate), but it is NOT a properly standardized
   SPEI in the strict climatological sense — true SPEI standardizes the
   water-balance series against a log-logistic distribution fit to a
   multi-decade historical climatology, which this platform does not
   store anywhere. ``compute_spei`` computes the real water-balance
   quantity SPEI is built from and applies a simple z-score-style
   standardization around zero (a balanced climate has D≈0), not a
   fitted distribution — a reasonable, honestly-labeled approximation
   given the data this platform actually has, not a fabricated "real"
   SPEI value.
"""

from __future__ import annotations

import math

from georisk.contexts.data_acquisition.domain.value_objects import (
    RemoteSensingSource,
    SpectralIndex,
)

#: Logical band name -> this source's real Earth Engine band name.
#: Sentinel-1 is SAR-only (VV/VH backscatter) and intentionally maps to
#: no logical optical/thermal band — none of this sprint's indices apply.
BAND_NAMES_BY_SOURCE: dict[RemoteSensingSource, dict[str, str]] = {
    RemoteSensingSource.SENTINEL_1: {},
    RemoteSensingSource.SENTINEL_2: {
        "BLUE": "B2",
        "GREEN": "B3",
        "RED": "B4",
        "NIR": "B8",
        "SWIR1": "B11",
        "SWIR2": "B12",
    },
    RemoteSensingSource.LANDSAT: {
        "BLUE": "SR_B2",
        "GREEN": "SR_B3",
        "RED": "SR_B4",
        "NIR": "SR_B5",
        "SWIR1": "SR_B6",
        "SWIR2": "SR_B7",
        "THERMAL": "ST_B10",
    },
    RemoteSensingSource.MODIS: {
        "RED": "sur_refl_b01",
        "NIR": "sur_refl_b02",
        "BLUE": "sur_refl_b03",
        "GREEN": "sur_refl_b04",
        "SWIR1": "sur_refl_b06",
        "SWIR2": "sur_refl_b07",
    },
    RemoteSensingSource.CHIRPS: {"PRECIPITATION": "precipitation"},
    RemoteSensingSource.ERA5: {
        "PRECIPITATION": "total_precipitation",
        "TEMPERATURE": "mean_2m_air_temperature",
    },
}

#: Logical bands each index needs, in the order its ``compute_*`` function
#: takes them. ``DNBR`` is handled specially (needs two time periods).
_REQUIRED_BANDS_BY_INDEX: dict[SpectralIndex, tuple[str, ...]] = {
    SpectralIndex.NDVI: ("NIR", "RED"),
    SpectralIndex.EVI: ("NIR", "RED", "BLUE"),
    SpectralIndex.SAVI: ("NIR", "RED"),
    SpectralIndex.NDWI: ("GREEN", "NIR"),
    SpectralIndex.NBR: ("NIR", "SWIR2"),
    SpectralIndex.LST: ("THERMAL",),
    SpectralIndex.SPEI: ("PRECIPITATION", "TEMPERATURE"),
}


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator != 0 else 0.0


def compute_ndvi(nir: float, red: float) -> float:
    return _safe_ratio(nir - red, nir + red)


def compute_evi(nir: float, red: float, blue: float) -> float:
    denominator = nir + 6 * red - 7.5 * blue + 1
    return _safe_ratio(2.5 * (nir - red), denominator)


def compute_savi(nir: float, red: float, soil_brightness_l: float = 0.5) -> float:
    denominator = nir + red + soil_brightness_l
    return _safe_ratio((1 + soil_brightness_l) * (nir - red), denominator)


def compute_ndwi(green: float, nir: float) -> float:
    """McFeeters' (1996) water-body NDWI: ``(GREEN - NIR) / (GREEN + NIR)``."""
    return _safe_ratio(green - nir, green + nir)


def compute_nbr(nir: float, swir2: float) -> float:
    return _safe_ratio(nir - swir2, nir + swir2)


def compute_dnbr(pre_fire_nbr: float, post_fire_nbr: float) -> float:
    return pre_fire_nbr - post_fire_nbr


def compute_lst_celsius(thermal_kelvin: float) -> float:
    """Expects an already radiometrically-corrected thermal band in
    Kelvin (Landsat Collection 2 Level-2's documented scale/offset,
    ``DN * 0.00341802 + 149.0``, is applied upstream in
    ``infrastructure/gee_connector.py`` — this function only does the
    final Kelvin -> Celsius conversion)."""
    return thermal_kelvin - 273.15


def _thornthwaite_pet_mm(temperature_c: float) -> float:
    """A real Thornthwaite (1948) potential-evapotranspiration estimate,
    applied to a SINGLE period's mean temperature rather than a proper
    12-month annual heat index (see module docstring's simplification
    #2) — the heat index ``i`` and exponent ``a`` formulas are the
    textbook Thornthwaite equations; a period with mean temperature at or
    below freezing has zero PET by definition."""
    if temperature_c <= 0:
        return 0.0
    heat_index = (temperature_c / 5.0) ** 1.514
    a = (
        6.75e-7 * heat_index**3
        - 7.71e-5 * heat_index**2
        + 1.792e-2 * heat_index
        + 0.49239
    )
    return 16.0 * (10.0 * temperature_c / heat_index) ** a


def compute_spei(precipitation_mm: float, temperature_c: float) -> float:
    """Water-balance-based SPEI approximation — see module docstring's
    simplification #2. ``D = precipitation - PET`` is the real quantity
    SPEI standardizes; without a stored historical climatology to fit a
    log-logistic distribution against, this standardizes ``D`` with a
    fixed, documented scale (100mm) rather than a fitted distribution,
    bounded to SPEI's conventional ~[-3, 3] range via ``tanh``."""
    pet = _thornthwaite_pet_mm(temperature_c)
    water_balance = precipitation_mm - pet
    return 3.0 * math.tanh(water_balance / 100.0)


def extract_features(
    *,
    source: RemoteSensingSource,
    band_statistics: dict[str, float],
    requested_indices: tuple[SpectralIndex, ...],
    comparison_band_statistics: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """The Feature Extraction Pipeline's single entry point. Returns
    ``(computed, skipped)`` — ``skipped`` maps an index's name to a clear,
    human-readable reason it could NOT be computed for this source/job
    (missing band, missing comparison window), so a caller always gets an
    honest, complete accounting of every requested index rather than a
    silently-incomplete ``computed`` dict.
    """
    band_names = BAND_NAMES_BY_SOURCE.get(source, {})

    def _value(statistics: dict[str, float], logical_name: str) -> float | None:
        gee_band_name = band_names.get(logical_name)
        if gee_band_name is None:
            return None
        return statistics.get(gee_band_name)

    computed: dict[str, float] = {}
    skipped: dict[str, str] = {}

    for index in requested_indices:
        if index == SpectralIndex.DNBR:
            if comparison_band_statistics is None:
                skipped[index.value] = (
                    "dNBR requires a comparison_temporal_start/end window (pre/post fire)"
                )
                continue
            raw_dnbr_values = [
                _value(band_statistics, "NIR"),
                _value(band_statistics, "SWIR2"),
                _value(comparison_band_statistics, "NIR"),
                _value(comparison_band_statistics, "SWIR2"),
            ]
            if any(value is None for value in raw_dnbr_values):
                skipped[index.value] = (
                    f"{source.value} does not provide the NIR/SWIR2 bands required for dNBR"
                )
                continue
            dnbr_values: list[float] = [v for v in raw_dnbr_values if v is not None]
            pre_nir, pre_swir2, post_nir, post_swir2 = dnbr_values
            pre_nbr = compute_nbr(pre_nir, pre_swir2)
            post_nbr = compute_nbr(post_nir, post_swir2)
            computed[index.value] = compute_dnbr(pre_nbr, post_nbr)
            continue

        required_bands = _REQUIRED_BANDS_BY_INDEX[index]
        raw_values = [_value(band_statistics, band) for band in required_bands]
        if any(value is None for value in raw_values):
            skipped[index.value] = (
                f"{source.value} does not provide the band(s) required for "
                f"{index.value} ({', '.join(required_bands)})"
            )
            continue
        values: list[float] = [v for v in raw_values if v is not None]

        if index == SpectralIndex.NDVI:
            computed[index.value] = compute_ndvi(*values)
        elif index == SpectralIndex.EVI:
            computed[index.value] = compute_evi(*values)
        elif index == SpectralIndex.SAVI:
            computed[index.value] = compute_savi(*values)
        elif index == SpectralIndex.NDWI:
            computed[index.value] = compute_ndwi(*values)
        elif index == SpectralIndex.NBR:
            computed[index.value] = compute_nbr(*values)
        elif index == SpectralIndex.LST:
            computed[index.value] = compute_lst_celsius(*values)
        elif index == SpectralIndex.SPEI:
            computed[index.value] = compute_spei(*values)

    return computed, skipped
