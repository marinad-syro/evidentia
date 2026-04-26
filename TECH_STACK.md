# Evidentia — Tech Stack

AI-powered healthcare provider finder for India. Accepts natural language queries, finds and ranks verified providers, and visualises coverage gaps across India.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Frontend](#frontend)
3. [Backend](#backend)
4. [Databricks Integration](#databricks-integration)
5. [Search Pipeline](#search-pipeline)
6. [Data & Pre-compute](#data--pre-compute)
7. [Medical Desert Map](#medical-desert-map)
8. [External Services](#external-services)
9. [Datasets Used](#datasets-used)
10. [Key Algorithms](#key-algorithms)
11. [Environment Variables](#environment-variables)

---

## Architecture Overview

```
Browser
  ├── Text search → GET /search (Server-Sent Events)
  ├── Voice search → WebSocket /ws/voice
  └── Desert map  → GET /deserts/pincodes + GET /population

FastAPI Backend (port 8000)
  ├── FAISS index (semantic candidate retrieval)
  ├── Databricks SQL (geographic + specialty filtering)
  ├── xAI Grok-3 (intent extraction, ranking, card generation)
  ├── Tavily (live website verification)
  └── Nominatim (geocoding)

Data Layer
  ├── providers.parquet (10,000 providers)
  ├── embeddings.faiss (384-dim vectors)
  └── trust.json (pre-computed trust scores)
```

---

## Frontend

**Framework:** React 18 + TypeScript 5, built with Vite 5

**Key libraries:**

| Library | Version | Purpose |
|---|---|---|
| react-leaflet | 4.2.1 | Interactive maps (v4 required for React 18 compatibility) |
| leaflet | 1.9.4 | Map engine |
| vitest | 1.6 | Unit testing |
| @testing-library/react | 16 | Component testing |

**Components:**

| File | What it does |
|---|---|
| `App.tsx` | Root — manages mode (`text / voice / deserts`), geolocation, SSE stream |
| `SearchBar.tsx` | Query input |
| `ProgressFeed.tsx` | Live step status (intent → geo → filter → rank → trust) |
| `ProviderCard.tsx` | Provider detail card with trust signals, mini-map, red flags |
| `MapView.tsx` | Leaflet map with trust-scored pins + scrollable sidebar |
| `DesertMap.tsx` | PIN code coverage map + population density choropleth |
| `VoiceInterface.tsx` | WebSocket audio client for xAI voice |

**Vite proxy:** All `/search`, `/deserts*`, `/population`, `/analysis`, `/ws` routes proxied to `localhost:8000` in dev.

---

## Backend

**Framework:** FastAPI + Uvicorn (async, ASGI)

**Dependencies:**

| Package | Version | Purpose |
|---|---|---|
| fastapi | ≥0.111 | Web framework |
| uvicorn[standard] | ≥0.29 | ASGI server |
| databricks-sql-connector | ≥3.0 | Databricks Delta table access |
| faiss-cpu | ≥1.8 | Vector similarity search |
| sentence-transformers | ≥3.0 | Local text embeddings |
| pandas | ≥2.2 | Local data filtering fallback |
| pyarrow | ≥16 | Parquet read |
| openai | ≥1.30 | xAI Grok API client (OpenAI-compatible) |
| tavily-python | ≥0.3.3 | Website extraction |
| httpx | ≥0.27 | Async HTTP (state GeoJSON fetch) |
| geopy | ≥2.4 | Nominatim geocoding |
| numpy | ≥1.26 | Desert grid computation |
| websockets | ≥12 | Voice relay to xAI |
| python-dotenv | ≥1.0 | Environment config |

**API endpoints:**

| Method | Path | Response | Purpose |
|---|---|---|---|
| GET | `/search` | SSE stream | Full provider search pipeline |
| WS | `/ws/voice` | Audio + JSON | Voice interface via xAI |
| GET | `/deserts` | JSON | 0.5° grid desert cells |
| GET | `/deserts/pincodes` | JSON | PIN code service coverage |
| GET | `/population` | GeoJSON | State population choropleth |
| GET | `/analysis/critical` | JSON | Ranked critical regions |
| GET | `/health` | JSON | Health check |

---

## Databricks Integration

**File:** `backend/api/databricks_client.py`

The provider dataset lives in a Delta table on Databricks. During a search, after FAISS retrieves candidate provider IDs, those IDs are passed to Databricks for geographic and specialty filtering. The heavy computation (Haversine distance, LIKE matching) runs inside the SQL warehouse — not on the FastAPI server.

### Connection

```python
from databricks import sql

sql.connect(
    server_hostname=os.environ["DATABRICKS_HOST"],
    http_path=os.environ["DATABRICKS_HTTP_PATH"],
    access_token=os.environ["DATABRICKS_TOKEN"],
)
```

Table is resolved from three env vars:
- `DATABRICKS_CATALOG` (default: `hive_metastore`)
- `DATABRICKS_SCHEMA` (default: `default`)
- `DATABRICKS_TABLE` (default: `providers`)

### Query

A single parameterised SQL query does three things simultaneously:

```sql
SELECT *,
    ROUND(
      2 * 6371 * ASIN(SQRT(
        POWER(SIN(RADIANS(latitude - ?) / 2), 2) +
        COS(RADIANS(?)) * COS(RADIANS(latitude)) *
        POWER(SIN(RADIANS(longitude - ?) / 2), 2)
      )), 2
    ) AS _distance_km
FROM `catalog`.`schema`.`providers`
WHERE provider_id IN (?, ?, ...)          -- candidates from FAISS
  AND LOWER(COALESCE(specialties, '')) LIKE ?  -- specialty filter
  AND (haversine expression) <= ?         -- radius filter
  AND latitude  IS NOT NULL AND latitude  != 0
  AND longitude IS NOT NULL AND longitude != 0
ORDER BY _distance_km
```

Parameters use `?` placeholders (not `%s`) — required by the Databricks SQL Connector.

### Fallback

The async wrapper applies a 12-second timeout. If the SQL warehouse is cold-starting (can take 30–60 seconds when idle), the query times out and a local pandas filter runs instead against the in-memory `providers.parquet`. The log line shows which path ran:

```
[filter] Databricks SQL — sent 200, matched 14, radius 10km
[filter] local fallback — sent 200, matched 14, radius 10km
```

### Why Databricks

The hackathon required use of Databricks for data processing. Beyond compliance, it offloads the Haversine calculation (computed per-row in SQL) onto the warehouse, returning a pre-sorted result set rather than loading thousands of rows into memory.

---

## Search Pipeline

Full flow from query to streamed results:

```
1. INTENT EXTRACTION
   Model: xAI Grok-3 (via OpenAI-compatible API)
   Input: raw user query
   Output: { specialty_description, location, preference }
   Config: max_tokens=100, temperature=0, json_object format

2. SPECIALTY RESOLUTION
   First: 88-entry lookup table (e.g. "eye doctor" → "ophthalmology")
   Fallback: Grok-3 matches description against 560 known specialty IDs from dataset

3. GEOCODING
   Provider: Nominatim (OpenStreetMap) via geopy
   Cache: LRU (512 entries)
   Note: "India" appended to all queries
   Skipped if user GPS coordinates provided directly

4. FAISS SEMANTIC SEARCH
   Model: all-MiniLM-L6-v2 (384-dim, runs locally)
   Index: IndexFlatIP with L2 normalisation (cosine similarity)
   Returns: top 200 candidate provider IDs

5. DATABRICKS SQL FILTERING
   Input: 200 candidate IDs + specialty + lat/lon + radius
   Output: (provider_dict, distance_km) tuples, ordered by distance
   Timeout: 12s → pandas fallback
   Radius expansion: 10km → 25km → 50km if no results

6. COMPOSITE RANKING
   Score = 0.6 × (trust_score / 100) + 0.4 × (1 − min(dist, 50) / 50)
   Takes top 25 by score

7. LIVE VERIFICATION (top 3 only)
   Tavily Extract: fetches provider website text
   Grok-3 audit: checks for red flags (placeholder images, fake reviews,
   location mismatch, generic templates)
   Trust delta: +10 (clearly legitimate) / 0 (unclear) / −5 (red flags)

8. CARD GENERATION
   Grok-3 writes a "why this one" sentence per provider
   Rule-based caveats: 1-doctor clinic, no staff profiles, outdated listing

9. SSE STREAM
   Format: text/event-stream
   Events: step (id, status, text, detail) + results (final JSON)
   Final payload: top ≤3 providers with full trust signal breakdown
```

---

## Data & Pre-compute

### `pre_compute/embed.py`

Reads the provider CSV, constructs a text representation per provider (name + specialties + procedures + capabilities + description, capped at 2000 chars), embeds with `all-MiniLM-L6-v2`, and writes:
- `backend/data/embeddings.faiss` — FAISS index (15.4 MB)
- `backend/data/providers.parquet` — full dataset (4.7 MB)

### `pre_compute/trust.py`

Rule-based trust scorer. Reads CSV, scores each provider, writes `backend/data/trust.json` (2.6 MB).

**Scoring signals (add points):**

| Signal | Column | Points |
|---|---|---|
| Valid Indian phone (+91 + 10 digits) | `officialPhone` | +15 |
| Phone unique to this provider (≤3 listings) | `officialPhone` | +10 |
| Own website, not a directory | `officialWebsite` | +15 |
| Valid email format | `email` | +5 |
| Description ≥50 chars, not boilerplate | `description` | +10 |
| Staff profiles listed | `affiliated_staff_presence` | +15 |
| Real logo (not generic placeholder) | `custom_logo_presence` | +10 |
| Listing updated within 12 months | `recency_of_page_update` | +10 |
| ≥2 capabilities or procedures | `capability` | +10 |

**Aggregator domains blocked from scoring as "own website":** JustDial, Practo, IndiaMART, Facebook, Sulekha, Lybrate, MyUpchar, Apollo, 1mg, Netmeds, HealthGrades, DocPlexus, CrediHealth, Vaidam, Instagram, Twitter, LinkedIn, YouTube.

Each signal stores the column name and spreadsheet row number so it can be traced back to the source CSV directly.

---

## Medical Desert Map

### How it works

Two complementary views:

**PIN code service map (`/deserts/pincodes`)**

Groups all 10,000 providers by their `address_zipOrPostcode` (Indian 6-digit PIN codes). For each PIN × service (oncology / emergency / trauma / dialysis):

- **Green** — ≥1 provider in that PIN has the service AND trust ≥ 65
- **Yellow** — provider claims the service but all have trust < 65
- **Red** — no provider in this PIN offers this service

Service detection checks three fields per provider: `specialties` (JSON list of IDs), `capability` (free text list), `procedure` (free text list). Keyword matching:

| Service | Specialty keywords | Text keywords |
|---|---|---|
| Oncology | `oncology` | `oncolog` |
| Emergency | `emergency` | `emergency` |
| Trauma | `trauma` | `trauma` |
| Dialysis | *(none in dataset)* | `dialysis` |

**Population density overlay (`/population`)**

Fetches India state boundary GeoJSON from `geohacker/india` on GitHub. Joins with embedded Census 2011 state population data. Colours states on a yellow→orange→red scale (ColorBrewer YlOrRd, 5 quintiles) behind the PIN dots. Choropleth only loads when toggled.

**Critical regions analysis (`/analysis/critical`)**

Point-in-polygon (ray-casting) assigns each PIN centroid to a state. Per state:

```
criticality_score = state_population × (emergency_red_pincodes / total_pincodes)
```

States ranked descending. A state with 200M people and 87% red PINs scores higher than one with 5M people and 95% red — population weight is intentional.

---

## External Services

| Service | What we use it for | Model / API |
|---|---|---|
| **xAI Grok** | Intent extraction, specialty resolution, provider card generation, live verification audit | `grok-3` (chat), `grok-voice-think-fast-1.0` (voice) |
| **Tavily** | Extract website text for live verification | `AsyncTavilyClient` |
| **Nominatim** | Geocode location strings to lat/lon | OpenStreetMap, via geopy |
| **Databricks** | SQL filtering of provider Delta table | SQL Connector 3.0+, SQL warehouse |
| **OpenStreetMap** | Map tiles in frontend | Standard tile CDN |
| **geohacker/india GeoJSON** | India state boundary polygons for population overlay | GitHub raw file |

---

## Datasets Used

| Dataset | Source | How we use it |
|---|---|---|
| **India healthcare providers** | Hackathon-provided CSV (~10,000 providers) | Core provider database — loaded into FAISS, Databricks Delta table, and local parquet |
| **Census 2011 state populations** | Embedded directly (public domain, from census.gov.in) | Population density overlay on desert map; critical regions analysis |
| **India state boundaries GeoJSON** | `github.com/geohacker/india` (open, CC) | State choropleth layer; PIN-to-state spatial join for analysis |

**Provider CSV columns used:**

| Column | Used for |
|---|---|
| `provider_id` | Primary key throughout |
| `name` | Display, embedding text |
| `specialties` | Specialty matching, desert map classification |
| `capability`, `procedure` | Clinical depth scoring, desert map service detection |
| `officialPhone` | Trust scoring |
| `officialWebsite` | Trust scoring, live verification |
| `email` | Trust scoring |
| `description` | Trust scoring, embedding text |
| `affiliated_staff_presence` | Trust scoring |
| `custom_logo_presence` | Trust scoring |
| `recency_of_page_update` | Trust scoring |
| `latitude`, `longitude` | Haversine distance, map display, desert grid |
| `address_zipOrPostcode` | PIN code grouping for desert map |
| `address_city` | Display |
| `facilityTypeId` | Display (clinic / hospital / pharmacy…) |
| `numberDoctors` | Caveat generation |
| `operatorTypeId` | Preference filter in Databricks query |

---

## Key Algorithms

**Cosine similarity (FAISS)**
Vectors L2-normalised before indexing; inner product = cosine similarity. Model `all-MiniLM-L6-v2` produces 384-dimensional embeddings.

**Haversine distance**
Great-circle distance implemented in both Python (ranking, desert grid) and SQL (Databricks WHERE clause):
```
d = 2R × arcsin(√(sin²(Δlat/2) + cos(lat1)×cos(lat2)×sin²(Δlon/2)))
R = 6371 km
```

**Composite provider ranking**
```
score = 0.6 × (trust / 100) + 0.4 × (1 − min(dist_km, 50) / 50)
```
Trust weighted 60%, proximity 40% (capped at 50 km so distant providers aren't penalised to zero).

**Desert grid (approximate haversine)**
For the 0.5° grid computation, uses `cos_lat ≈ cos(22°)` constant approximation (India's centre latitude) to avoid a full haversine per cell. Reduces computation from O(cells × providers) trigonometry to vectorised Euclidean distance — fast enough to run in-process without batching beyond chunking for RAM.

**Ray-casting point-in-polygon**
Assigns PIN code centroids to states. Fires a ray east from each point, counts edge crossings against state boundary polygon rings — odd = inside.

---

## Environment Variables

```bash
# xAI
XAI_API_KEY=

# Tavily
TAVILY_API_KEY=

# Databricks
DATABRICKS_HOST=
DATABRICKS_HTTP_PATH=
DATABRICKS_TOKEN=
DATABRICKS_CATALOG=hive_metastore   # optional
DATABRICKS_SCHEMA=default            # optional
DATABRICKS_TABLE=providers           # optional

# OpenAI (optional — only needed for OpenAI embeddings)
OPENAI_API_KEY=
```
