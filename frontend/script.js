(() => {
    "use strict";

    const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
    const WS_URL = `${wsProto}//${location.host}/ws`;

    const $ = (sel) => document.querySelector(sel);
    const connDot = $("#connection-status");
    const connText = $("#connection-text");
    const pulseRing = $("#pulse-ring");
    const micBtn = $("#mic-btn");
    const interruptBtn = $("#interrupt-btn");
    const textInput = $("#text-input");
    const sendBtn = $("#send-btn");
    const userTranscript = $("#user-transcript");
    const assistantResponse = $("#assistant-response");
    const metricLatency = $("#metric-latency");
    const metricTtfb = $("#metric-ttfb");
    const metricStatus = $("#metric-status");
    const logEntries = $("#log-entries");

    let ws = null;
    let audioCtx = null;
    let mediaRecorder = null;
    let audioChunks = [];
    let isRecording = false;
    let isSpeaking = false;
    let audioQueue = [];
    let currentSource = null;
    let nextPlayTime = 0;
    let playbackActive = false;

    function connect() {
        ws = new WebSocket(WS_URL);
        ws.binaryType = "arraybuffer";

        ws.onopen = () => {
            connDot.className = "status-dot connected";
            connText.textContent = "Connected";
            micBtn.disabled = false;
            metricStatus.textContent = "Ready";
        };

        ws.onclose = () => {
            connDot.className = "status-dot disconnected";
            connText.textContent = "Disconnected";
            micBtn.disabled = true;
            metricStatus.textContent = "Offline";
            setTimeout(connect, 2000);
        };

        ws.onerror = () => {
            ws.close();
        };

        ws.onmessage = (event) => {
            if (event.data instanceof ArrayBuffer) {
                handleAudioChunk(event.data);
            } else {
                handleTextMessage(JSON.parse(event.data));
            }
        };
    }

    function handleTextMessage(msg) {
        switch (msg.type) {
            case "transcript":
                userTranscript.textContent = `You: ${msg.text}`;
                if (msg.asr_latency_ms) {
                    metricStatus.textContent = `ASR: ${msg.asr_latency_ms}ms`;
                }
                break;

            case "intent":
                assistantResponse.textContent = `System: ${msg.response_text}`;
                if (msg.orchestrator_latency_ms) {
                    metricStatus.textContent = `Processing`;
                }
                addLogEntry(msg.intent, msg.detail || msg.response_text);
                break;

            case "tts_start":
                isSpeaking = true;
                pulseRing.className = "speaking";
                interruptBtn.style.display = "inline-block";
                metricLatency.textContent = `${msg.first_chunk_latency_ms}ms`;
                metricTtfb.textContent = `${msg.tts_latency_ms}ms`;
                metricStatus.textContent = "Speaking";
                break;

            case "tts_end":
                finishPlayback();
                if (msg.total_latency_ms) {
                    metricStatus.textContent = `Done (${msg.total_latency_ms}ms)`;
                }
                break;

            case "interrupt_ack":
                flushAudio();
                metricStatus.textContent = `Interrupted (${msg.interrupt_latency_ms}ms)`;
                break;

            case "error":
                assistantResponse.textContent = `Error: ${msg.message}`;
                metricStatus.textContent = "Error";
                finishPlayback();
                break;

            case "pong":
                break;
        }
    }

    function handleAudioChunk(arrayBuffer) {
        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }

        if (audioCtx.state === "suspended") {
            audioCtx.resume();
        }

        playFullAudio(arrayBuffer);
    }

    async function playFullAudio(arrayBuffer) {
        if (!audioCtx) return;

        try {
            const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer.slice(0));
            const source = audioCtx.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(audioCtx.destination);
            source.start(0);
            currentSource = source;
            playbackActive = true;

            source.onended = () => {
                playbackActive = false;
                currentSource = null;
            };
        } catch (e) {
            console.warn("Audio decode error:", e);
            playbackActive = false;
        }
    }

    function flushAudio() {
        audioQueue = [];
        if (currentSource) {
            try { currentSource.stop(); } catch {}
            currentSource = null;
        }
        playbackActive = false;
        isSpeaking = false;
        pulseRing.className = "idle";
        interruptBtn.style.display = "none";
    }

    function finishPlayback() {
        setTimeout(() => {
            if (audioQueue.length === 0) {
                isSpeaking = false;
                pulseRing.className = "idle";
                interruptBtn.style.display = "none";
            }
        }, 300);
    }

    function sendInterrupt() {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "interrupt" }));
            flushAudio();
        }
    }

    async function startRecording() {
        if (isRecording) return;

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                },
            });

            if (isSpeaking) {
                sendInterrupt();
            }

            mediaRecorder = new MediaRecorder(stream, {
                mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
                    ? "audio/webm;codecs=opus"
                    : "audio/webm",
            });

            audioChunks = [];
            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) audioChunks.push(e.data);
            };

            mediaRecorder.onstop = async () => {
                stream.getTracks().forEach((t) => t.stop());
                if (audioChunks.length === 0) return;

                const blob = new Blob(audioChunks, { type: "audio/webm" });
                const arrayBuf = await blob.arrayBuffer();

                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(arrayBuf);
                }
            };

            mediaRecorder.start(100);
            isRecording = true;
            pulseRing.className = "listening";
            micBtn.textContent = "Release to Send";
            metricStatus.textContent = "Listening";
        } catch (err) {
            console.error("Mic error:", err);
            metricStatus.textContent = "Mic Error";
        }
    }

    function stopRecording() {
        if (!isRecording || !mediaRecorder) return;

        mediaRecorder.stop();
        isRecording = false;
        pulseRing.className = "processing";
        micBtn.textContent = "Hold to Speak";
        metricStatus.textContent = "Processing...";
    }

    function sendText(text) {
        if (!text.trim() || !ws || ws.readyState !== WebSocket.OPEN) return;

        if (isSpeaking) {
            sendInterrupt();
        }

        userTranscript.textContent = `You: ${text}`;
        assistantResponse.textContent = "";

        ws.send(JSON.stringify({ type: "text_input", text: text.trim() }));
        textInput.value = "";
        metricStatus.textContent = "Processing...";
        pulseRing.className = "processing";
    }

    function addLogEntry(action, detail) {
        if (!["log", "add_note", "edit_note", "start_timer", "stop_timer", "clear"].includes(action)) return;

        const emptyMsg = logEntries.querySelector(".log-empty");
        if (emptyMsg) emptyMsg.remove();

        if (action === "clear") {
            logEntries.innerHTML = '<div class="log-empty">No entries yet</div>';
            return;
        }

        const entry = document.createElement("div");
        entry.className = "log-entry";

        const now = new Date();
        const timeStr = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

        entry.innerHTML = `
            <span class="log-entry-text">${escapeHtml(detail)}</span>
            <span class="log-entry-time">${timeStr}</span>
        `;

        logEntries.prepend(entry);

        while (logEntries.children.length > 20) {
            logEntries.removeChild(logEntries.lastChild);
        }
    }

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    // Event listeners
    micBtn.addEventListener("mousedown", startRecording);
    micBtn.addEventListener("mouseup", stopRecording);
    micBtn.addEventListener("mouseleave", () => { if (isRecording) stopRecording(); });
    micBtn.addEventListener("touchstart", (e) => { e.preventDefault(); startRecording(); });
    micBtn.addEventListener("touchend", (e) => { e.preventDefault(); stopRecording(); });

    interruptBtn.addEventListener("click", sendInterrupt);

    sendBtn.addEventListener("click", () => sendText(textInput.value));
    textInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") sendText(textInput.value);
    });

    // Initialize
    logEntries.innerHTML = '<div class="log-empty">No entries yet</div>';
    connect();

    // Keepalive ping
    setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
        }
    }, 30000);
})();
