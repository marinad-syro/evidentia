"""
Offline script: embed all providers and build FAISS index.
Run once before demo:
  python pre_compute/embed.py --csv data/providers.csv \
    --out-faiss backend/data/embeddings.faiss \
    --out-parquet backend/data/providers.parquet \
    --model text-embedding-3-small  # or: all-MiniLM-L6-v2 (local)
"""
import argparse
import hashlib
import json
import pickle
import sys
from pathlib import Path

import faiss
import numpy as np
import pandas as pd


def provider_id(name: str, phone: str) -> str:
    raw = f"{(name or '').strip()}{(phone or '').strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def parse_json_list(val) -> list:
    if not val or (isinstance(val, float) and np.isnan(val)):
        return []
    if isinstance(val, list):
        return val
    try:
        return json.loads(val) if isinstance(val, str) else []
    except Exception:
        return []


def build_text(row: dict) -> str:
    parts = []
    if row.get("name"):
        parts.append(str(row["name"]))
    specialties = parse_json_list(row.get("specialties"))
    if specialties:
        parts.append(" ".join(specialties))
    procedures = parse_json_list(row.get("procedure"))
    if procedures:
        parts.append(" ".join(procedures[:10]))
    capabilities = parse_json_list(row.get("capability"))
    if capabilities:
        parts.append(" ".join(capabilities[:10]))
    desc = str(row.get("description") or "")[:500]
    if desc:
        parts.append(desc)
    return " ".join(parts)[:2000]  # ~512 tokens max


def embed_openai(texts: list[str], model: str) -> np.ndarray:
    from openai import OpenAI
    import os

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    all_embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(input=batch, model=model)
        embeddings = [e.embedding for e in sorted(response.data, key=lambda x: x.index)]
        all_embeddings.extend(embeddings)
        print(f"  Embedded {min(i + batch_size, len(texts))}/{len(texts)}", end="\r")
    print()
    return np.array(all_embeddings, dtype=np.float32)


def embed_local(texts: list[str], model_name: str) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=64)
    return np.array(embeddings, dtype=np.float32)


def run(csv_path: str, out_faiss: str, out_parquet: str, model: str) -> None:
    df = pd.read_csv(csv_path, low_memory=False)
    print(f"Loaded {len(df)} providers")

    # Add provider_id column
    df["provider_id"] = df.apply(
        lambda r: provider_id(str(r.get("name") or ""), str(r.get("officialPhone") or "")),
        axis=1,
    )

    texts = [build_text(r) for _, r in df.iterrows()]
    print(f"Building text representations...")

    use_local = model in ("all-MiniLM-L6-v2", "local")
    if use_local:
        print(f"Using local model: {model}")
        embeddings = embed_local(texts, model if model != "local" else "all-MiniLM-L6-v2")
    else:
        print(f"Using OpenAI model: {model}")
        embeddings = embed_openai(texts, model)

    dim = embeddings.shape[1]
    print(f"Embedding dimension: {dim}")

    # Normalise for cosine similarity (FAISS uses inner product after normalisation)
    faiss.normalize_L2(embeddings)
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    Path(out_faiss).parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, out_faiss)
    print(f"FAISS index saved to {out_faiss} ({index.ntotal} vectors)")

    # Save parquet with provider_ids aligned to FAISS index positions
    df.to_parquet(out_parquet, index=False)
    print(f"Provider parquet saved to {out_parquet}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out-faiss", default="backend/data/embeddings.faiss")
    parser.add_argument("--out-parquet", default="backend/data/providers.parquet")
    parser.add_argument("--model", default="text-embedding-3-small",
                        help="OpenAI model name or 'all-MiniLM-L6-v2' for local")
    args = parser.parse_args()
    run(args.csv, args.out_faiss, args.out_parquet, args.model)
