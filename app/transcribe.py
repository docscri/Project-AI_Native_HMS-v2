"""Live speech-to-text with Deepgram (ported from Project-Dictate)."""
import asyncio
import logging
import os
from contextlib import suppress

log = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(os.environ.get("DEEPGRAM_API_KEY", "").strip())


class DeepgramStream:
    """Browser audio in (16 kHz mono 16-bit PCM), text out via on_text({"text", "final"})."""

    def __init__(self):
        from deepgram import AsyncDeepgramClient
        self.client = AsyncDeepgramClient(api_key=os.environ["DEEPGRAM_API_KEY"].strip())
        self.conn = self.ctx = self.listen_task = self.keep_task = None
        self.send_lock, self.close_lock = asyncio.Lock(), asyncio.Lock()
        self.closing, self.error = False, None

    async def connect(self, on_text) -> None:
        from deepgram.core.events import EventType
        from deepgram.listen.v1.types import ListenV1Results
        options = {"model": os.environ.get("DEEPGRAM_MODEL", "nova-3"), "language": os.environ.get("DEEPGRAM_LANGUAGE", "en"),
                   "interim_results": True, "smart_format": True, "encoding": "linear16", "sample_rate": 16000, "channels": 1}
        for attempt in range(3):
            try:
                ctx = self.client.listen.v1.connect(**options)
                self.conn = await asyncio.wait_for(ctx.__aenter__(), timeout=10)
                self.ctx = ctx
                break
            except Exception as exc:
                status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
                if not (isinstance(exc, (OSError, TimeoutError)) or status in (408, 429, 500, 502, 503, 504)) or attempt == 2:
                    raise RuntimeError("Transcription connection failed") from exc
                await asyncio.sleep(0.5 * 2 ** attempt)

        async def on_message(message):
            if not isinstance(message, ListenV1Results) or not message.channel or not message.channel.alternatives:
                return
            text = (message.channel.alternatives[0].transcript or "").strip()
            if text:
                await on_text({"text": text, "final": bool(message.is_final)})

        def on_error(error):
            self.error = error if isinstance(error, Exception) else RuntimeError(str(error))
            log.error("Deepgram stream failed: %s", error)

        self.conn.on(EventType.MESSAGE, on_message)
        self.conn.on(EventType.ERROR, on_error)
        self.listen_task = asyncio.create_task(self.conn.start_listening())
        self.keep_task = asyncio.create_task(self._keep_alive())

    async def _keep_alive(self):
        with suppress(asyncio.CancelledError):
            while not self.closing:
                await asyncio.sleep(3)
                async with self.send_lock:
                    if not self.closing and self.conn is not None:
                        await self.conn.send_keep_alive()

    async def send(self, audio: bytes) -> None:
        async with self.send_lock:
            if self.conn is None or self.closing:
                raise RuntimeError("Transcription stream is not connected")
            if self.error is not None or self.listen_task.done():
                raise RuntimeError("Transcription connection was lost") from self.error
            if audio:
                await self.conn.send_media(audio)

    async def close(self) -> None:
        """Waits for Deepgram's last words before closing."""
        async with self.close_lock:
            if self.ctx is None:
                return
            self.closing = True
            if self.keep_task:
                self.keep_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.keep_task
            try:
                if self.listen_task and not self.listen_task.done():
                    async with self.send_lock:
                        await self.conn.send_close_stream()
                    await asyncio.wait_for(asyncio.shield(self.listen_task), timeout=10)
            except Exception:
                log.exception("Deepgram finalization failed")
            finally:
                if self.listen_task and not self.listen_task.done():
                    self.listen_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await self.listen_task
                with suppress(Exception):
                    await self.ctx.__aexit__(None, None, None)
                self.conn = self.ctx = self.listen_task = self.keep_task = None
