import asyncio
from functools import lru_cache
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import math

_geocoder = Nominatim(user_agent="hn2026-healthcare-finder", timeout=5)


@lru_cache(maxsize=512)
def _geocode_cached(location: str) -> tuple[float, float] | None:
    try:
        result = _geocoder.geocode(f"{location}, India")
        if result:
            return result.latitude, result.longitude
        return None
    except (GeocoderTimedOut, GeocoderServiceError):
        return None


async def geocode(location: str) -> tuple[float, float]:
    """
    Returns (lat, lon). Raises ValueError on failure.
    Nominatim is sync; run in executor to avoid blocking the event loop.
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _geocode_cached, location)
    if result is None:
        raise ValueError(
            f"Could not find '{location}'. "
            "Try a city name instead, e.g. 'Bangalore', 'Mumbai', 'Pune'."
        )
    return result


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
