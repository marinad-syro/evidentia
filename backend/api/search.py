import asyncio
import json
import os
import sys
from pathlib import Path
from typing import AsyncGenerator

import faiss
import numpy as np
import pandas as pd
from openai import AsyncOpenAI

from .geo import geocode, haversine_km
from .specialty import resolve_specialty
from .tavily_verify import verify_providers_parallel, VerificationResult
from ..models import Provider, SearchResult

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"

DATA_DIR = Path(__file__).parent.parent / "data"
FAISS_PATH = DATA_DIR / "embeddings.faiss"
PARQUET_PATH = DATA_DIR / "providers.parquet"
TRUST_PATH = DATA_DIR / "trust.json"

# Module-level singletons loaded at startup
_index: faiss.Index | None = None
_df: pd.DataFrame | None = None
_trust: dict = {}
_known_specialty_ids: set[str] = set()
_openai: AsyncOpenAI | None = None
_embed_model = None


def load_data() -> None:
    """Load FAISS index, provider parquet, and trust scores. Call at app startup."""
    global _index, _df, _trust, _known_specialty_ids

    if not FAISS_PATH.exists():
        raise RuntimeError(
            f"FAISS index not found at {FAISS_PATH}. "
            "Run: python pre_compute/embed.py --csv data/providers.csv"
        )
    if not PARQUET_PATH.exists():
        raise RuntimeError(f"Provider parquet not found at {PARQUET_PATH}.")

    _index = faiss.read_index(str(FAISS_PATH))
    _df = pd.read_parquet(PARQUET_PATH)
    _trust = json.loads(TRUST_PATH.read_text()) if TRUST_PATH.exists() else {}

    # Build known specialty IDs from the dataset
    all_specialties: set[str] = set()
    for val in _df["specialties"].dropna():
        try:
            items = json.loads(val) if isinstance(val, str) else val
            if isinstance(items, list):
                all_specialties.update(str(s) for s in items)
        except Exception:
            pass
    _known_specialty_ids = all_specialties

    print(f"Loaded {_index.ntotal} vectors, {len(_df)} providers, {len(_trust)} trust scores")
    print(f"Known specialty IDs: {len(_known_specialty_ids)}")


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(
            api_key=os.environ["XAI_API_KEY"],
            base_url="https://api.x.ai/v1",
        )
    return _openai


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def _parse_list(val) -> list:
    if not val or (isinstance(val, float) and np.isnan(val)):
        return []
    if isinstance(val, list):
        return val
    try:
        return json.loads(val) if isinstance(val, str) else []
    except Exception:
        return []


def _safe_int(val) -> int:
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return 0
        return int(val)
    except (ValueError, TypeError):
        return 0


def _composite_score(trust_score: int, distance_km: float) -> float:
    trust_norm = trust_score / 100
    dist_norm = 1 - min(distance_km, 50) / 50
    return trust_norm * 0.6 + dist_norm * 0.4


async def _extract_intent(query: str) -> dict:
    """LLM call: extract specialty description and location from NL query."""
    response = await _get_openai().chat.completions.create(
        model="grok-3",
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract structured information from a healthcare search query. "
                    "Return a JSON object with: "
                    "specialty_description (what kind of doctor/care they need), "
                    "location (city or area name, in India), "
                    "preference (public/private if mentioned, else null). "
                    "Return ONLY the JSON."
                ),
            },
            {"role": "user", "content": query},
        ],
        max_tokens=100,
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content or "{}")


async def _embed_query(text: str) -> np.ndarray:
    """Embed query using the same local model used at index build time."""
    loop = asyncio.get_event_loop()
    model = _get_embed_model()
    vec = await loop.run_in_executor(None, lambda: model.encode([text]))
    vec = np.array(vec, dtype=np.float32)
    faiss.normalize_L2(vec)
    return vec


def _build_provider(row: pd.Series, distance_km: float, trust_score: int,
                    trust_signals: list, trust_penalties: list) -> Provider:
    specialties = _parse_list(row.get("specialties"))
    procedures = _parse_list(row.get("procedure"))
    capabilities = _parse_list(row.get("capability"))

    return Provider(
        provider_id=str(row.get("provider_id", "")),
        name=str(row.get("name") or "Unknown"),
        facility_type=str(row.get("facilityTypeId") or "Healthcare Provider"),
        address=", ".join(filter(None, [
            str(row.get("address_line1") or ""),
            str(row.get("address_line2") or ""),
            str(row.get("address_city") or ""),
        ])),
        city=str(row.get("address_city") or ""),
        phone=str(row.get("officialPhone") or ""),
        email=str(row.get("email") or ""),
        website=str(row.get("officialWebsite") or ""),
        specialties=specialties,
        procedures=procedures,
        capabilities=capabilities,
        description=str(row.get("description") or ""),
        number_doctors=_safe_int(row.get("numberDoctors")),
        capacity=_safe_int(row.get("capacity")),
        latitude=float(row.get("latitude") or 0),
        longitude=float(row.get("longitude") or 0),
        distance_km=round(distance_km, 1),
        trust_score=trust_score,
        trust_signals=trust_signals,
        trust_penalties=trust_penalties,
    )


async def _generate_cards(providers: list[Provider], query: str) -> None:
    """Batch LLM call to generate 'why this one' + caveats. Mutates providers in-place."""
    if not providers:
        return

    prompts = []
    for p in providers:
        prompts.append(
            f"Provider: {p.name}. "
            f"Specialties: {', '.join(p.specialties[:5])}. "
            f"Query match: {query}. "
            f"Beds: {p.capacity}. "
            f"In one sentence (max 20 words), explain why this provider fits the user's need. "
            f"Be specific — no generic phrases like 'highly recommended' or 'great choice'."
        )

    try:
        tasks = [
            _get_openai().chat.completions.create(
                model="grok-3",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=60,
                temperature=0.3,
            )
            for prompt in prompts
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for p, resp in zip(providers, responses):
            if isinstance(resp, Exception):
                p.why_this = f"Matches your need for {p.specialties[0] if p.specialties else 'this specialty'}."
            else:
                p.why_this = (resp.choices[0].message.content or "").strip()
    except Exception:
        for p in providers:
            p.why_this = f"Matches your need for {p.specialties[0] if p.specialties else 'this specialty'}."

    # Rule-based caveats
    for p in providers:
        caveats = []
        if p.number_doctors == 1:
            caveats.append("1-doctor clinic — for major procedures consider a larger hospital.")
        if not any("affiliated" in s.lower() for s in p.trust_signals):
            caveats.append("Staff profiles not found — call ahead to confirm availability.")
        elif len(p.procedures) + len(p.capabilities) < 2:
            caveats.append("Limited clinical detail listed — verify scope of services by phone.")
        p.caveat = " ".join(caveats)


async def run_search(query: str) -> AsyncGenerator[str, None]:
    """
    Main search pipeline. Yields SSE-formatted strings.
    Pipeline: intent → specialty → geocode → FAISS → post-filter → trust → Tavily → cards → results
    """
    assert _index is not None and _df is not None, "Data not loaded"

    def sse(event_id: str, status: str, text: str, detail: str = "") -> str:
        data = json.dumps({"id": event_id, "status": status, "text": text, "detail": detail})
        return f"event: step\ndata: {data}\n\n"

    def sse_error(message: str) -> str:
        data = json.dumps({"error": message})
        return f"event: error\ndata: {data}\n\n"

    # Step 1: Intent extraction
    yield sse("intent", "active", "Understanding your symptoms…")
    try:
        intent = await _extract_intent(query)
    except Exception as e:
        yield sse_error("Service temporarily busy — try again in a moment.")
        return

    specialty_desc = intent.get("specialty_description", query)
    location = intent.get("location", "")
    preference = intent.get("preference")

    if not location:
        yield sse_error("Please include a location in your query, e.g. 'near Bangalore'.")
        return

    # Specialty resolution
    try:
        specialty_id, specialty_label = await resolve_specialty(specialty_desc, _known_specialty_ids)
    except ValueError as e:
        yield sse_error(str(e))
        return

    yield sse("intent", "done", "Understanding your symptoms…",
              f"Mapped to: {specialty_label}")

    # Step 2: Geocoding
    yield sse("geo", "active", f"Locating {location}…")
    try:
        user_lat, user_lon = await geocode(location)
    except ValueError as e:
        yield sse_error(str(e))
        return
    yield sse("geo", "done", f"Locating {location}…", f"Found coordinates")

    # Step 3: FAISS semantic search over full index
    radius_km = 10.0
    yield sse("filter", "active", f"Looking for {specialty_label}s within {int(radius_km)} km of {location}…")

    query_vec = await _embed_query(f"{specialty_desc} {specialty_label}")
    top_k = 200
    _, indices = _index.search(query_vec, top_k)
    candidate_rows = _df.iloc[indices[0]]

    # Post-filter: specialty match + haversine radius
    def matches(row: pd.Series) -> tuple[bool, float]:
        try:
            lat, lon = float(row.get("latitude") or 0), float(row.get("longitude") or 0)
            if lat == 0 and lon == 0:
                return False, 0.0
            dist = haversine_km(user_lat, user_lon, lat, lon)
            specialties = _parse_list(row.get("specialties"))
            specialty_match = any(
                s.lower() == specialty_id.lower() for s in specialties
            )
            if preference:
                op_type = str(row.get("operatorTypeId") or "").lower()
                if preference.lower() not in op_type:
                    return False, dist
            return specialty_match and dist <= radius_km, dist
        except Exception:
            return False, 0.0

    filtered = []
    for _, row in candidate_rows.iterrows():
        ok, dist = matches(row)
        if ok:
            filtered.append((row, dist))

    # Radius expansion if no results
    if not filtered:
        radius_km = 25.0
        yield sse("filter", "active",
                  f"No results within 10 km — expanding to {int(radius_km)} km…",
                  "Expanding search radius")
        for _, row in candidate_rows.iterrows():
            try:
                lat, lon = float(row.get("latitude") or 0), float(row.get("longitude") or 0)
                dist = haversine_km(user_lat, user_lon, lat, lon)
                specialties = _parse_list(row.get("specialties"))
                if any(s.lower() == specialty_id.lower() for s in specialties) and dist <= radius_km:
                    filtered.append((row, dist))
            except Exception:
                pass

    yield sse("filter", "done",
              f"Looking for {specialty_label}s within {int(radius_km)} km of {location}…",
              f"Found {len(filtered)} candidates")

    if not filtered:
        yield sse_error(f"No {specialty_label} providers found within {int(radius_km)} km of {location}.")
        return

    # Step 4: Apply trust scores + composite ranking
    yield sse("rank", "active", "Narrowing to best clinical match…")
    scored: list[tuple[float, Provider]] = []
    for row, dist in filtered[:25]:
        pid = str(row.get("provider_id", ""))
        trust_entry = _trust.get(pid, {"score": 0, "signals": [], "penalties": []})
        trust_score = trust_entry["score"]
        provider = _build_provider(
            row, dist, trust_score,
            trust_entry.get("signals", []),
            trust_entry.get("penalties", []),
        )
        provider.final_score = _composite_score(trust_score, dist)
        scored.append((provider.final_score, provider))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_providers = [p for _, p in scored[:5]]

    yield sse("rank", "done", "Narrowing to best clinical match…",
              f"Shortlisted top {len(top_providers)} by similarity + trust")

    # Step 5: Live Tavily verification for top 3
    top3 = top_providers[:3]
    yield sse("trust", "active", "Scoring providers based on reliability…",
              "Verifying contact details for top 3")

    verify_inputs = [
        (p.website, p.name, p.phone, p.city) for p in top3
    ]
    verifications: list[VerificationResult] = await verify_providers_parallel(verify_inputs)

    for provider, vr in zip(top3, verifications):
        new_score = min(100, provider.trust_score + vr.trust_delta)
        provider.trust_score = new_score
        provider.live_verified = vr.verified
        provider.red_flags = vr.red_flags
        if vr.trust_delta > 0:
            provider.trust_signals.append("Live website verified ✓")
        elif vr.trust_delta < 0:
            provider.trust_penalties.extend(vr.red_flags)
        # Re-score
        provider.final_score = _composite_score(new_score, provider.distance_km)

    # Re-sort after live verification adjustments
    top_providers.sort(key=lambda p: p.final_score, reverse=True)
    top_providers = top_providers[:3]

    yield sse("trust", "done", "Scoring providers based on reliability…",
              f"Verified {sum(1 for p in top3 if p.live_verified)} of 3 providers")

    # Step 6: Generate "why this one" summaries
    await _generate_cards(top_providers, query)

    # Done
    yield sse("done", "done", f"Done. Here are {len(top_providers)} providers I'd recommend.")

    # Results payload
    def provider_to_dict(p: Provider) -> dict:
        return {
            "provider_id": p.provider_id,
            "name": p.name,
            "facility_type": p.facility_type,
            "address": p.address,
            "city": p.city,
            "phone": p.phone,
            "email": p.email,
            "website": p.website,
            "specialties": p.specialties[:5],
            "distance_km": p.distance_km,
            "trust_score": p.trust_score,
            "trust_signals": p.trust_signals,
            "trust_penalties": p.trust_penalties,
            "live_verified": p.live_verified,
            "red_flags": p.red_flags,
            "why_this": p.why_this,
            "caveat": p.caveat,
            "number_doctors": p.number_doctors,
        }

    results_data = json.dumps({
        "providers": [provider_to_dict(p) for p in top_providers],
        "specialty_interpreted": specialty_label,
        "location_interpreted": location,
        "radius_km": radius_km,
        "total_candidates": len(filtered),
    })
    yield f"event: results\ndata: {results_data}\n\n"
