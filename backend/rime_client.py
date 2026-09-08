import os
import time
import logging
import asyncio
from typing import AsyncGenerator

import httpx

logger = logging.getLogger("voicelog.rime")

RIME_ENDPOINT = os.getenv("RIME_ENDPOINT_URL", "https://users.rime.ai/v1/rime-tts")
RIME_API_KEY = os.getenv("RIME_API_KEY", "")
RIME_VOICE_ID = os.getenv("RIME_VOICE_ID", "marsh")
RIME_MODEL_ID = os.getenv("RIME_MODEL_ID", "mist")
RIME_LANGUAGE = os.getenv("RIME_LANGUAGE", "en")
RIME_AUDIO_FORMAT = os.getenv("RIME_AUDIO_FORMAT", "mp3")
RIME_SAMPLE_RATE = int(os.getenv("RIME_SAMPLE_RATE", "22050"))

AUDIO_CHUNK_SIZE = 4096


class RimeTTSClient:
    def __init__(self):
        self.endpoint = RIME_ENDPOINT
        self.api_key = RIME_API_KEY
        self.voice_id = RIME_VOICE_ID
        self.model_id = RIME_MODEL_ID
        self.language = RIME_LANGUAGE
        self.audio_format = RIME_AUDIO_FORMAT
        self.sample_rate = RIME_SAMPLE_RATE
        self._client = httpx.AsyncClient(timeout=30.0)

    async def synthesize_streaming(self, text: str) -> AsyncGenerator[bytes, None]:
        if not self.api_key:
            logger.warning("No RIME_API_KEY set, using mock TTS")
            async for chunk in self._mock_tts(text):
                yield chunk
            return

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": f"audio/{self.audio_format}",
            "Content-Type": "application/json",
        }

        payload = {
            "text": text,
            "speaker": self.voice_id,
            "modelId": self.model_id,
            "lang": self.language,
            "audioFormat": self.audio_format,
            "samplingRate": self.sample_rate,
            "speedAlpha": 1.0,
            "reduceLatency": True,
        }

        t_start = time.time()
        first_chunk = True

        try:
            async with self._client.stream("POST", self.endpoint, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.error(f"Rime API error {response.status_code}: {body[:200]}")
                    async for chunk in self._fallback_beep():
                        yield chunk
                    return

                async for chunk in response.aiter_bytes(AUDIO_CHUNK_SIZE):
                    if first_chunk:
                        logger.info(f"Rime TTFB: {round((time.time() - t_start) * 1000, 1)}ms")
                        first_chunk = False
                    yield chunk

        except httpx.TimeoutException:
            logger.error("Rime API timeout, falling back to beep")
            async for chunk in self._fallback_beep():
                yield chunk

        except Exception as e:
            logger.error(f"Rime API error: {e}")
            async for chunk in self._fallback_beep():
                yield chunk

    async def synthesize_full(self, text: str) -> tuple[bytes, float]:
        chunks = []
        t_start = time.time()
        ttfb = 0.0
        first = True

        async for chunk in self.synthesize_streaming(text):
            if first:
                ttfb = time.time() - t_start
                first = False
            chunks.append(chunk)

        return b"".join(chunks), ttfb

    async def _mock_tts(self, text: str) -> AsyncGenerator[bytes, None]:
        import struct
        import math

        duration = min(len(text) * 0.05, 5.0)
        sample_rate = 22050
        num_samples = int(sample_rate * duration)
        freq = 440.0

        await asyncio.sleep(0.05)

        samples_per_chunk = AUDIO_CHUNK_SIZE // 2
        for offset in range(0, num_samples, samples_per_chunk):
            chunk_samples = min(samples_per_chunk, num_samples - offset)
            data = b""
            for i in range(chunk_samples):
                t = (offset + i) / sample_rate
                envelope = max(0, 1.0 - t / duration)
                sample = int(16000 * envelope * math.sin(2 * math.pi * freq * t))
                sample = max(-32768, min(32767, sample))
                data += struct.pack("<h", sample)
            yield data
            await asyncio.sleep(0.01)

    async def _fallback_beep(self) -> AsyncGenerator[bytes, None]:
        import struct
        import math

        sample_rate = 22050
        duration = 0.3
        freq = 800.0
        num_samples = int(sample_rate * duration)

        data = b""
        for i in range(num_samples):
            t = i / sample_rate
            sample = int(8000 * math.sin(2 * math.pi * freq * t))
            data += struct.pack("<h", sample)

        yield data

    async def close(self):
        await self._client.aclose()
