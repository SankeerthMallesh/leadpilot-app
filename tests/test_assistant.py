import httpx
import respx

from app.models.audit import AssistantMessage
from app.schemas.intake import Intake
from app.services import intake as intake_svc
from tests.conftest import VALID_INTAKE, page_token


def _reply(text):
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}],
                                     "usage": {"input_tokens": 10, "output_tokens": 5}})


@respx.mock
def test_chat_returns_both_bubbles_and_stores_them(logged_in, db):
    route = respx.post("https://api.anthropic.com/v1/messages").mock(return_value=_reply("Try niche directories."))
    token = page_token(logged_in)
    r = logged_in.post("/assistant/chat", data={"message": "Where do I find leads?", "client_id": "",
                                                "page_path": "/clients"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 200
    assert "Where do I find leads?" in r.text and "Try niche directories." in r.text
    assert db.query(AssistantMessage).count() == 2
    assert route.call_count == 1


@respx.mock
def test_chat_with_client_includes_client_context(logged_in, db):
    client = intake_svc.create_client(db, Intake.model_validate(VALID_INTAKE), "admin")
    route = respx.post("https://api.anthropic.com/v1/messages").mock(return_value=_reply("ok"))
    token = page_token(logged_in)
    logged_in.post("/assistant/chat", data={"message": "review", "client_id": str(client.id), "page_path": "/x"},
                   headers={"X-CSRF-Token": token})
    sent = route.calls.last.request.content.decode()
    assert "Acme Roofing" in sent


@respx.mock
def test_history_is_scoped_per_client(logged_in, db):
    client = intake_svc.create_client(db, Intake.model_validate(VALID_INTAKE), "admin")
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=_reply("reply-for-client"))
    token = page_token(logged_in)
    logged_in.post("/assistant/chat", data={"message": "client question", "client_id": str(client.id),
                                            "page_path": "/x"}, headers={"X-CSRF-Token": token})
    general = logged_in.get("/assistant/history")
    scoped = logged_in.get(f"/assistant/history?client_id={client.id}")
    assert "client question" not in general.text
    assert "client question" in scoped.text


@respx.mock
def test_llm_failure_shows_friendly_message(logged_in):
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(400))
    token = page_token(logged_in)
    r = logged_in.post("/assistant/chat", data={"message": "hi", "client_id": "", "page_path": "/"},
                       headers={"X-CSRF-Token": token})
    assert r.status_code == 200 and "request failed" in r.text


def test_panel_is_rendered_on_the_right_of_pages(logged_in):
    html = logged_in.get("/clients").text
    assert 'id="ai-panel"' in html and 'id="chat-form"' in html
    assert html.index('id="ai-panel"') > html.index("<main")


SSE = "\n\n".join([
    'data: {"type":"message_start","message":{"usage":{"input_tokens":20}}}',
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hel"}}',
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}',
    'data: {"type":"message_delta","usage":{"output_tokens":4}}', ""])


def _stream_reply(text="Hello"):
    sse = SSE.replace("Hel", text[:3]).replace('"lo"', f'"{text[3:]}"') if text != "Hello" else SSE
    return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})


@respx.mock
def test_stream_emits_events_and_saves_reply(logged_in, db):
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=_stream_reply())
    token = page_token(logged_in)
    r = logged_in.post("/assistant/stream", data={"message": "hi", "client_id": "", "page_path": "/"},
                       headers={"X-CSRF-Token": token})
    assert '"t": "delta"' in r.text and '"t": "done"' in r.text
    roles = [(m.role, m.content) for m in db.query(AssistantMessage).order_by(AssistantMessage.id)]
    assert roles == [("user", "hi"), ("assistant", "Hello")]


@respx.mock
def test_regenerate_replaces_last_reply(logged_in, db):
    route = respx.post("https://api.anthropic.com/v1/messages")
    route.side_effect = [_stream_reply("Hello"), _stream_reply("Howdy")]
    token = page_token(logged_in)
    logged_in.post("/assistant/stream", data={"message": "hi", "client_id": "", "page_path": "/"},
                   headers={"X-CSRF-Token": token})
    logged_in.post("/assistant/stream", data={"regenerate": "1", "client_id": "", "page_path": "/"},
                   headers={"X-CSRF-Token": token})
    rows = [(m.role, m.content) for m in db.query(AssistantMessage).order_by(AssistantMessage.id)]
    assert rows == [("user", "hi"), ("assistant", "Howdy")]


def test_regenerate_with_empty_history_reports_error(logged_in):
    token = page_token(logged_in)
    r = logged_in.post("/assistant/stream", data={"regenerate": "1", "client_id": "", "page_path": "/"},
                       headers={"X-CSRF-Token": token})
    assert "nothing to regenerate" in r.text


@respx.mock
def test_stream_failure_is_reported_and_saved(logged_in, db):
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(400))
    token = page_token(logged_in)
    r = logged_in.post("/assistant/stream", data={"message": "hi", "client_id": "", "page_path": "/"},
                       headers={"X-CSRF-Token": token})
    assert '"t": "error"' in r.text
    assert "request failed" in db.query(AssistantMessage).order_by(AssistantMessage.id.desc()).first().content


def test_stream_requires_csrf(logged_in):
    assert logged_in.post("/assistant/stream", data={"message": "hi"}).status_code == 403
