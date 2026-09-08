import os
import json
import asyncio
import time
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from rime_client import RimeTTSClient
from asr_client import ASRClient
from orchestrator import IntentOrchestrator
from audio_utils import chunk_audio, pcm_to_wav_header

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voicelog")

rime = RimeTTSClient()
asr = ASRClient()
orchestrator = IntentOrchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("VoiceLog server starting")
    yield
    logger.info("VoiceLog server shutting down")


app = FastAPI(title="VoiceLog - Voice Field Operations Log", lifespan=lifespan)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


class SessionState:
    def __init__(self):
        self.is_speaking = False
        self.current_tts_task: asyncio.Task | None = None
        self.interrupted = False
        self.log_entries: list[dict] = []
        self.active_timer: float | None = None
        self.sequence_id = 0

    def next_seq(self) -> int:
        self.sequence_id += 1
        return self.sequence_id


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session = SessionState()
    logger.info("Client connected")

    try:
        while True:
            try:
                msg_type = await ws.receive()
            except WebSocketDisconnect:
                break

            if msg_type.get("type") == "websocket.disconnect":
                break

            if "bytes" in msg_type and msg_type["bytes"]:
                audio_bytes = msg_type["bytes"]
                await handle_audio_input(ws, session, audio_bytes)

            elif "text" in msg_type and msg_type["text"]:
                msg = json.loads(msg_type["text"])
                await handle_text_message(ws, session, msg)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        logger.info("Client disconnected")


async def handle_text_message(ws: WebSocket, session: SessionState, msg: dict):
    msg_type = msg.get("type")

    if msg_type == "interrupt":
        await handle_interrupt(ws, session)

    elif msg_type == "text_input":
        text = msg.get("text", "").strip()
        if text:
            await process_user_utterance(ws, session, text)

    elif msg_type == "audio_end":
        pass

    elif msg_type == "ping":
        await ws.send_text(json.dumps({"type": "pong", "ts": time.time()}))


async def handle_audio_input(ws: WebSocket, session: SessionState, audio_bytes: bytes):
    t_recv = time.time()

    if session.is_speaking:
        await handle_interrupt(ws, session)

    try:
        transcript = await asr.transcribe(audio_bytes)
    except Exception as e:
        logger.error(f"ASR error: {e}")
        await ws.send_text(json.dumps({
            "type": "error",
            "message": "Speech recognition failed. Please try again."
        }))
        return

    if not transcript or not transcript.strip():
        return

    await ws.send_text(json.dumps({
        "type": "transcript",
        "text": transcript,
        "asr_latency_ms": round((time.time() - t_recv) * 1000, 1)
    }))

    await process_user_utterance(ws, session, transcript, t_asr_done=time.time())


async def process_user_utterance(ws: WebSocket, session: SessionState, text: str, t_asr_done: float | None = None):
    t_start = time.time()
    seq = session.next_seq()

    intent = await orchestrator.parse(text)

    action_result = execute_action(session, intent)

    response_text = intent.get("response", action_result)

    await ws.send_text(json.dumps({
        "type": "intent",
        "intent": intent.get("action", "unknown"),
        "detail": intent.get("detail", ""),
        "response_text": response_text,
        "sequence_id": seq,
        "orchestrator_latency_ms": round((time.time() - t_start) * 1000, 1)
    }))

    session.current_tts_task = asyncio.create_task(
        stream_tts_to_client(ws, session, response_text, seq, t_start)
    )


def execute_action(session: SessionState, intent: dict) -> str:
    action = intent.get("action", "unknown")
    detail = intent.get("detail", "")

    if action == "log":
        entry = {
            "text": detail,
            "timestamp": time.time(),
            "id": len(session.log_entries) + 1
        }
        session.log_entries.append(entry)
        return f"Logged: {detail}. Entry number {entry['id']}."

    elif action == "start_timer":
        session.active_timer = time.time()
        return "Timer started."

    elif action == "stop_timer":
        if session.active_timer:
            elapsed = round(time.time() - session.active_timer, 1)
            session.active_timer = None
            return f"Timer stopped. Elapsed: {elapsed} seconds."
        return "No active timer."

    elif action == "add_note":
        entry = {
            "text": f"[NOTE] {detail}",
            "timestamp": time.time(),
            "id": len(session.log_entries) + 1
        }
        session.log_entries.append(entry)
        return f"Note added: {detail}."

    elif action == "edit_note":
        if session.log_entries:
            session.log_entries[-1]["text"] = f"[EDITED] {detail}"
            return f"Last entry edited to: {detail}."
        return "No entries to edit."

    elif action == "read_log":
        if not session.log_entries:
            return "Log is empty."
        recent = session.log_entries[-3:]
        lines = [f"Entry {e['id']}: {e['text']}" for e in recent]
        return "Recent entries. " + " ".join(lines)

    elif action == "status":
        count = len(session.log_entries)
        timer_status = "running" if session.active_timer else "stopped"
        return f"You have {count} log entries. Timer is {timer_status}."

    elif action == "clear":
        session.log_entries.clear()
        return "Log cleared."

    else:
        return intent.get("response", "Command not recognized. Try: log, timer, add note, read log, or status.")


async def stream_tts_to_client(ws: WebSocket, session: SessionState, text: str, seq: int, t_pipeline_start: float):
    session.is_speaking = True
    session.interrupted = False
    first_chunk_sent = False
    t_tts_start = time.time()

    try:
        async for audio_chunk in rime.synthesize_streaming(text):
            if session.interrupted or session.sequence_id != seq:
                logger.info(f"TTS cancelled for seq {seq}")
                break

            if not first_chunk_sent:
                first_chunk_latency = round((time.time() - t_pipeline_start) * 1000, 1)
                tts_latency = round((time.time() - t_tts_start) * 1000, 1)
                await ws.send_text(json.dumps({
                    "type": "tts_start",
                    "sequence_id": seq,
                    "first_chunk_latency_ms": first_chunk_latency,
                    "tts_latency_ms": tts_latency
                }))
                first_chunk_sent = True

            await ws.send_bytes(audio_chunk)

        if not session.interrupted and session.sequence_id == seq:
            await ws.send_text(json.dumps({
                "type": "tts_end",
                "sequence_id": seq,
                "total_latency_ms": round((time.time() - t_pipeline_start) * 1000, 1)
            }))

    except Exception as e:
        logger.error(f"TTS streaming error: {e}")
        await ws.send_text(json.dumps({
            "type": "error",
            "message": "Voice synthesis failed. Falling back to text.",
            "sequence_id": seq
        }))
    finally:
        session.is_speaking = False


async def handle_interrupt(ws: WebSocket, session: SessionState):
    t_interrupt = time.time()
    session.interrupted = True

    if session.current_tts_task and not session.current_tts_task.done():
        session.current_tts_task.cancel()
        try:
            await session.current_tts_task
        except asyncio.CancelledError:
            pass

    session.is_speaking = False

    await ws.send_text(json.dumps({
        "type": "interrupt_ack",
        "interrupt_latency_ms": round((time.time() - t_interrupt) * 1000, 1)
    }))
    logger.info(f"Interrupt handled in {round((time.time() - t_interrupt) * 1000, 1)}ms")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
