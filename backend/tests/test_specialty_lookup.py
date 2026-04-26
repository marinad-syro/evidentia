import pytest
from unittest.mock import AsyncMock, patch

from backend.api.specialty import resolve_specialty, SPECIALTY_LOOKUP


@pytest.mark.asyncio
async def test_lookup_table_eye_doctor():
    known = {"ophthalmology", "cardiology"}
    specialty_id, label = await resolve_specialty("eye doctor", known)
    assert specialty_id == "ophthalmology"


@pytest.mark.asyncio
async def test_lookup_table_heart_specialist():
    known = {"ophthalmology", "cardiology"}
    specialty_id, label = await resolve_specialty("heart specialist", known)
    assert specialty_id == "cardiology"


@pytest.mark.asyncio
async def test_lookup_table_case_insensitive():
    known = {"ophthalmology"}
    specialty_id, _ = await resolve_specialty("Eye Doctor", known)
    assert specialty_id == "ophthalmology"


@pytest.mark.asyncio
async def test_unknown_specialty_raises_with_llm_fallback_failing():
    """When lookup misses and LLM returns a specialty not in known IDs, raise ValueError."""
    known = {"ophthalmology"}
    with patch("backend.api.specialty._get_openai") as mock_openai:
        mock_client = AsyncMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content='{"specialty_id": "xyzzy_fake"}'))]
        ))
        with pytest.raises(ValueError, match="could not map"):
            await resolve_specialty("quantum healing", known)


@pytest.mark.asyncio
async def test_lookup_table_has_reasonable_coverage():
    assert "ophthalmology" in SPECIALTY_LOOKUP.values()
    assert "cardiology" in SPECIALTY_LOOKUP.values()
    assert "pediatrics" in SPECIALTY_LOOKUP.values()
    assert len(SPECIALTY_LOOKUP) >= 20
