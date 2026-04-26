"""
Offline script: compute trust scores for all providers in the dataset.
Run once before demo: python pre_compute/trust.py --csv data/providers.csv --out backend/data/trust.json
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import pandas as pd

AGGREGATOR_DOMAINS = {
    "justdial.com", "practo.com", "indiamart.com", "facebook.com",
    "sulekha.com", "lybrate.com", "myupchar.com", "apolloa.com",
    "1mg.com", "netmeds.com", "healthgrades.com", "doctorspring.com",
    "docplexus.in", "credihealth.com", "vaidam.com", "wockhardt.com",
    "instagram.com", "twitter.com", "linkedin.com", "youtube.com",
}

PHONE_RE = re.compile(r"^\+?91\d{10}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def provider_id(name: str, phone: str) -> str:
    raw = f"{(name or '').strip()}{(phone or '').strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def is_aggregator(url: str) -> bool:
    if not url:
        return True
    url_lower = url.lower()
    return any(domain in url_lower for domain in AGGREGATOR_DOMAINS)


def parse_json_list(val) -> list:
    if not val or pd.isna(val):
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def compute_trust_score(row: dict, phone_counts: dict[str, int]) -> tuple[int, list[str], list[str]]:
    """Returns (score, signals_list, penalties_list). Score clamped to [0, 100]."""
    score = 0
    signals: list[str] = []
    penalties: list[str] = []

    phone = str(row.get("officialPhone") or "").strip().replace(" ", "").replace("-", "")

    # Valid Indian phone (+91 + 10 digits)
    if PHONE_RE.match(phone if phone.startswith("+") else f"+91{phone[-10:]}" if len(phone) >= 10 else ""):
        score += 15
        signals.append("Valid Indian phone number")
    elif phone:
        penalties.append("Phone number format invalid")

    # Phone not shared with >3 other providers
    if phone and phone_counts.get(phone, 0) <= 3:
        score += 10
        signals.append("Phone not shared with multiple providers")
    elif phone:
        penalties.append("Phone shared across multiple listings (aggregator artifact)")

    # Non-aggregator official website
    website = str(row.get("officialWebsite") or "").strip()
    if website and not is_aggregator(website):
        score += 15
        signals.append("Has own domain (not aggregator)")
    elif website:
        penalties.append("Website is aggregator page only")

    # Valid email
    email = str(row.get("email") or "").strip()
    if EMAIL_RE.match(email):
        score += 5
        signals.append("Valid email address")

    # Description: present, not boilerplate (≥50 chars, not all-caps)
    desc = str(row.get("description") or "").strip()
    if desc and len(desc) >= 50 and not desc.isupper():
        score += 10
        signals.append("Has substantive description")

    # Affiliated staff presence
    if str(row.get("affiliated_staff_presence") or "").upper() in ("TRUE", "1", "YES"):
        score += 15
        signals.append("Staff profiles present")

    # Custom logo
    if str(row.get("custom_logo_presence") or "").upper() in ("TRUE", "1", "YES"):
        score += 10
        signals.append("Custom logo (not placeholder)")

    # Recency: page updated within 12 months
    recency = str(row.get("recency_of_page_update") or "").strip()
    if recency and recency not in ("", "None", "nan"):
        try:
            import datetime
            updated = pd.to_datetime(recency, errors="coerce")
            if pd.notna(updated):
                cutoff = pd.Timestamp.now() - pd.DateOffset(months=12)
                if updated >= cutoff:
                    score += 10
                    signals.append("Listing updated within 12 months")
                else:
                    penalties.append("Listing may be outdated (>12 months old)")
        except Exception:
            pass

    # Clinical depth: ≥2 capabilities or procedures
    caps = parse_json_list(row.get("capability"))
    procs = parse_json_list(row.get("procedure"))
    if len(caps) + len(procs) >= 2:
        score += 10
        signals.append("Clinical capabilities listed")
    else:
        penalties.append("Limited clinical detail in listing")

    return min(score, 100), signals, penalties


def compute_all(csv_path: str, out_path: str) -> None:
    df = pd.read_csv(csv_path, low_memory=False)
    print(f"Loaded {len(df)} providers")

    # Phone share counts (aggregator detection)
    phones = df["officialPhone"].astype(str).str.strip().str.replace(r"[\s\-]", "", regex=True)
    phone_counts = phones.value_counts().to_dict()

    trust_data: dict[str, dict] = {}
    for _, row in df.iterrows():
        pid = provider_id(str(row.get("name") or ""), str(row.get("officialPhone") or ""))
        score, sigs, pens = compute_trust_score(row.to_dict(), phone_counts)
        trust_data[pid] = {
            "score": score,
            "signals": sigs,
            "penalties": pens,
        }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(trust_data, f)
    print(f"Trust scores written to {out_path} ({len(trust_data)} entries)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out", default="backend/data/trust.json")
    args = parser.parse_args()
    compute_all(args.csv, args.out)
