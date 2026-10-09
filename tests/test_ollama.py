import json

import httpx
import pytest
import respx

from app.config import get_settings
from app.providers import llm

URL = "http://127.0.0.1:11434/api/chat"
MSG = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def _ollama(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "ollama")
    monkeypatch.setattr(s, "ollama_base_url", "http://127.0.0.1:11434")
    monkeypatch.setattr(s, "ollama_model", "llama3.1:8b")
    monkeypatch.setattr(llm, "_ollama_gate", None)


def _ndjson(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


@respx.mock
def test_stream_parses_ndjson_and_sends_tuned_options():
    body = _ndjson({"message": {"content": "Hel"}, "done": False}, {"message": {"content": "lo"}, "done": False},
                   {"message": {"content": ""}, "done": True, "prompt_eval_count": 12, "eval_count": 5,
                    "eval_duration": 500_000_000})
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    events = list(llm.stream(system="sys", messages=MSG, max_tokens=300))
    assert [v for k, v in events if k == "delta"] == ["Hel", "lo"]
    usage = events[-1][1]
    assert (usage.input_tokens, usage.output_tokens, usage.cost_usd, usage.tokens_per_second) == (12, 5, 0.0, 10.0)
    sent = json.loads(route.calls.last.request.content)
    assert sent["stream"] is True and sent["keep_alive"] == "30m" and sent["model"] == "llama3.1:8b"
    assert sent["options"]["num_predict"] == 300 and sent["options"]["num_ctx"] == 4096
    assert sent["messages"][0] == {"role": "system", "content": "sys"}


@respx.mock
def test_stream_without_done_is_an_interruption():
    respx.post(URL).mock(return_value=httpx.Response(200, content=_ndjson({"message": {"content": "Hi"}, "done": False})))
    with pytest.raises(llm.LLMError, match="interrupted"):
        list(llm.stream(system="s", messages=MSG))


@respx.mock
def test_model_not_found_gives_pull_command():
    respx.post(URL).mock(return_value=httpx.Response(404, json={"error": "model 'x' not found"}))
    with pytest.raises(llm.LLMError, match="ollama pull"):
        list(llm.stream(system="s", messages=MSG))


@respx.mock
def test_unreachable_server_message():
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(llm.LLMError, match="Cannot reach Ollama"):
        llm.complete(system="s", messages=MSG)


@respx.mock
def test_complete_structured_output_uses_schema_format():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={
        "message": {"content": '{"a": 1}'}, "prompt_eval_count": 3, "eval_count": 2}))
    tool = {"name": "x", "description": "d", "input_schema": {"type": "object", "properties": {"a": {"type": "integer"}}}}
    result = llm.complete(system="s", messages=MSG, tool=tool)
    sent = json.loads(route.calls.last.request.content)
    assert sent["format"] == tool["input_schema"] and sent["stream"] is False
    assert result.tool_input == {"a": 1} and result.cost_usd == 0.0


def test_model_name_mapping():
    s = get_settings()
    assert llm._ollama_model(None) == "llama3.1:8b"
    assert llm._ollama_model(s.claude_model_main) == "llama3.1:8b"
    assert llm._ollama_model("custom:tag") == "custom:tag"


def test_keep_alive_number_or_duration():
    assert llm._keep_alive("-1") == -1 and llm._keep_alive("30m") == "30m"
