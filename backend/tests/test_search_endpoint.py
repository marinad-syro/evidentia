import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd


@pytest.fixture
def mock_search_deps(tmp_path):
    """Patch module-level singletons so search.py doesn't need real FAISS/parquet."""
    import faiss

    dim = 1536
    index = faiss.IndexFlatIP(dim)
    vec = np.zeros((1, dim), dtype=np.float32)
    vec[0, 0] = 1.0
    index.add(vec)

    df = pd.DataFrame([{
        "provider_id": "abc123def456",
        "name": "City Eye Hospital",
        "facilityTypeId": "Hospital",
        "address_line1": "12 MG Road",
        "address_line2": "",
        "address_city": "Bangalore",
        "officialPhone": "+919876543210",
        "email": "info@cityeye.in",
        "officialWebsite": "https://cityeye.in",
        "specialties": json.dumps(["ophthalmology"]),
        "procedure": json.dumps(["cataract surgery"]),
        "capability": json.dumps(["OPD"]),
        "description": "Leading eye care in Bangalore.",
        "numberDoctors": 5,
        "capacity": 50,
        "latitude": 12.9352,
        "longitude": 77.6245,
        "operatorTypeId": "private",
    }])

    trust = {"abc123def456": {"score": 75, "signals": ["Valid phone"], "penalties": []}}

    with patch("backend.api.search._index", index), \
         patch("backend.api.search._df", df), \
         patch("backend.api.search._trust", trust), \
         patch("backend.api.search._known_specialty_ids", {"ophthalmology"}):
        yield


@pytest.mark.asyncio
async def test_run_search_yields_sse_events(mock_search_deps):
    from backend.api.search import run_search

    with patch("backend.api.search._extract_intent", return_value={
        "specialty_description": "eye doctor",
        "location": "Koramangala",
        "preference": None,
    }), patch("backend.api.search.resolve_specialty", return_value=("ophthalmology", "Ophthalmology")), \
       patch("backend.api.search.geocode", return_value=(12.9352, 77.6245)), \
       patch("backend.api.search._embed_query", return_value=np.array([[1.0] + [0.0]*1535], dtype=np.float32)), \
       patch("backend.api.search.verify_providers_parallel", return_value=[
           MagicMock(verified=True, trust_delta=10, red_flags=[])
       ]), \
       patch("backend.api.search._generate_cards", new_callable=AsyncMock):
        events = []
        async for chunk in run_search("eye doctor near Koramangala"):
            events.append(chunk)

    event_types = [e.split("\n")[0].replace("event: ", "") for e in events if e.startswith("event:")]
    assert "step" in event_types
    assert "results" in event_types


@pytest.mark.asyncio
async def test_run_search_no_location_returns_error(mock_search_deps):
    from backend.api.search import run_search

    with patch("backend.api.search._extract_intent", return_value={
        "specialty_description": "eye doctor",
        "location": "",
        "preference": None,
    }):
        events = []
        async for chunk in run_search("eye doctor"):
            events.append(chunk)

    error_events = [e for e in events if "event: error" in e]
    assert len(error_events) == 1
    assert "location" in error_events[0].lower()


@pytest.mark.asyncio
async def test_composite_score_formula():
    from backend.api.search import _composite_score

    score_perfect = _composite_score(100, 0)
    assert score_perfect == pytest.approx(1.0)

    score_mid = _composite_score(50, 25)
    assert 0 < score_mid < 1

    score_worst = _composite_score(0, 50)
    assert score_worst == pytest.approx(0.0)
