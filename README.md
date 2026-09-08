# VoiceLog - Voice-Driven Field Operations Log

A voice-first field operations logging system for maintenance technicians. Built for the **DataForge x Rime Hackathon**.

## The Problem

Maintenance technicians work hands-busy and eyes-busy — holding tools, looking at machinery. They need to log observations, start timers, and add notes without touching a screen. A text-based app is useless in this context. Removing speech from VoiceLog makes the product non-functional.

## How It Solves the Hard Voice Problem

**Primary: Perceived Response Time (Latency)**

The pipeline is optimized for minimal time between the user finishing a command and hearing the first audio frame of the response:

1. **Streaming TTS** — Audio chunks stream to the client as they are generated. The frontend begins playback on the first chunk arrival, not after full synthesis completes.
2. **Fast intent parsing** — A rule-based parser handles common commands in <1ms. LLM fallback is only used for ambiguous input.
3. **WebSocket transport** — Persistent bidirectional connection eliminates HTTP handshake overhead on every turn.
4. **Target: <900ms end-to-end** from speech-end to first audible response.

**Secondary: Interruption and Recovery (Barge-in)**

1. The frontend detects the user pressing the mic button while the system is speaking.
2. An interrupt signal is sent via WebSocket.
3. The backend cancels the in-progress TTS stream and increments a sequence counter.
4. The frontend flushes the Web Audio buffer and stops playback instantly.
5. **Target: <200ms from interrupt signal to silence.**

## Architecture

```
[Microphone] --> [WebSocket] --> [ASR (Groq Whisper)] --> [Intent Parser]
                                                              |
                                                     [Action Executor]
                                                              |
                                                   [Rime TTS Streaming]
                                                              |
                                          [WebSocket chunks] --> [Web Audio Playback]
```

- **Backend:** Python 3.11+, FastAPI, WebSockets
- **Frontend:** Vanilla HTML/CSS/JS, Web Audio API
- **TTS:** Rime API (streaming HTTP)
- **ASR:** Groq Whisper API (whisper-large-v3-turbo)
- **Intent:** Rule-based parser with optional LLM fallback (Llama 3.1 8B via Groq)

## Rime Configuration

| Parameter     | Value                                    |
|---------------|------------------------------------------|
| **Model ID**  | `mist`                                   |
| **Speaker**   | `marsh`                                  |
| **Language**   | `en`                                     |
| **Endpoint**  | `https://users.rime.ai/v1/rime-tts`     |
| **Audio Format** | `mp3`                                 |
| **Sample Rate** | `22050 Hz`                              |
| **Transport** | HTTPS (streaming response body)          |

## Setup

### Prerequisites

- Python 3.11+
- A Rime API key ([rime.ai](https://rime.ai))
- A Groq API key ([groq.com](https://groq.com)) for ASR and optional LLM

### Installation

```bash
git clone <this-repo>
cd rime-hackathon

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Running

```bash
cd backend
python app.py
```

Open http://localhost:8000 in your browser.

### Running Measurement Tests

```bash
cd backend
python test_measurement.py --mode both --trials 10
```

Results are saved to `measurement_results.json`.

## Supported Voice Commands

| Command | Example |
|---------|---------|
| Log entry | "Log part replaced on unit seven" |
| Start timer | "Start timer" |
| Stop timer | "Stop timer" |
| Add note | "Add note: belt shows wear" |
| Edit last entry | "Edit note: belt replaced" |
| Read log | "Read log" |
| Status | "Status" |
| Clear log | "Clear log" |

## Known Limitations

1. **ASR accuracy** — Groq Whisper may misinterpret domain-specific terms (part numbers, equipment names) in noisy environments.
2. **Rime API timeout** — If the Rime API does not respond within 30 seconds, the system falls back to a local beep tone to acknowledge the command. Text response is still shown on screen.
3. **Single-user** — The WebSocket session is single-user. No authentication or multi-tenancy.
4. **Browser mic access** — Requires HTTPS in production for microphone access. Works on localhost for development.
5. **Audio format** — Web Audio API decoding of streamed MP3 chunks may vary across browsers. Tested on Chrome 130+.
6. **No offline mode** — Requires network connectivity for both ASR and TTS.

## Third-Party Services

| Service | Purpose | Free Tier |
|---------|---------|-----------|
| Rime | Text-to-Speech | API key required |
| Groq | ASR (Whisper) + LLM (Llama) | Free tier available |

## License

MIT
