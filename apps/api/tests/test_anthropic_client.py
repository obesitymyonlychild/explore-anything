"""Runs the real SDK wrapper against a mocked HTTP transport (no network, no API key)."""

import json

import anthropic
import httpx2  # the SDK's HTTP layer (anthropic>=1.x); objects passed to it must be httpx2

from app.llm.card_schema import OUTPUT_FORMAT
from app.llm.client import FALLBACK_BETA, AnthropicCardLLM, Final, TextDelta, ThinkingStarted


def sse_body(card_text: str) -> str:
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 0},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": "", "signature": ""},
            },
        ),
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig-xyz"}},
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "content_block_start",
            {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        ),
        *[
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "text_delta", "text": card_text[i : i + 10]},
                },
            )
            for i in range(0, len(card_text), 10)
        ],
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 42},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


async def test_request_shape_and_stream_parsing():
    card_text = json.dumps({"concept": "Tides", "kind": "intro"})
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, text=sse_body(card_text), headers={"content-type": "text/event-stream"})

    client = anthropic.AsyncAnthropic(
        api_key="test", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    llm = AnthropicCardLLM(client)
    system = [{"type": "text", "text": "rules"}]
    messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]

    events = [e async for e in llm.stream_card(system, messages)]

    body = seen["body"]
    assert seen["url"].startswith("https://api.anthropic.com/v1/messages")
    assert body["model"] == "claude-opus-5-5"
    assert body["stream"] is True
    assert body["system"] == system and body["messages"] == messages
    assert body["output_config"] == {"effort": "medium", "format": OUTPUT_FORMAT}
    assert body["fallbacks"] == "default"
    assert body["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in body and "temperature" not in body
    assert FALLBACK_BETA in seen["headers"]["anthropic-beta"]

    assert isinstance(events[0], ThinkingStarted)
    deltas = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert deltas == card_text
    final = events[-1]
    assert isinstance(final, Final)
    assert final.stop_reason == "end_turn"
    assert final.content == [
        {"type": "thinking", "thinking": "", "signature": "sig-xyz"},
        {"type": "text", "text": card_text},
    ]
    assert final.usage["output_tokens"] == 42
