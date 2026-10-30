"""Live dictation link, with a fake Deepgram."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import transcribe
from app.main import app
from tests.test_review_gaps import clinic, started_visit


class FakeStream:
    closed = 0

    async def connect(self, on_text):
        self.on_text = on_text

    async def send(self, audio):
        await self.on_text({"text": audio.decode(), "final": False})

    async def close(self):
        FakeStream.closed += 1
        await self.on_text({"text": "last words", "final": True})


@pytest.fixture
def deepgram(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test")
    monkeypatch.setattr(transcribe, "DeepgramStream", FakeStream)


def token(h):
    return h["Authorization"].removeprefix("Bearer ")


def test_provider_follows_key(monkeypatch):
    with TestClient(app) as c:
        h, _ = clinic(c, "d0@x.in")
        monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
        assert c.get("/api/dictation", headers=h).json() == {"provider": "browser"}
        monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
        assert c.get("/api/dictation", headers=h).json() == {"provider": "deepgram"}


def test_text_streams_back_and_last_words_arrive(deepgram):
    with TestClient(app) as c:
        h, doc = clinic(c, "d1@x.in")
        v = started_visit(c, h, doc)
        with c.websocket_connect(f"/api/visits/{v['id']}/dictate", subprotocols=["dictate", token(h)]) as ws:
            assert ws.receive_json() == {"type": "ready"}
            ws.send_bytes(b"fever since monday")
            assert ws.receive_json() == {"type": "transcript", "text": "fever since monday", "final": False}
            ws.send_text("stop")
            assert ws.receive_json() == {"type": "transcript", "text": "last words", "final": True}
        # the server never writes the transcript itself; the page saves it
        assert c.get(f"/api/visits/{v['id']}", headers=h).json()["text"] == ""


def refused(c, path, protocols):
    with c.websocket_connect(path, subprotocols=protocols) as ws:
        msg = ws.receive_json()
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    return msg


def test_refused_without_login_other_clinic_or_unstarted_visit(deepgram):
    with TestClient(app) as c:
        h, doc = clinic(c, "d2@x.in")
        v = started_visit(c, h, doc)
        path = f"/api/visits/{v['id']}/dictate"
        assert refused(c, path, ["dictate", "bad-token"])["type"] == "error"
        assert refused(c, path, [])["message"] == "Session ended. Log in again."
        other, _ = clinic(c, "d2b@x.in")
        assert refused(c, path, ["dictate", token(other)])["type"] == "error"
        p = c.post("/api/patients", headers=h, json={"name": "Later", "consent": True}).json()
        w = c.post("/api/visits/walk-in", headers=h, json={"patient_id": p["id"], "doctor_id": doc, "payment_method": "cash"}).json()
        assert refused(c, f"/api/visits/{w['id']}/dictate", ["dictate", token(h)])["message"] == "Start the consultation first."


def test_one_stream_per_visit(deepgram):
    with TestClient(app) as c:
        h, doc = clinic(c, "d3@x.in")
        v = started_visit(c, h, doc)
        path, proto = f"/api/visits/{v['id']}/dictate", ["dictate", token(h)]
        with c.websocket_connect(path, subprotocols=proto) as first:
            assert first.receive_json()["type"] == "ready"
            assert refused(c, path, proto)["message"] == "Already dictating in another window."
            first.send_text("stop")
            first.receive_json()
        with c.websocket_connect(path, subprotocols=proto) as again:
            assert again.receive_json()["type"] == "ready"


def test_not_set_up_without_key(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    with TestClient(app) as c:
        h, doc = clinic(c, "d4@x.in")
        v = started_visit(c, h, doc)
        assert refused(c, f"/api/visits/{v['id']}/dictate", ["dictate", token(h)])["message"] == "Dictation is not set up."
