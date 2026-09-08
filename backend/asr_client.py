import os
import io
import time
import logging
import asyncio

import httpx

logger = logging.getLogger("voicelog.asr")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_ASR_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
ASR_MODEL = os.getenv("ASR_MODEL", "whisper-large-v3-turbo")


class ASRClient:
    def __init__(self):
        self.groq_key = GROQ_API_KEY
        self._client = httpx.AsyncClient(timeout=15.0)

    async def transcribe(self, audio_bytes: bytes) -> str:
        if not self.groq_key:
            logger.warning("No GROQ_API_KEY set, using mock ASR")
            return self._mock_transcribe()

        return await self._groq_transcribe(audio_bytes)

    async def _groq_transcribe(self, audio_bytes: bytes) -> str:
        t_start = time.time()

        headers = {
            "Authorization": f"Bearer {self.groq_key}",
        }

        from audio_utils import ensure_wav_header
        wav_bytes = ensure_wav_header(audio_bytes)

        files = {
            "file": ("audio.wav", io.BytesIO(wav_bytes), "audio/wav"),
        }
        data = {
            "model": ASR_MODEL,
            "language": "en",
            "response_format": "text",
            "temperature": 0.0,
        }

        try:
            response = await self._client.post(
                GROQ_ASR_ENDPOINT,
                headers=headers,
                files=files,
                data=data,
            )

            if response.status_code != 200:
                logger.error(f"Groq ASR error {response.status_code}: {response.text[:200]}")
                return ""

            transcript = response.text.strip()
            latency = round((time.time() - t_start) * 1000, 1)
            logger.info(f"ASR result ({latency}ms): {transcript[:80]}")
            return transcript

        except Exception as e:
            logger.error(f"ASR request failed: {e}")
            return ""

    def _mock_transcribe(self) -> str:
        return ""

    async def close(self):
        await self._client.aclose()
