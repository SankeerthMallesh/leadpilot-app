import json

import httpx
import pytest
import respx

from app.config import get_settings
from app.providers import llm
from app.schemas.icp import ICP

URL = "https://api.anthropic.com/v1/messages"


def test_tool_for_inlines_refs():
    tool = llm.tool_for("t", "d", ICP)
    dumped = json.dumps(tool)
    assert "$ref" not in dumped and "$defs" not in dumped
    assert "min_employees" in tool["input_schema"]["properties"]["company_size"]["properties"]


def test_cache_aware_cost():
    model = get_settings().claude_model_main
    assert llm.compute_cost(model, 0, 0, cache_read=1_000_000) == pytest.approx(0.3)
    assert llm.compute_cost(model, 0, 0, cache_write=1_000_000) == pytest.approx(3.75)
    assert llm.compute_cost(model, 1_000_000, 0) == pytest.approx(3.0)


@respx.mock
def test_complete_marks_system_cacheable_and_forces_tool():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={
        "content": [{"type": "tool_use", "id": "t", "name": "x", "input": {"a": 1}}],
        "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}}))
    tool = {"name": "x", "description": "d", "input_schema": {"type": "object", "properties": {}}}
    result = llm.complete(system="sys", messages=[{"role": "user", "content": "hi"}], tool=tool)
    body = json.loads(route.calls.last.request.content)
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["tool_choice"] == {"type": "tool", "name": "x"}
    assert result.tool_input == {"a": 1} and result.cache_read_tokens == 100


@respx.mock
def test_stream_yields_deltas_then_usage():
    sse = "\n\n".join([
        'data: {"type":"message_start","message":{"usage":{"input_tokens":50,"cache_read_input_tokens":200}}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hel"}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}',
        'data: {"type":"message_delta","usage":{"output_tokens":7}}', ""])
    respx.post(URL).mock(return_value=httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"}))
    events = list(llm.stream(system="s", messages=[{"role": "user", "content": "hi"}]))
    assert [v for k, v in events if k == "delta"] == ["Hel", "lo"]
    usage = events[-1][1]
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (50, 7, 200)


@respx.mock
def test_stream_rejects_bad_request():
    respx.post(URL).mock(return_value=httpx.Response(400))
    with pytest.raises(llm.LLMError):
        list(llm.stream(system="s", messages=[{"role": "user", "content": "hi"}]))
