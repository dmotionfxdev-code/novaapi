"""Unit tests for Sprint 14's Feature Extraction Pipeline (requirement
#4) — pure band-math functions and the ``extract_features`` dispatcher.
Pure logic, no I/O, no ``ee`` dependency.
"""

from __future__ import annotations

import math

import pytest

from georisk.contexts.data_acquisition.domain.feature_extraction import (
    BAND_NAMES_BY_SOURCE,
    compute_dnbr,
    compute_evi,
    compute_lst_celsius,
    compute_nbr,
    compute_ndvi,
    compute_ndwi,
    compute_savi,
    compute_spei,
    extract_features,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    RemoteSensingSource,
    SpectralIndex,
)

pytestmark = pytest.mark.unit


def test_compute_ndvi_healthy_vegetation() -> None:
    assert compute_ndvi(nir=0.5, red=0.1) == pytest.approx(0.6667, abs=1e-3)


def test_compute_ndvi_handles_zero_denominator() -> None:
    assert compute_ndvi(nir=0.0, red=0.0) == 0.0


def test_compute_evi() -> None:
    value = compute_evi(nir=0.5, red=0.1, blue=0.05)
    assert value == pytest.approx(2.5 * 0.4 / (0.5 + 0.6 - 0.375 + 1), abs=1e-6)


def test_compute_savi_matches_ndvi_when_l_is_zero() -> None:
    assert compute_savi(nir=0.5, red=0.1, soil_brightness_l=0.0) == pytest.approx(
        compute_ndvi(nir=0.5, red=0.1)
    )


def test_compute_ndwi_water_body() -> None:
    # Water reflects more in green than NIR -> positive NDWI.
    assert compute_ndwi(green=0.3, nir=0.05) > 0


def test_compute_nbr_and_dnbr() -> None:
    pre_nbr = compute_nbr(nir=0.5, swir2=0.1)
    post_nbr = compute_nbr(nir=0.2, swir2=0.3)
    assert pre_nbr > post_nbr  # burned area loses NIR, gains SWIR
    assert compute_dnbr(pre_nbr, post_nbr) == pytest.approx(pre_nbr - post_nbr)


def test_compute_lst_celsius() -> None:
    assert compute_lst_celsius(300.0) == pytest.approx(26.85, abs=1e-2)


def test_compute_spei_wet_conditions_positive() -> None:
    # High precipitation, mild temperature -> positive water balance.
    assert compute_spei(precipitation_mm=200.0, temperature_c=15.0) > 0


def test_compute_spei_dry_conditions_negative() -> None:
    # No precipitation, hot temperature -> negative water balance.
    assert compute_spei(precipitation_mm=0.0, temperature_c=35.0) < 0


def test_compute_spei_bounded_like_conventional_spei_range() -> None:
    value = compute_spei(precipitation_mm=1000.0, temperature_c=0.0)
    assert -3.0 <= value <= 3.0


def test_band_names_cover_every_remote_sensing_source() -> None:
    assert set(BAND_NAMES_BY_SOURCE) == set(RemoteSensingSource)


def test_extract_features_computes_ndvi_for_sentinel2() -> None:
    computed, skipped = extract_features(
        source=RemoteSensingSource.SENTINEL_2,
        band_statistics={"B8": 0.5, "B4": 0.1, "B2": 0.05, "B3": 0.2},
        requested_indices=(SpectralIndex.NDVI, SpectralIndex.EVI, SpectralIndex.NDWI),
    )
    assert computed["NDVI"] == pytest.approx(compute_ndvi(0.5, 0.1))
    assert "EVI" in computed
    assert "NDWI" in computed
    assert skipped == {}


def test_extract_features_skips_lst_for_source_without_thermal_band() -> None:
    computed, skipped = extract_features(
        source=RemoteSensingSource.SENTINEL_2,
        band_statistics={"B8": 0.5, "B4": 0.1},
        requested_indices=(SpectralIndex.LST,),
    )
    assert computed == {}
    assert "LST" in skipped
    assert "SENTINEL_2" in skipped["LST"]


def test_extract_features_computes_lst_for_landsat() -> None:
    computed, skipped = extract_features(
        source=RemoteSensingSource.LANDSAT,
        band_statistics={"ST_B10": 300.0},
        requested_indices=(SpectralIndex.LST,),
    )
    assert computed["LST"] == pytest.approx(compute_lst_celsius(300.0))
    assert skipped == {}


def test_extract_features_computes_spei_for_era5() -> None:
    computed, _ = extract_features(
        source=RemoteSensingSource.ERA5,
        band_statistics={"total_precipitation": 150.0, "mean_2m_air_temperature": 18.0},
        requested_indices=(SpectralIndex.SPEI,),
    )
    assert computed["SPEI"] == pytest.approx(compute_spei(150.0, 18.0))


def test_extract_features_sentinel1_has_no_computable_indices() -> None:
    computed, skipped = extract_features(
        source=RemoteSensingSource.SENTINEL_1,
        band_statistics={"VV": -12.0, "VH": -18.0},
        requested_indices=(SpectralIndex.NDVI, SpectralIndex.NBR),
    )
    assert computed == {}
    assert set(skipped) == {"NDVI", "NBR"}


def test_extract_features_dnbr_requires_comparison_statistics() -> None:
    computed, skipped = extract_features(
        source=RemoteSensingSource.LANDSAT,
        band_statistics={"SR_B5": 0.5, "SR_B7": 0.1},
        requested_indices=(SpectralIndex.DNBR,),
        comparison_band_statistics=None,
    )
    assert computed == {}
    assert "comparison" in skipped["DNBR"]


def test_extract_features_dnbr_with_comparison_statistics() -> None:
    computed, skipped = extract_features(
        source=RemoteSensingSource.LANDSAT,
        band_statistics={"SR_B5": 0.5, "SR_B7": 0.1},
        requested_indices=(SpectralIndex.DNBR,),
        comparison_band_statistics={"SR_B5": 0.2, "SR_B7": 0.3},
    )
    pre_nbr = compute_nbr(0.5, 0.1)
    post_nbr = compute_nbr(0.2, 0.3)
    assert computed["DNBR"] == pytest.approx(compute_dnbr(pre_nbr, post_nbr))
    assert skipped == {}


def test_extract_features_missing_band_is_honestly_skipped() -> None:
    computed, skipped = extract_features(
        source=RemoteSensingSource.CHIRPS,
        band_statistics={"precipitation": 5.0},
        requested_indices=(SpectralIndex.NDVI,),
    )
    assert computed == {}
    assert "NDVI" in skipped
    assert not math.isnan(5.0)  # sanity: CHIRPS band value itself is a plain float
