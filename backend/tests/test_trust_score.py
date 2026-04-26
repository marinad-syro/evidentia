import pytest
from pre_compute.trust import compute_trust_score, is_aggregator


def test_full_trust_score_clamped_to_100(sample_provider_row, phone_counts):
    score, signals, penalties = compute_trust_score(sample_provider_row, phone_counts)
    assert 0 <= score <= 100


def test_valid_phone_adds_signal(sample_provider_row, phone_counts):
    score, signals, _ = compute_trust_score(sample_provider_row, phone_counts)
    assert any("phone" in s.lower() for s in signals)


def test_aggregator_website_adds_penalty():
    row = {
        "officialPhone": "",
        "officialWebsite": "https://www.justdial.com/clinic",
        "email": "",
        "description": "",
        "affiliated_staff_presence": "",
        "custom_logo_presence": "",
        "recency_of_page_update": "",
        "capability": "[]",
        "procedure": "[]",
    }
    _, _, penalties = compute_trust_score(row, {})
    assert any("aggregator" in p.lower() for p in penalties)


def test_own_domain_adds_signal(sample_provider_row, phone_counts):
    _, signals, _ = compute_trust_score(sample_provider_row, phone_counts)
    assert any("domain" in s.lower() or "aggregator" in s.lower() for s in signals)


def test_is_aggregator_known_domains():
    assert is_aggregator("https://www.justdial.com/hospital/123")
    assert is_aggregator("https://practo.com/doctor/abc")
    assert not is_aggregator("https://cityeye.in")
    assert is_aggregator("")  # empty URL treated as aggregator


def test_score_zero_for_empty_row():
    row = {k: "" for k in [
        "officialPhone", "officialWebsite", "email", "description",
        "affiliated_staff_presence", "custom_logo_presence",
        "recency_of_page_update", "capability", "procedure",
    ]}
    score, _, _ = compute_trust_score(row, {})
    assert score == 0
