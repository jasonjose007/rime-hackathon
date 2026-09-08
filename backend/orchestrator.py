import os
import re
import logging

import httpx

logger = logging.getLogger("voicelog.orchestrator")

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

INTENT_PATTERNS = [
    (r"(?i)^(?:log|record|entry)\b[:\s]*(.+)", "log"),
    (r"(?i)^(?:start\s+timer|timer\s+start|begin\s+timer)", "start_timer"),
    (r"(?i)^(?:stop\s+timer|timer\s+stop|end\s+timer|pause\s+timer)", "stop_timer"),
    (r"(?i)^(?:add\s+note|note)[:\s]*(.+)", "add_note"),
    (r"(?i)^(?:edit\s+(?:note|last|entry)|update\s+(?:note|last|entry))[:\s]*(.+)", "edit_note"),
    (r"(?i)^(?:read\s+log|show\s+log|list\s+entries|what(?:'s| is)\s+in\s+(?:the\s+)?log)", "read_log"),
    (r"(?i)^(?:status|current\s+status|what(?:'s| is)\s+(?:the\s+)?status)", "status"),
    (r"(?i)^(?:clear\s+(?:log|all|entries)|reset\s+log)", "clear"),
    (r"(?i)^(?:stop|cancel|never\s*mind|abort)", "interrupt_command"),
    (r"(?i)^(?:help|what\s+can\s+(?:you|I)\s+(?:do|say))", "help"),
]

HELP_TEXT = (
    "You can say: log something, start timer, stop timer, add note, "
    "edit note, read log, status, clear log, or stop."
)


class IntentOrchestrator:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=10.0)

    async def parse(self, text: str) -> dict:
        result = self._rule_based_parse(text)
        if result["action"] != "unknown":
            return result

        if LLM_API_KEY:
            return await self._llm_parse(text)

        return {
            "action": "unknown",
            "detail": text,
            "response": f"I didn't understand that. {HELP_TEXT}"
        }

    def _rule_based_parse(self, text: str) -> dict:
        text = text.strip()

        for pattern, action in INTENT_PATTERNS:
            match = re.match(pattern, text)
            if match:
                detail = ""
                if match.groups():
                    detail = match.group(1).strip() if match.group(1) else ""

                if action == "help":
                    return {"action": "help", "detail": "", "response": HELP_TEXT}

                if action == "interrupt_command":
                    return {"action": "interrupt_command", "detail": "", "response": "Stopping."}

                return {"action": action, "detail": detail, "response": ""}

        return {"action": "unknown", "detail": text, "response": ""}

    async def _llm_parse(self, text: str) -> dict:
        system_prompt = (
            "You are an intent parser for a voice-driven field operations log. "
            "Given a user command, respond with ONLY a JSON object with keys: "
            "action (one of: log, start_timer, stop_timer, add_note, edit_note, "
            "read_log, status, clear, help, unknown), detail (extracted content), "
            "response (a short spoken confirmation). Keep responses under 20 words."
        )

        try:
            resp = await self._client.post(
                LLM_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 150,
                },
            )

            if resp.status_code != 200:
                logger.error(f"LLM error {resp.status_code}")
                return {"action": "unknown", "detail": text, "response": "Sorry, I didn't catch that."}

            import json
            content = resp.json()["choices"][0]["message"]["content"]
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"```\w*\n?", "", content).strip()

            parsed = json.loads(content)
            return {
                "action": parsed.get("action", "unknown"),
                "detail": parsed.get("detail", ""),
                "response": parsed.get("response", "Done."),
            }

        except Exception as e:
            logger.error(f"LLM parse error: {e}")
            return {"action": "unknown", "detail": text, "response": "Sorry, I didn't understand."}

    async def close(self):
        await self._client.aclose()
