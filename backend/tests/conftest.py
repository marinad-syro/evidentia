import json
import os

import numpy as np
import pytest

# Ensure env vars are set before importing modules
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("TAVILY_API_KEY", "test-key")


@pytest.fixture
def sample_provider_row() -> dict:
    return {
        "provider_id": "abc123def456",
        "name": "City Eye Hospital",
        "facilityTypeId": "Hospital",
        "address_line1": "12 MG Road",
        "address_line2": "",
        "address_city": "Bangalore",
        "officialPhone": "+919876543210",
        "email": "info@cityeye.in",
        "officialWebsite": "https://cityeye.in",
        "specialties": json.dumps(["ophthalmology", "optometry"]),
        "procedure": json.dumps(["cataract surgery", "LASIK"]),
        "capability": json.dumps(["ICU", "OPD"]),
        "description": "City Eye Hospital is a leading ophthalmology centre in Bangalore with 15+ years of experience.",
        "numberDoctors": 5,
        "capacity": 50,
        "latitude": 12.9716,
        "longitude": 77.5946,
    }


@pytest.fixture
def phone_counts() -> dict:
    return {"+919876543210": 1}
