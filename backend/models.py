from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Provider:
    provider_id: str
    name: str
    facility_type: str
    address: str
    city: str
    phone: str
    email: str
    website: str
    specialties: list[str]
    procedures: list[str]
    capabilities: list[str]
    description: str
    number_doctors: int
    capacity: int
    latitude: float
    longitude: float
    distance_km: float = 0.0
    trust_score: int = 0
    trust_signals: list[dict] = field(default_factory=list)
    trust_penalties: list[dict] = field(default_factory=list)
    live_verified: bool = False
    red_flags: list[str] = field(default_factory=list)
    why_this: str = ""
    caveat: str = ""
    final_score: float = 0.0


@dataclass
class SearchResult:
    providers: list[Provider]
    specialty_interpreted: str
    location_interpreted: str
    radius_km: float
    total_candidates: int
