import asyncio
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .. import transcribe
from ..auth import current_member, member_for_token, public_member
from ..db import connect
from .consultation import editable
from .operations import get_visit

router = APIRouter(prefix="/api")
_active: set[int] = set()   # one live stream per visit (single server process)


@router.get("/dictation")
def provider(me=Depends(current_member)):
    return {"provider": "deepgram" if transcribe.enabled() else "browser"}


def _check(token: str, visit_id: int) -> str | None:
    """None when this login may dictate into this visit, else the reason."""
    db = connect()
    try:
        m = member_for_token(db, token)
        if not m:
            return "Session ended. Log in again."
        me = public_member(m)
        if "consultation" not in me["screens"]:
            return "No access to Consultation."
        try:
            editable(db, get_visit(db, me, visit_id))
        except HTTPException as e:
            return e.detail
        db.commit()
        return None
    finally:
        db.close()


@router.websocket("/visits/{visit_id}/dictate")
async def dictate(ws: WebSocket, visit_id: int):
    # The login token comes as a WebSocket subprotocol so it never appears in URLs or logs.
    protocols = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",")]
    token = protocols[1] if len(protocols) == 2 and protocols[0] == "dictate" else ""
    await ws.accept(subprotocol="dictate" if token else None)

    async def fail(message: str):
        with suppress(Exception):
            await ws.send_json({"type": "error", "message": message})
            await ws.close(code=1008)

    problem = await asyncio.to_thread(_check, token, visit_id)
    if problem:
        return await fail(problem)
    if not transcribe.enabled():
        return await fail("Dictation is not set up.")
    if visit_id in _active:
        return await fail("Already dictating in another window.")
    _active.add(visit_id)
    stream = None
    try:
        async def on_text(event: dict):
            if ws.application_state == WebSocketState.CONNECTED:
                with suppress(Exception):
                    await ws.send_json({"type": "transcript", **event})

        stream = transcribe.DeepgramStream()
        await stream.connect(on_text)
        await ws.send_json({"type": "ready"})
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect" or msg.get("text") == "stop":
                break
            if msg.get("bytes"):
                await stream.send(msg["bytes"])
    except WebSocketDisconnect:
        pass
    except Exception:
        await fail("Dictation stopped. Try again.")
    finally:
        if stream is not None:
            await asyncio.shield(stream.close())   # last words still reach the browser
        _active.discard(visit_id)
        if ws.application_state == WebSocketState.CONNECTED:
            with suppress(Exception):
                await ws.close()
