import math
import pytest
from unittest.mock import patch, MagicMock

from backend.api.geo import haversine_km, geocode


def test_haversine_same_point():
    assert haversine_km(12.97, 77.59, 12.97, 77.59) == pytest.approx(0.0, abs=0.01)


def test_haversine_known_distance():
    # Bangalore to Chennai is approx 290 km
    dist = haversine_km(12.9716, 77.5946, 13.0827, 80.2707)
    assert 280 < dist < 300


def test_haversine_symmetry():
    d1 = haversine_km(12.9716, 77.5946, 18.5204, 73.8567)
    d2 = haversine_km(18.5204, 73.8567, 12.9716, 77.5946)
    assert d1 == pytest.approx(d2, rel=1e-6)


@pytest.mark.asyncio
async def test_geocode_returns_tuple():
    mock_result = MagicMock()
    mock_result.latitude = 12.9716
    mock_result.longitude = 77.5946

    with patch("backend.api.geo._geocode_cached", return_value=(12.9716, 77.5946)):
        lat, lon = await geocode("Koramangala")
        assert isinstance(lat, float)
        assert isinstance(lon, float)


@pytest.mark.asyncio
async def test_geocode_raises_on_not_found():
    with patch("backend.api.geo._geocode_cached", return_value=None):
        with pytest.raises(ValueError, match="Could not find"):
            await geocode("xyzzy_fake_place_12345")
