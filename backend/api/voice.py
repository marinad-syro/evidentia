import asyncio
import json
import os

import websockets
from fastapi import WebSocket, WebSocketDisconnect

SYSTEM_PROMPT = (
    "You are a warm, concise healthcare assistant for India. "
    "When the user describes symptoms or the type of doctor they need, "
    "ask for their city or area if not mentioned, then call search_providers immediately. "
    "Present results conversationally — name, why it fits, trust score, distance. "
    "No bullet points or markdown. You are speaking, not typing. Keep responses very brief."
)

SEARCH_TOOL = {
    "type": "function",
    "name": "search_providers",
    "description": "Find healthcare providers in India for the user's health need and location",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Full query e.g. 'eye specialist near Koramangala Bangalore'",
            }
        },
        "required": ["query"],
    },
}

XAI_URL = "wss://api.x.ai/v1/realtime?model=grok-voice-think-fast-1.0"


async def _run_search(query: str, provided_lat: float | None = None, provided_lon: float | None = None) -> tuple[str, dict | None]:
    """Returns (spoken_text, full_results_dict | None)."""
    from .search import run_search

    async for chunk in run_search(query, provided_lat=provided_lat, provided_lon=provided_lon):
        if chunk.startswith("event: results\n"):
            data = json.loads(chunk.split("data: ", 1)[1].strip())
            providers = data.get("providers", [])
            if not providers:
                return "No providers found for that search.", None
            parts = [
                f"Found {len(providers)} provider{'s' if len(providers) > 1 else ''} "
                f"for {data.get('specialty_interpreted', 'that specialty')} "
                f"near {data.get('location_interpreted', 'that location')}."
            ]
            for i, p in enumerate(providers, 1):
                parts.append(
                    f"Number {i}: {p['name']}, trust score {p['trust_score']} out of 100, "
                    f"{p['distance_km']} kilometres away. {p.get('why_this', '')}"
                )
                if p.get("caveat"):
                    parts.append(f"Note: {p['caveat']}")
            return " ".join(parts), data
        if chunk.startswith("event: error\n"):
            data = json.loads(chunk.split("data: ", 1)[1].strip())
            return data.get("error", "Search failed."), None

    return "Search returned no results.", None


async def handle_voice_session(client_ws: WebSocket) -> None:
    await client_ws.accept()
    session: dict = {"location": None}  # {"lat": float, "lon": float} once client sends it

    try:
        async with websockets.connect(
            XAI_URL,
            additional_headers={"Authorization": f"Bearer {os.environ['XAI_API_KEY']}"},
            ping_interval=30,
        ) as xai_ws:
            await xai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "voice": "ara",
                    "instructions": SYSTEM_PROMPT,
                    "turn_detection": {"type": "server_vad"},
                    "tools": [SEARCH_TOOL],
                    "audio": {
                        "input": {"format": {"type": "audio/pcm", "rate": 24000}},
                        "output": {"format": {"type": "audio/pcm", "rate": 24000}},
                    },
                },
            }))

            async def from_client() -> None:
                try:
                    while True:
                        msg = await client_ws.receive_text()
                        try:
                            parsed = json.loads(msg)
                            if parsed.get("type") == "client.location":
                                lat, lon = float(parsed["lat"]), float(parsed["lon"])
                                session["location"] = {"lat": lat, "lon": lon}
                                # Tell xAI the user's location so it won't ask for it
                                await xai_ws.send(json.dumps({
                                    "type": "session.update",
                                    "session": {
                                        "instructions": SYSTEM_PROMPT + (
                                            f" The user's GPS location is lat={lat:.5f}, lon={lon:.5f}. "
                                            "You already know their location — never ask for it. "
                                            "Include it automatically in every search_providers call."
                                        )
                                    },
                                }))
                                continue
                        except Exception:
                            pass
                        await xai_ws.send(msg)
                except (WebSocketDisconnect, Exception):
                    pass

            async def from_xai() -> None:
                try:
                    async for raw in xai_ws:
                        event = json.loads(raw)

                        if event.get("type") == "response.function_call_arguments.done":
                            call_id = event.get("call_id", "")
                            args = json.loads(event.get("arguments", "{}"))

                            await client_ws.send_text(json.dumps({"type": "voice.searching"}))

                            if event.get("name") == "search_providers":
                                loc = session.get("location")
                                spoken, results_data = await _run_search(
                                    args.get("query", ""),
                                    provided_lat=loc["lat"] if loc else None,
                                    provided_lon=loc["lon"] if loc else None,
                                )
                                if results_data:
                                    await client_ws.send_text(json.dumps({
                                        "type": "voice.results",
                                        **results_data,
                                    }))
                                result = spoken
                            else:
                                result = "Unknown function."

                            await xai_ws.send(json.dumps({
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": result,
                                },
                            }))
                            await xai_ws.send(json.dumps({"type": "response.create"}))
                        else:
                            await client_ws.send_text(raw)
                except Exception:
                    pass

            await asyncio.gather(from_client(), from_xai())

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await client_ws.send_text(json.dumps({"type": "voice.error", "message": str(exc)}))
            await client_ws.close()
        except Exception:
            pass
