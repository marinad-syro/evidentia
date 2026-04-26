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

from .databricks_client import filter_providers as db_filter
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


# ── Medical desert grid ────────────────────────────────────────────────────────

# Simplified clockwise India boundary polygon (lat, lon pairs).
# Good enough for grid-cell filtering; not a legal border definition.
_INDIA_POLY = [
    (37.0, 75.0), (35.5, 77.0), (34.5, 78.5), (32.5, 78.5),
    (30.0, 80.0), (28.8, 81.0), (28.0, 84.0), (27.5, 87.0),
    (27.5, 88.5), (27.0, 91.5), (28.5, 97.5), (27.0, 97.0),
    (25.5, 94.0), (24.0, 93.5), (23.5, 92.5), (22.0, 93.5),
    (21.5, 92.5), (22.5, 91.8), (23.5, 91.5), (25.0, 89.5),
    (26.5, 89.5), (22.5, 88.5), (20.5, 87.0), (17.5, 83.5),
    (14.5, 80.5), (13.0, 80.5), (10.5, 80.0), (8.5, 78.0),
    (8.0, 77.5),  (8.5, 76.5),  (10.0, 76.0), (12.5, 74.5),
    (14.5, 74.0), (18.0, 72.5), (21.0, 69.0), (22.5, 68.5),
    (23.5, 68.0), (25.0, 68.5), (27.0, 70.5), (29.0, 70.5),
    (31.0, 71.5), (33.0, 74.0), (34.5, 73.5), (35.5, 74.5),
    (37.0, 75.0),
]


def _in_india(lat: float, lon: float) -> bool:
    """Ray-casting point-in-polygon against the simplified India boundary."""
    inside = False
    n = len(_INDIA_POLY)
    j = n - 1
    for i in range(n):
        yi, xi = _INDIA_POLY[i]
        yj, xj = _INDIA_POLY[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


_desert_cache: dict | None = None


def get_desert_grid(min_trust: int = 50, cell_deg: float = 0.5) -> dict:
    """
    Compute (once, then cache) a grid of 0.5° cells over India.
    Each cell is classified by how far the nearest quality provider is.
    Quality = trust_score >= min_trust AND valid coordinates.
    """
    global _desert_cache
    if _desert_cache is not None:
        return _desert_cache
    assert _df is not None, "Data not loaded"

    # ── 1. Build quality-provider arrays ──────────────────────────────────────
    pids = _df["provider_id"].astype(str).values
    trust_scores_arr = np.array([_trust.get(p, {}).get("score", 0) for p in pids])
    lats_arr = pd.to_numeric(_df["latitude"],  errors="coerce").fillna(0).values.astype(float)
    lons_arr = pd.to_numeric(_df["longitude"], errors="coerce").fillna(0).values.astype(float)

    quality_mask = (
        (trust_scores_arr >= min_trust)
        & (lats_arr > 6) & (lats_arr < 38)   # rough India bounding box
        & (lons_arr > 67) & (lons_arr < 98)
    )
    p_lats = lats_arr[quality_mask]
    p_lons = lons_arr[quality_mask]
    print(f"Desert grid: {quality_mask.sum()} quality providers (trust ≥ {min_trust})")

    # ── 2. Grid cell centres ──────────────────────────────────────────────────
    half = cell_deg / 2
    lat_starts = np.arange(8.0,  37.0, cell_deg)
    lon_starts = np.arange(68.0, 97.0, cell_deg)
    s_lat, s_lon = np.meshgrid(lat_starts, lon_starts, indexing="ij")
    c_lats = (s_lat + half).ravel()
    c_lons = (s_lon + half).ravel()
    s_lats = s_lat.ravel()
    s_lons = s_lon.ravel()

    # ── 3. Vectorised approximate distance (chunked to limit RAM) ─────────────
    min_dists = np.full(len(c_lats), 9999.0)
    chunk = 400
    cos_lat = np.cos(np.radians(22.0))  # India centre latitude approximation
    for i in range(0, len(c_lats), chunk):
        dlat_km = (c_lats[i:i+chunk, None] - p_lats[None, :]) * 111.0
        dlon_km = (c_lons[i:i+chunk, None] - p_lons[None, :]) * 111.0 * cos_lat
        min_dists[i:i+chunk] = np.sqrt(dlat_km**2 + dlon_km**2).min(axis=1)

    # ── 4. Build response ─────────────────────────────────────────────────────
    cells = [
        {"lat": float(s_lats[i]), "lon": float(s_lons[i]), "min_dist_km": round(float(min_dists[i]), 1)}
        for i in range(len(c_lats))
        if min_dists[i] >= 10 and _in_india(float(c_lats[i]), float(c_lons[i]))
    ]

    # Top reference providers (trust ≥ 65) for the dot layer — cap at 400
    dot_mask = quality_mask & (trust_scores_arr >= 65)
    dot_idx = np.where(dot_mask)[0]
    dot_idx = dot_idx[np.argsort(trust_scores_arr[dot_idx])[::-1][:400]]
    dots = [
        {
            "lat": round(float(lats_arr[i]), 5),
            "lon": round(float(lons_arr[i]), 5),
            "name": str(_df.iloc[i].get("name") or ""),
            "trust_score": int(trust_scores_arr[i]),
        }
        for i in dot_idx
    ]

    n_desert     = sum(1 for c in cells if c["min_dist_km"] > 150)
    n_underserved = sum(1 for c in cells if 50 < c["min_dist_km"] <= 150)
    n_sparse     = sum(1 for c in cells if 10 < c["min_dist_km"] <= 50)

    _desert_cache = {
        "cells": cells,
        "quality_providers": dots,
        "cell_deg": cell_deg,
        "stats": {
            "quality_provider_count": int(quality_mask.sum()),
            "desert_cells": n_desert,
            "underserved_cells": n_underserved,
            "sparse_cells": n_sparse,
            "min_trust_used": min_trust,
        },
    }
    print(f"Desert grid done: {n_desert} deserts, {n_underserved} underserved, {n_sparse} sparse")
    return _desert_cache


# ── PIN code service desert map ───────────────────────────────────────────────

_SERVICES = {
    "oncology":  {"specialty": ["oncology"], "text": ["oncolog"]},
    "emergency": {"specialty": ["emergency"], "text": ["emergency"]},
    "trauma":    {"specialty": ["trauma"],    "text": ["trauma"]},
    "dialysis":  {"specialty": [],            "text": ["dialysis"]},
}

_pincode_cache: dict | None = None


def _provider_has_service(row, service_key: str) -> bool:
    """Return True if any specialty, capability, or procedure text matches the service."""
    cfg = _SERVICES[service_key]
    specialties  = _parse_list(row.get("specialties"))
    capabilities = _parse_list(row.get("capability"))
    procedures   = _parse_list(row.get("procedure"))

    spec_text = " ".join(str(s).lower() for s in specialties)
    free_text  = " ".join(str(s).lower() for s in capabilities + procedures)

    for kw in cfg["specialty"]:
        if kw in spec_text:
            return True
    for kw in cfg["text"]:
        if kw in spec_text or kw in free_text:
            return True
    return False


def get_pincode_grid() -> dict:
    """
    Group providers by PIN code. For each PIN × service combination classify as:
      green  — at least one provider with that service AND trust ≥ 65
      yellow — provider(s) claim the service but all have trust < 65
      red    — no provider in this PIN offers the service at all
    Returns centroid lat/lon per PIN derived from provider coordinates.
    """
    global _pincode_cache
    if _pincode_cache is not None:
        return _pincode_cache
    assert _df is not None, "Data not loaded"

    lats = pd.to_numeric(_df["latitude"],  errors="coerce")
    lons = pd.to_numeric(_df["longitude"], errors="coerce")
    pins = _df["address_zipOrPostcode"].astype(str).str.strip()

    # Only keep rows with a valid 6-digit Indian PIN and valid India-bbox coords
    valid = (
        pins.str.match(r"^\d{6}$")
        & lats.between(6, 38)
        & lons.between(67, 98)
    )

    df = _df[valid].copy()
    df["_lat"] = lats[valid].values
    df["_lon"] = lons[valid].values
    df["_pin"] = pins[valid].values
    df["_trust"] = [_trust.get(str(pid), {}).get("score", 0)
                    for pid in df["provider_id"].astype(str)]

    pincode_rows: dict[str, list] = {}
    for _, row in df.iterrows():
        pincode_rows.setdefault(row["_pin"], []).append(row)

    result_pins = []
    stats: dict[str, dict[str, int]] = {
        svc: {"green": 0, "yellow": 0, "red": 0} for svc in _SERVICES
    }

    for pin, rows in pincode_rows.items():
        centroid_lat = float(np.mean([r["_lat"] for r in rows]))
        centroid_lon = float(np.mean([r["_lon"] for r in rows]))

        services: dict[str, str] = {}
        for svc in _SERVICES:
            matching = [r for r in rows if _provider_has_service(r, svc)]
            if not matching:
                label = "red"
            elif any(r["_trust"] >= 65 for r in matching):
                label = "green"
            else:
                label = "yellow"
            services[svc] = label
            stats[svc][label] += 1

        result_pins.append({
            "pin": pin,
            "lat": round(centroid_lat, 5),
            "lon": round(centroid_lon, 5),
            "provider_count": len(rows),
            "services": services,
        })

    print(f"PIN code grid done: {len(result_pins)} PINs processed")
    _pincode_cache = {
        "pincodes": result_pins,
        "stats": stats,
        "total_pincodes": len(result_pins),
    }
    return _pincode_cache


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


def _normalize_url(url: str) -> str:
    if not url or url in ("nan", "None"):
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return "https://" + url


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


def _build_provider(row: "pd.Series | dict", distance_km: float, trust_score: int,
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
        website=_normalize_url(str(row.get("officialWebsite") or "")),
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
        if not any("staff" in (s.get("text", "") if isinstance(s, dict) else s).lower() for s in p.trust_signals):
            caveats.append("Staff profiles not found — call ahead to confirm availability.")
        elif len(p.procedures) + len(p.capabilities) < 2:
            caveats.append("Limited clinical detail listed — verify scope of services by phone.")
        p.caveat = " ".join(caveats)


async def run_search(
    query: str,
    provided_lat: float | None = None,
    provided_lon: float | None = None,
) -> AsyncGenerator[str, None]:
    """
    Main search pipeline. Yields SSE-formatted strings.
    Pipeline: intent → specialty → geocode → FAISS → post-filter → trust → Tavily → cards → results
    If provided_lat/lon are given, the geocoding step is skipped.
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

    if not location and (provided_lat is None or provided_lon is None):
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

    # Step 2: Location — use provided GPS coords or geocode the text location
    if provided_lat is not None and provided_lon is not None:
        user_lat, user_lon = provided_lat, provided_lon
        location_label = location if location else "your location"
        yield sse("geo", "done", "Using your current location…", "GPS coordinates provided")
    else:
        yield sse("geo", "active", f"Locating {location}…")
        try:
            user_lat, user_lon = await geocode(location)
        except ValueError as e:
            yield sse_error(str(e))
            return
        yield sse("geo", "done", f"Locating {location}…", "Found coordinates")
        location_label = location

    # Step 3: FAISS semantic search → candidate IDs → Databricks SQL filter
    radius_km = 10.0
    yield sse("filter", "active", f"Looking for {specialty_label}s within {int(radius_km)} km of {location_label}…")

    query_vec = await _embed_query(f"{specialty_desc} {specialty_label}")
    top_k = 200
    _, indices = _index.search(query_vec, top_k)

    # Map FAISS indices → provider_id strings + keep rows for local fallback
    candidate_rows = _df.iloc[indices[0]]
    candidate_ids = [
        str(_df.iloc[i].get("provider_id", ""))
        for i in indices[0] if i < len(_df)
    ]

    DB_TIMEOUT = 12.0  # seconds before falling back to local pandas filter

    def _local_filter(rows: pd.DataFrame, radius: float) -> tuple[list, dict]:
        found, counts = [], dict(sent=len(rows), matched=0)
        for _, row in rows.iterrows():
            try:
                lat = float(row.get("latitude") or 0)
                lon = float(row.get("longitude") or 0)
                if lat == 0 and lon == 0:
                    continue
                dist = haversine_km(user_lat, user_lon, lat, lon)
                if dist > radius:
                    continue
                specs = _parse_list(row.get("specialties"))
                if not any(s.lower() == specialty_id.lower() for s in specs):
                    continue
                if preference:
                    if preference.lower() not in str(row.get("operatorTypeId") or "").lower():
                        continue
                counts["matched"] += 1
                found.append((row, dist))
            except Exception:
                pass
        return found, counts

    async def _filter(ids: list[str], rows: pd.DataFrame, radius: float) -> tuple[list, dict, str]:
        """Try Databricks first; fall back to local on timeout or error."""
        try:
            result, stats = await asyncio.wait_for(
                db_filter(ids, specialty_id, user_lat, user_lon, radius, preference),
                timeout=DB_TIMEOUT,
            )
            return result, stats, "Databricks SQL"
        except Exception:
            result, stats = _local_filter(rows, radius)
            return result, stats, "local fallback"

    def _fmt(label: str, stats: dict, radius: float, source: str) -> str:
        return (
            f"{label} ({int(radius)} km, {source}):\n"
            f"  Candidates : {stats['sent']}\n"
            f"  Matched    : {stats['matched']}"
        )

    filter_log: list[str] = [
        f"Dataset: {len(_df):,} providers total",
        f"FAISS semantic search → top {top_k} candidate IDs retrieved",
        "",
    ]

    filtered, stats1, src1 = await _filter(candidate_ids, candidate_rows, radius_km)
    filter_log.append(_fmt("Pass 1", stats1, radius_km, src1))

    # Radius expansion: 10 km → 25 km → 50 km
    if not filtered:
        radius_km = 25.0
        yield sse("filter", "active", "No results within 10 km — expanding to 25 km…")
        filtered, stats2, src2 = await _filter(candidate_ids, candidate_rows, radius_km)
        filter_log += ["", _fmt("Pass 2 (expanded)", stats2, radius_km, src2)]

    if not filtered:
        radius_km = 50.0
        yield sse("filter", "active", "No results within 25 km — expanding to 50 km…")
        _, wide_indices = _index.search(query_vec, 500)
        wide_rows = _df.iloc[wide_indices[0]]
        wide_ids = [
            str(_df.iloc[i].get("provider_id", ""))
            for i in wide_indices[0] if i < len(_df)
        ]
        filtered, stats3, src3 = await _filter(wide_ids, wide_rows, radius_km)
        filter_log += ["", _fmt("Pass 3 (expanded, 500 candidates)", stats3, radius_km, src3)]

    yield sse("filter", "done",
              f"Looking for {specialty_label}s within {int(radius_km)} km of {location_label}…",
              f"Found {len(filtered)} candidates\n\n" + "\n".join(filter_log))

    if not filtered:
        yield sse_error(f"No {specialty_label} providers found within {int(radius_km)} km of {location_label}.")
        return

    # Step 4: Apply trust scores + composite ranking
    yield sse("rank", "active", "Narrowing to best clinical match…")
    scored: list[tuple[float, Provider]] = []
    for row, dist in filtered[:25]:
        pid = str(row.get("provider_id", ""))
        trust_entry = _trust.get(pid, {"score": 0, "signals": [], "penalties": [], "row": None})
        trust_score = trust_entry["score"]
        data_row = trust_entry.get("row")

        def _inject_row(sigs: list, row_num) -> list:
            if not row_num:
                return sigs
            return [{**s, "row": row_num} if isinstance(s, dict) and "row" not in s else s for s in sigs]

        provider = _build_provider(
            row, dist, trust_score,
            _inject_row(trust_entry.get("signals", []), data_row),
            _inject_row(trust_entry.get("penalties", []), data_row),
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
            provider.trust_signals.append({"text": "Website was live-verified during this search", "col": "officialWebsite"})
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
            "latitude": p.latitude,
            "longitude": p.longitude,
        }

    results_data = json.dumps({
        "providers": [provider_to_dict(p) for p in top_providers],
        "specialty_interpreted": specialty_label,
        "location_interpreted": location_label,
        "radius_km": radius_km,
        "total_candidates": len(filtered),
    })
    yield f"event: results\ndata: {results_data}\n\n"
