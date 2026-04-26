import os
import json
from openai import AsyncOpenAI

# Lookup table: common user phrases → dataset specialty IDs (camelCase)
SPECIALTY_LOOKUP: dict[str, str] = {
    "eye doctor": "ophthalmology",
    "eye specialist": "ophthalmology",
    "ophthalmologist": "ophthalmology",
    "optometrist": "optometry",
    "optometry": "optometry",
    "skin doctor": "dermatology",
    "skin specialist": "dermatology",
    "dermatologist": "dermatology",
    "kids doctor": "pediatrics",
    "child doctor": "pediatrics",
    "pediatrician": "pediatrics",
    "pediatrics": "pediatrics",
    "heart doctor": "cardiology",
    "cardiologist": "cardiology",
    "cardiology": "cardiology",
    "bone doctor": "orthopedics",
    "orthopedic": "orthopedics",
    "orthopaedic": "orthopedics",
    "joint doctor": "orthopedics",
    "brain doctor": "neurology",
    "neurologist": "neurology",
    "neurology": "neurology",
    "general doctor": "generalPractice",
    "general physician": "generalPractice",
    "gp": "generalPractice",
    "family doctor": "generalPractice",
    "dentist": "dentistry",
    "dental": "dentistry",
    "teeth doctor": "dentistry",
    "gynecologist": "gynecology",
    "gynaecologist": "gynecology",
    "women doctor": "gynecology",
    "ob gyn": "gynecologyAndObstetrics",
    "obstetrician": "gynecologyAndObstetrics",
    "psychiatrist": "psychiatry",
    "mental health": "psychiatry",
    "psychologist": "psychology",
    "ent": "entSpecialist",
    "ear nose throat": "entSpecialist",
    "ear doctor": "entSpecialist",
    "kidney doctor": "nephrology",
    "nephrologist": "nephrology",
    "liver doctor": "gastroenterology",
    "stomach doctor": "gastroenterology",
    "gastroenterologist": "gastroenterology",
    "lung doctor": "pulmonology",
    "chest doctor": "pulmonology",
    "pulmonologist": "pulmonology",
    "cancer doctor": "oncology",
    "oncologist": "oncology",
    "surgeon": "generalSurgery",
    "surgery": "generalSurgery",
    "urology": "urology",
    "urologist": "urology",
    "kidney stone": "urology",
    "burning urination": "urology",
    "physiotherapist": "physiotherapy",
    "physio": "physiotherapy",
    "physiotherapy": "physiotherapy",
    "dietitian": "dietAndNutrition",
    "nutritionist": "dietAndNutrition",
    "diabetes doctor": "endocrinology",
    "endocrinologist": "endocrinology",
    "thyroid doctor": "endocrinology",
    "allergy doctor": "allergy",
    "allergist": "allergy",
    "rheumatologist": "rheumatology",
    "arthritis doctor": "rheumatology",
    "radiologist": "radiology",
    "x-ray": "radiology",
    "scan": "radiology",
    "pathologist": "pathology",
    "blood test": "pathology",
    "laboratory": "pathology",
    "emergency": "emergencyMedicine",
    "icu": "intensiveCare",
    "anesthesiologist": "anesthesiology",
    "plastic surgeon": "plasticSurgery",
    "cosmetic surgery": "plasticSurgery",
    "lasik": "ophthalmology",
    "cataract": "ophthalmology",
}

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ["XAI_API_KEY"],
            base_url="https://api.x.ai/v1",
        )
    return _client


async def resolve_specialty(query: str, known_specialty_ids: set[str]) -> tuple[str, str]:
    """
    Returns (specialty_id, human_readable_label).
    Raises ValueError if specialty cannot be determined.
    """
    normalized = query.lower().strip()

    # Exact lookup table match
    for phrase, specialty_id in SPECIALTY_LOOKUP.items():
        if phrase in normalized:
            if specialty_id in known_specialty_ids:
                return specialty_id, phrase
            # camelCase variant might differ slightly — try case-insensitive match
            for sid in known_specialty_ids:
                if sid.lower() == specialty_id.lower():
                    return sid, phrase

    # LLM fallback: ask model to pick from known IDs
    id_list = sorted(known_specialty_ids)[:200]  # cap to avoid token overflow
    id_list_str = ", ".join(id_list)

    response = await _get_client().chat.completions.create(
        model="grok-3",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a medical specialty classifier. "
                    "Given a user's health query, return the single most relevant "
                    "specialty ID from the provided list. "
                    "Return ONLY the ID string, nothing else. "
                    "If no match exists, return null."
                ),
            },
            {
                "role": "user",
                "content": f"Query: {query}\n\nSpecialty IDs: {id_list_str}",
            },
        ],
        max_tokens=30,
        temperature=0,
    )

    raw = (response.choices[0].message.content or "").strip().strip('"').strip("'")

    if raw.lower() == "null" or not raw:
        raise ValueError(
            "I couldn't identify a specialty for that. "
            "Try: 'eye doctor', 'cardiologist', 'skin specialist'."
        )

    # Validate against known IDs (case-insensitive)
    matched_id = next(
        (sid for sid in known_specialty_ids if sid.lower() == raw.lower()), None
    )
    if not matched_id:
        raise ValueError(
            f"I interpreted that as '{raw}' but it's not in the dataset. "
            "Try: 'eye doctor', 'cardiologist', 'skin specialist'."
        )

    return matched_id, raw
