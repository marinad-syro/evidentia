import pytest
from unittest.mock import AsyncMock, patch

from backend.api.tavily_verify import verify_provider, VerificationResult


@pytest.mark.asyncio
async def test_no_url_returns_unverified():
    result = await verify_provider("", "Test Hospital", "+91999", "Bangalore")
    assert result.verified is False
    assert result.trust_delta == 0
    assert result.red_flags == []


@pytest.mark.asyncio
async def test_extract_failure_returns_unverified():
    with patch("backend.api.tavily_verify._extract_page", return_value=None):
        result = await verify_provider("https://example.com", "Test Hospital", "+91999", "Bangalore")
    assert result.verified is False
    assert result.trust_delta == 0


@pytest.mark.asyncio
async def test_verified_positive_delta():
    with patch("backend.api.tavily_verify._extract_page", return_value="Test Hospital is located in Bangalore. Phone: +91999."):
        with patch("backend.api.tavily_verify._llm_verify", return_value=VerificationResult(
            verified=True, trust_delta=10, red_flags=[]
        )):
            result = await verify_provider("https://example.com", "Test Hospital", "+91999", "Bangalore")
    assert result.verified is True
    assert result.trust_delta == 10


@pytest.mark.asyncio
async def test_red_flags_negative_delta():
    with patch("backend.api.tavily_verify._extract_page", return_value="Lorem ipsum dolor sit amet placeholder"):
        with patch("backend.api.tavily_verify._llm_verify", return_value=VerificationResult(
            verified=False, trust_delta=-5, red_flags=["Placeholder content found"]
        )):
            result = await verify_provider("https://example.com", "Ghost Clinic", "+91000", "Mumbai")
    assert result.trust_delta == -5
    assert len(result.red_flags) > 0


@pytest.mark.asyncio
async def test_parallel_verification_handles_exceptions():
    from backend.api.tavily_verify import verify_providers_parallel

    inputs = [
        ("", "Provider A", "+91111", "Chennai"),
        ("https://good.com", "Provider B", "+91222", "Delhi"),
        ("https://bad.com", "Provider C", "+91333", "Kolkata"),
    ]

    async def mock_verify(url, name, phone, city):
        if url == "":
            return VerificationResult(False, 0, [])
        if url == "https://good.com":
            return VerificationResult(True, 10, [])
        raise RuntimeError("Simulated network failure")

    with patch("backend.api.tavily_verify.verify_provider", side_effect=mock_verify):
        results = await verify_providers_parallel(inputs)

    assert len(results) == 3
    assert results[0].verified is False
    assert results[1].verified is True
    # exception falls back to unverified
    assert results[2].verified is False
    assert results[2].trust_delta == 0
