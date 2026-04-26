import asyncio
import json
import os
from dataclasses import dataclass

from openai import AsyncOpenAI
from tavily import AsyncTavilyClient

_tavily: AsyncTavilyClient | None = None
_openai: AsyncOpenAI | None = None

TAVILY_TIMEOUT = 5.0  # seconds total for extract call


def _get_tavily() -> AsyncTavilyClient:
    global _tavily
    if _tavily is None:
        _tavily = AsyncTavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    return _tavily


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(
            api_key=os.environ["XAI_API_KEY"],
            base_url="https://api.x.ai/v1",
        )
    return _openai


@dataclass
class VerificationResult:
    verified: bool
    trust_delta: int  # +10, 0, or -5
    red_flags: list[str]


async def _extract_page(url: str) -> str | None:
    """Fetch page text via Tavily Extract. Returns None on failure."""
    try:
        result = await asyncio.wait_for(
            _get_tavily().extract(urls=[url]),
            timeout=TAVILY_TIMEOUT,
        )
        results = result.get("results", [])
        if results:
            return results[0].get("raw_content", "")
        return None
    except Exception:
        return None


async def _llm_verify(page_text: str, provider_name: str, phone: str, city: str) -> VerificationResult:
    """Ask LLM to inspect page content for trust signals and red flags."""
    prompt = f"""You are auditing a healthcare provider's website for trustworthiness.

Provider record:
- Name: {provider_name}
- Phone: {phone}
- City: {city}

Website content (extracted text):
---
{page_text[:3000]}
---

Evaluate this page and return a JSON object with exactly these fields:
{{
  "verified": true/false,  // true if name+phone/address appear to match
  "trust_delta": 10 or 0 or -5,  // +10 if clearly legitimate, 0 if neutral/unclear, -5 if red flags found
  "red_flags": []  // list of specific issues found (empty if none)
}}

Red flags to look for:
- Placeholder images/videos (e.g. "lorem ipsum", "image coming soon", generic stock photos mentioned)
- Location clearly doesn't match the city in the record
- Phone number on page doesn't match the record phone
- Page is entirely generic template with no real clinic-specific info
- Suspicious content (fake reviews, misleading claims)

Return ONLY the JSON object, no other text."""

    try:
        response = await _get_openai().chat.completions.create(
            model="grok-3",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        return VerificationResult(
            verified=bool(data.get("verified", False)),
            trust_delta=int(data.get("trust_delta", 0)),
            red_flags=list(data.get("red_flags", [])),
        )
    except Exception:
        # Malformed response: treat as unverified, no delta
        return VerificationResult(verified=False, trust_delta=0, red_flags=[])


async def verify_provider(
    url: str, provider_name: str, phone: str, city: str
) -> VerificationResult:
    """Full verification pipeline: Tavily extract → LLM audit."""
    if not url:
        return VerificationResult(verified=False, trust_delta=0, red_flags=[])

    page_text = await _extract_page(url)
    if not page_text:
        return VerificationResult(verified=False, trust_delta=0, red_flags=[])

    return await _llm_verify(page_text, provider_name, phone, city)


async def verify_providers_parallel(
    providers: list[tuple[str, str, str, str]],  # (url, name, phone, city)
) -> list[VerificationResult]:
    """Verify up to 3 providers concurrently."""
    tasks = [verify_provider(url, name, phone, city) for url, name, phone, city in providers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [
        r if isinstance(r, VerificationResult) else VerificationResult(False, 0, [])
        for r in results
    ]
