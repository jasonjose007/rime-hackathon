# RIME_EVIDENCE.md — Hard Voice Problem Evidence

## Hard Voice Claim

**Primary:** The system achieves < 900ms end-to-end perceived latency (from user speech end to first audible TTS frame at the client) under normal operating conditions.

**Secondary:** The system achieves < 200ms interrupt response time (from barge-in signal to complete playback silence) under active TTS streaming.

## Why These Are Hard

**Latency** — A voice-first field tool is unusable if the technician has to wait more than ~1 second for confirmation. The pipeline has four serial stages (ASR, intent parsing, TTS synthesis, audio delivery), each contributing latency. We minimize this by streaming TTS output chunk-by-chunk and beginning playback on the first chunk rather than waiting for full synthesis.

**Interruption** — In a real field scenario, the technician may start a command, realize they misspoke, and say "stop, edit note." If the system keeps speaking the old response while trying to process the new one, the interaction breaks down. The system must cancel TTS mid-stream, flush the client audio buffer, and be ready for new input within 200ms.

## Acceptance Test

### Test 1: Latency

**Claim:** End-to-end first-chunk latency < 900ms for 90%+ of trials.

**Procedure:**
1. Start the backend server.
2. Run the measurement script with 10 trial phrases.
3. The script sends each phrase through the orchestrator and Rime TTS pipeline.
4. It measures: orchestrator parse time, TTS time-to-first-byte, and total end-to-end time.

**Repeatable command:**
```bash
cd backend
python test_measurement.py --mode latency --trials 10 --output latency_results.json
```

**Expected output:** JSON file with per-trial and summary statistics.

**Latency formula:**
```
E2E_first_chunk = T_orchestrator + T_rime_ttfb
```

Where:
- `T_orchestrator` = time for rule-based intent parsing (typically < 5ms)
- `T_rime_ttfb` = time from Rime API request to first audio byte received

**Result:** [INSERT MEASURED RESULT]

**Pass criteria:** `mean_e2e_ms < 900` and `pass_rate >= 90%`

### Test 2: Interruption

**Claim:** Interrupt-to-silence latency < 200ms.

**Procedure:**
1. Start a long TTS synthesis (5-sentence maintenance report).
2. After 500ms of playback, trigger an interrupt.
3. Measure the time from interrupt signal to cancellation of the TTS stream.

**Repeatable command:**
```bash
cd backend
python test_measurement.py --mode interrupt --trials 5 --output interrupt_results.json
```

**Interruption formula:**
```
T_interrupt = T_cancel_signal_processed - T_interrupt_sent
```

Server-side cancellation is near-instant (asyncio task cancellation). Client-side buffer flush adds ~10-50ms depending on buffered audio duration.

**Result:** [INSERT MEASURED RESULT]

**Pass criteria:** `max_interrupt_ms < 200`

## End-to-End Stress Test

**Scenario:** Send a long text (5 sentences) to Rime, interrupt after 500ms, immediately send a new short command ("Status"), and measure that the new response arrives within the latency target.

**Repeatable command:**
```bash
cd backend
python test_measurement.py --mode both --trials 10 --output full_results.json
```

## Limitations

1. **Network jitter** — Latency measurements depend on network conditions between the server and Rime's API. Results will vary based on geographic proximity and network congestion. Tests should be run multiple times and averaged.

2. **API rate limits** — Under high concurrency, Rime or Groq API rate limits may increase latency. Our measurements assume single-user operation.

3. **Cold start** — The first TTS request after server startup may be slower due to connection establishment. The measurement script discards the first trial as a warm-up when computing statistics.

4. **Mock mode** — When `RIME_API_KEY` is not set, the system uses a mock TTS that generates a sine wave tone. Mock latency does not reflect real Rime API performance. Evidence must be gathered with a real API key.

5. **Client-side latency** — The `test_measurement.py` script measures server-side latency only. Actual perceived latency includes WebSocket transit time and Web Audio buffer scheduling, adding an estimated 20-80ms depending on the client.

## Rime Integration Details

| Setting | Value |
|---------|-------|
| Model ID | `mist` |
| Speaker | `marsh` |
| Language | `en` |
| Endpoint | `https://users.rime.ai/v1/rime-tts` |
| Audio Format | `mp3` |
| Sample Rate | 22050 Hz |
| Transport | HTTPS with streaming response |
| `reduceLatency` | `true` |
| `speedAlpha` | `1.0` |
