# TODOS

## Post-demo features

### Informational KB ("What is glaucoma?")
**What:** Add a second pipeline path that routes informational health questions to a document retrieval system (RAG over curated medical docs), separate from the provider search path. An intent classifier at Step 1 routes "what is X" → KB, "find me a provider" → search.
**Why:** Handles the 30-40% of queries that are informational rather than directional. Without it, the assistant returns an error or unhelpful redirect for common health questions.
**Where to start:** `api/intent_router.py` — add a two-class classifier (informational vs. directional). Then add `api/kb_search.py` with a FAISS index over the general healthcare document corpus.
**Depends on:** Curated healthcare document corpus (not yet in repo).

### Map view for provider cards
**What:** Add a map embed (Leaflet.js recommended — free, no API key) showing provider pin locations relative to the user's searched location. Display as a panel above or beside the card list.
**Why:** "2.1 km" is less intuitive than seeing two pins on a map. Visual geography reduces cognitive load and increases trust in the distance signal.
**Where to start:** `frontend/src/components/MapView.tsx`. Provider lat/lon is already in the dataset — pass it through the SSE `results` payload.
**Depends on:** Nothing blocked. Can be added post-hackathon in a few hours.
