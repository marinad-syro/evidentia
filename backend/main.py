import asyncio
import math
import os
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

load_dotenv()

from .api.search import get_desert_grid, get_pincode_grid, load_data, run_search
from .api.voice import handle_voice_session


async def _warmup():
    """Pre-compute pincode need scores at startup so the first request is instant."""
    try:
        loop = asyncio.get_event_loop()
        pincode_data, state_features = await asyncio.gather(
            loop.run_in_executor(None, get_pincode_grid),
            _ensure_state_features(),
        )
        global _pincode_enriched_cache
        _pincode_enriched_cache = await loop.run_in_executor(
            None, _sync_enrich_need_scores, pincode_data, state_features
        )
        print(f"[warmup] pincode need scores ready — {len(_pincode_enriched_cache['pincodes'])} PINs")
    except Exception as e:
        print(f"[warmup] need score enrichment failed ({e}), will retry on first request")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_data()
    asyncio.create_task(_warmup())
    yield


app = FastAPI(title="Healthcare Provider Finder", lifespan=lifespan)

_extra_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"] + _extra_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/search")
async def search(
    q: str = Query(..., min_length=3),
    lat: float | None = Query(None),
    lon: float | None = Query(None),
):
    return StreamingResponse(
        run_search(q, provided_lat=lat, provided_lon=lon),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.websocket("/ws/voice")
async def voice_ws(ws: WebSocket):
    await handle_voice_session(ws)


@app.get("/deserts")
async def deserts():
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, get_desert_grid)
    return JSONResponse(content=data)


@app.get("/deserts/pincodes")
async def deserts_pincodes():
    global _pincode_enriched_cache
    if _pincode_enriched_cache is not None:
        return JSONResponse(content=_pincode_enriched_cache)

    # Warmup still running — return basic data immediately so the page loads,
    # with need_score=0 as a fallback. The client can refresh once warmup is done.
    loop = asyncio.get_event_loop()
    try:
        pincode_data, state_features = await asyncio.wait_for(
            asyncio.gather(
                loop.run_in_executor(None, get_pincode_grid),
                _ensure_state_features(),
            ),
            timeout=25,
        )
        _pincode_enriched_cache = await loop.run_in_executor(
            None, _sync_enrich_need_scores, pincode_data, state_features
        )
    except Exception as e:
        print(f"[pincodes] enrichment failed or timed out ({e}), returning base data")
        pincode_data = await loop.run_in_executor(None, get_pincode_grid)
        for pin in pincode_data["pincodes"]:
            pin.setdefault("need_score", 0.0)
            pin.setdefault("state", "")
        # Don't cache the unenriched version so warmup can still populate it
        return JSONResponse(content=pincode_data)

    return JSONResponse(content=_pincode_enriched_cache)


_STATE_GEOJSON_URL = (
    "https://raw.githubusercontent.com/geohacker/india/master/state/india_state.geojson"
)

# Census 2011 state populations — embedded so we don't depend on an external join
_STATE_POP: dict[str, int] = {
    "Uttar Pradesh": 199812341, "Maharashtra": 112374333, "Bihar": 104099452,
    "West Bengal": 91276115, "Andhra Pradesh": 84580777, "Madhya Pradesh": 72626809,
    "Tamil Nadu": 72147030, "Rajasthan": 68548437, "Karnataka": 61095297,
    "Gujarat": 60439692, "Odisha": 41974218, "Kerala": 33406061,
    "Jharkhand": 32988134, "Assam": 31205576, "Punjab": 27743338,
    "Chhattisgarh": 25545198, "Haryana": 25351462, "Delhi": 16787941,
    "Jammu & Kashmir": 12541302, "Jammu and Kashmir": 12541302,
    "Uttarakhand": 10086292, "Himachal Pradesh": 6864602,
    "Tripura": 3673917, "Meghalaya": 2966889, "Manipur": 2855794,
    "Nagaland": 1978502, "Goa": 1458545, "Arunachal Pradesh": 1383727,
    "Mizoram": 1097206, "Sikkim": 610577, "Telangana": 35003674,
    "Puducherry": 1247953, "Chandigarh": 1055450,
    "Dadra and Nagar Haveli": 343709, "Daman and Diu": 243247,
    "Andaman and Nicobar Islands": 380581, "Lakshadweep": 64473,
}

# Approximate state areas in km² (Census 2011 boundaries)
_STATE_AREA_KM2: dict[str, float] = {
    "Uttar Pradesh": 240928, "Maharashtra": 307713, "Bihar": 94163,
    "West Bengal": 88752, "Andhra Pradesh": 162975, "Madhya Pradesh": 308252,
    "Tamil Nadu": 130058, "Rajasthan": 342239, "Karnataka": 191791,
    "Gujarat": 196024, "Odisha": 155707, "Kerala": 38852,
    "Jharkhand": 79716, "Assam": 78438, "Punjab": 50362,
    "Chhattisgarh": 135192, "Haryana": 44212, "Delhi": 1484,
    "Jammu & Kashmir": 42241, "Jammu and Kashmir": 42241,
    "Uttarakhand": 53483, "Himachal Pradesh": 55673,
    "Tripura": 10486, "Meghalaya": 22429, "Manipur": 22327,
    "Nagaland": 16579, "Goa": 3702, "Arunachal Pradesh": 83743,
    "Mizoram": 21081, "Sikkim": 7096, "Telangana": 112077,
    "Puducherry": 479, "Chandigarh": 114,
    "Dadra and Nagar Haveli": 491, "Daman and Diu": 112,
    "Andaman and Nicobar Islands": 8249, "Lakshadweep": 32,
}

# India average population density, Census 2011
_NATIONAL_DENSITY = 382.0  # people / km²

_population_cache: dict | None = None


@app.get("/population")
async def population():
    global _population_cache
    if _population_cache is not None:
        return JSONResponse(content=_population_cache)

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(_STATE_GEOJSON_URL)
            r.raise_for_status()
            geojson = r.json()
        print(f"[population] fetched {len(geojson.get('features', []))} state features")
    except Exception as e:
        print(f"[population] fetch failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))

    # Print property keys from first feature so we can see the schema
    features = geojson.get("features", [])
    if features:
        sample = features[0].get("properties") or {}
        print(f"[population] property keys: {list(sample.keys())}")
        print(f"[population] sample values: { {k: v for k, v in list(sample.items())[:6]} }")

    # Match by scanning ALL string properties — works regardless of field name
    _state_pop_lower = {k.lower(): v for k, v in _STATE_POP.items()}

    populations = []
    for f in features:
        props = f.get("properties") or {}
        matched_name = ""
        matched_pop = 0
        for v in props.values():
            if not isinstance(v, str) or len(v) < 3:
                continue
            pop = _STATE_POP.get(v) or _state_pop_lower.get(v.lower(), 0)
            if pop:
                matched_name = v
                matched_pop = pop
                break
        props["_population"] = matched_pop
        props["_state_name"] = matched_name
        if matched_pop > 0:
            populations.append(matched_pop)

    print(f"[population] matched {len(populations)}/{len(features)} states to Census data")

    populations.sort()
    n = len(populations)
    breakpoints = [
        populations[n // 5],
        populations[2 * n // 5],
        populations[3 * n // 5],
        populations[4 * n // 5],
    ] if n >= 5 else [10_000_000, 30_000_000, 70_000_000, 100_000_000]

    _population_cache = {"geojson": geojson, "breakpoints": breakpoints}
    return JSONResponse(content=_population_cache)


def _ray_cast(lat: float, lon: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]   # GeoJSON = [lon, lat]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _find_state(lat: float, lon: float, features: list) -> str:
    for f in features:
        name = (f.get("properties") or {}).get("_state_name", "")
        if not name:
            continue
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates", [])
        if geom.get("type") == "Polygon":
            if _ray_cast(lat, lon, coords[0]):
                return name
        elif geom.get("type") == "MultiPolygon":
            for poly in coords:
                if _ray_cast(lat, lon, poly[0]):
                    return name
    return ""


async def _ensure_state_features() -> list:
    """Fetch + normalise state features, reusing population cache if available."""
    global _population_cache
    if _population_cache is not None:
        return _population_cache["geojson"].get("features", [])
    # Fetch fresh without caching the full response
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(_STATE_GEOJSON_URL)
        r.raise_for_status()
        geojson = r.json()
    _state_pop_lower = {k.lower(): v for k, v in _STATE_POP.items()}
    for f in geojson.get("features", []):
        props = f.get("properties") or {}
        matched_name, matched_pop = "", 0
        for v in props.values():
            if not isinstance(v, str) or len(v) < 3:
                continue
            pop = _STATE_POP.get(v) or _state_pop_lower.get(v.lower(), 0)
            if pop:
                matched_name, matched_pop = v, pop
                break
        props["_population"] = matched_pop
        props["_state_name"] = matched_name
    return geojson.get("features", [])


_pincode_enriched_cache: dict | None = None


def _sync_enrich_need_scores(pincode_data: dict, state_features: list) -> dict:
    """
    Tag each PIN with a need_score = log(1 + density_ratio) × coverage_gap.

    density_ratio  = state_density / national_average (382 people/km²)
    coverage_gap   = fraction of the 4 services that are red (0–1)

    Effect: a PIN in Delhi missing emergency care scores ~30× higher than
    the same gap in Arunachal Pradesh — because the Delhi gap affects far
    more people per km². Sparse mountain areas with no services stay near 0.
    """
    import copy
    data = copy.deepcopy(pincode_data)

    SERVICES = ["oncology", "emergency", "trauma", "dialysis"]

    # State → density lookup
    _density: dict[str, float] = {}
    for state, pop in _STATE_POP.items():
        area = _STATE_AREA_KM2.get(state, 0.0)
        if area > 0:
            _density[state] = pop / area

    assigned = 0
    for pin in data["pincodes"]:
        coverage_gap = sum(
            1 for s in SERVICES if pin["services"].get(s) == "red"
        ) / len(SERVICES)

        state = _find_state(pin["lat"], pin["lon"], state_features)
        density = _density.get(state, _NATIONAL_DENSITY)
        density_ratio = density / _NATIONAL_DENSITY
        # log-dampen so outliers (Delhi ~30×) don't drown everything else
        pin["need_score"] = round(math.log1p(density_ratio) * coverage_gap, 4)
        pin["state"] = state
        if state:
            assigned += 1

    print(f"[pincodes] need scores computed — {assigned}/{len(data['pincodes'])} PINs assigned to a state")
    return data


_analysis_cache: dict | None = None


def _sync_analysis(pincode_data: dict, state_features: list) -> dict:
    from collections import defaultdict
    SERVICES = ["emergency", "oncology", "trauma", "dialysis"]

    state_stats: dict[str, dict] = defaultdict(lambda: {
        "total": 0,
        **{f"{s}_{st}": 0 for s in SERVICES for st in ("green", "yellow", "red")},
    })

    for pin in pincode_data["pincodes"]:
        state = _find_state(pin["lat"], pin["lon"], state_features)
        if not state:
            continue
        st = state_stats[state]
        st["total"] += 1
        for svc in SERVICES:
            status = pin["services"].get(svc, "red")
            st[f"{svc}_{status}"] += 1

    results = []
    for state, st in state_stats.items():
        total = st["total"]
        if total == 0:
            continue
        pop = _STATE_POP.get(state, 0)
        if not pop:
            pop_lower = {k.lower(): v for k, v in _STATE_POP.items()}
            pop = pop_lower.get(state.lower(), 0)

        em_red_pct  = st["emergency_red"]  / total
        em_green    = st["emergency_green"]
        criticality = pop * em_red_pct

        results.append({
            "state":            state,
            "population":       pop,
            "pop_millions":     round(pop / 1_000_000, 1),
            "total_pincodes":   total,
            "emergency": {
                "green":    em_green,
                "yellow":   st["emergency_yellow"],
                "red":      st["emergency_red"],
                "red_pct":  round(em_red_pct * 100, 1),
            },
            "other_gaps": {
                "oncology_red_pct":  round(st["oncology_red"]  / total * 100, 1),
                "trauma_red_pct":    round(st["trauma_red"]    / total * 100, 1),
                "dialysis_red_pct":  round(st["dialysis_red"]  / total * 100, 1),
            },
            "criticality_score": int(criticality),
        })

    results.sort(key=lambda x: x["criticality_score"], reverse=True)
    pop_at_risk = sum(r["population"] for r in results[:10] if r["emergency"]["red_pct"] > 70)

    return {
        "regions": results[:20],
        "summary": {
            "states_analysed":       len(results),
            "total_pincodes":        sum(r["total_pincodes"] for r in results),
            "population_at_risk":    pop_at_risk,
            "pop_at_risk_millions":  round(pop_at_risk / 1_000_000, 1),
        },
    }


@app.get("/analysis/critical")
async def critical_regions():
    global _analysis_cache
    if _analysis_cache is not None:
        return JSONResponse(content=_analysis_cache)

    loop = asyncio.get_event_loop()
    pincode_data, state_features = await asyncio.gather(
        loop.run_in_executor(None, get_pincode_grid),
        _ensure_state_features(),
    )

    print(f"[analysis] {len(pincode_data['pincodes'])} PINs × {len(state_features)} states")
    _analysis_cache = await loop.run_in_executor(
        None, _sync_analysis, pincode_data, state_features
    )
    print(f"[analysis] done — top state: {_analysis_cache['regions'][0]['state'] if _analysis_cache['regions'] else 'none'}")
    return JSONResponse(content=_analysis_cache)


@app.get("/health")
async def health():
    return {"status": "ok"}
