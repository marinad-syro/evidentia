# Healthcare Provider Finder

AI-powered provider search for India. Enter a plain-language health query — get ranked, verified providers near you with live trust scoring and a streaming progress feed.

## Setup

### 1. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Set API keys

```bash
cp .env.example .env
# Fill in OPENAI_API_KEY and TAVILY_API_KEY
```

### 3. Pre-compute embeddings and trust scores (run once)

You need a CSV with provider data (columns: name, officialPhone, officialWebsite, email, specialties, procedure, capability, description, latitude, longitude, address_city, etc.).

```bash
# From the project root
python pre_compute/trust.py --csv data/providers.csv --out backend/data/trust.json

python pre_compute/embed.py \
  --csv data/providers.csv \
  --out-faiss backend/data/embeddings.faiss \
  --out-parquet backend/data/providers.parquet \
  --model text-embedding-3-small
```

To use a free local embedding model instead (no OpenAI cost):
```bash
pip install sentence-transformers
python pre_compute/embed.py --csv providers.csv --model all-MiniLM-L6-v2
```

### 4. Start the backend

```bash
uvicorn backend.main:app --reload --port 8000
```

### 5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Running tests

**Backend:**
```bash
cd backend
pip install -r requirements-dev.txt
pytest tests/
```

**Frontend:**
```bash
cd frontend
npm test
```

## Architecture

```
Query → Intent extraction (LLM)
      → Specialty resolution (lookup table + LLM fallback)
      → Geocoding (Nominatim)
      → FAISS semantic search (top 200)
      → Post-filter by specialty + haversine radius
      → Trust scoring (precomputed offline)
      → Tavily Extract verification (top 3, parallel)
      → LLM red-flag analysis
      → Card generation (batched LLM)
      → SSE stream to frontend
```

Each step yields a Server-Sent Event so the frontend can show a live progress feed as the pipeline runs.
