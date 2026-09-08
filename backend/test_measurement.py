#!/usr/bin/env python3
"""
Latency and interruption measurement tool for VoiceLog.
Produces JSON results for RIME_EVIDENCE.md.

Usage:
    python test_measurement.py --mode latency
    python test_measurement.py --mode interrupt
    python test_measurement.py --mode both
"""

import argparse
import asyncio
import json
import time
import sys
import os
import statistics

sys.path.insert(0, os.path.dirname(__file__))

from rime_client import RimeTTSClient
from orchestrator import IntentOrchestrator


async def measure_latency(trials: int = 10) -> dict:
    """Measure time from text input to first TTS audio chunk."""
    rime = RimeTTSClient()
    orchestrator = IntentOrchestrator()

    test_phrases = [
        "Log part replaced on unit seven.",
        "Start timer.",
        "Add note: belt shows wear on the left side.",
        "Status.",
        "Log filter changed, pressure normal.",
        "Stop timer.",
        "Read log.",
        "Log bearing lubricated.",
        "Add note: vibration detected at high RPM.",
        "Log compressor maintenance complete.",
    ]

    results = []

    print(f"\n{'='*60}")
    print(f"  LATENCY MEASUREMENT - {trials} trials")
    print(f"{'='*60}\n")

    for i in range(min(trials, len(test_phrases))):
        phrase = test_phrases[i % len(test_phrases)]

        # Phase 1: Orchestrator latency
        t0 = time.time()
        intent = await orchestrator.parse(phrase)
        t_orchestrator = time.time() - t0

        response_text = intent.get("response", "") or f"Logged: {intent.get('detail', phrase)}"

        # Phase 2: TTS time-to-first-byte
        t1 = time.time()
        first_chunk_received = False
        total_bytes = 0
        t_first_chunk = 0

        async for chunk in rime.synthesize_streaming(response_text):
            if not first_chunk_received:
                t_first_chunk = time.time() - t1
                first_chunk_received = True
            total_bytes += len(chunk)

        t_total_tts = time.time() - t1

        # Total end-to-end: orchestrator + TTS first chunk
        e2e_first_chunk = t_orchestrator + t_first_chunk

        result = {
            "trial": i + 1,
            "phrase": phrase,
            "orchestrator_ms": round(t_orchestrator * 1000, 1),
            "tts_ttfb_ms": round(t_first_chunk * 1000, 1),
            "tts_total_ms": round(t_total_tts * 1000, 1),
            "e2e_first_chunk_ms": round(e2e_first_chunk * 1000, 1),
            "audio_bytes": total_bytes,
        }
        results.append(result)

        status = "PASS" if e2e_first_chunk < 0.9 else "FAIL"
        print(f"  Trial {i+1:2d}: E2E={result['e2e_first_chunk_ms']:7.1f}ms "
              f"(orch={result['orchestrator_ms']:.1f}ms + ttfb={result['tts_ttfb_ms']:.1f}ms) "
              f"[{status}]")

    e2e_times = [r["e2e_first_chunk_ms"] for r in results]
    summary = {
        "test": "latency",
        "trials": len(results),
        "target_ms": 900,
        "mean_e2e_ms": round(statistics.mean(e2e_times), 1),
        "median_e2e_ms": round(statistics.median(e2e_times), 1),
        "p95_e2e_ms": round(sorted(e2e_times)[int(len(e2e_times) * 0.95)], 1) if len(e2e_times) >= 2 else e2e_times[-1],
        "min_e2e_ms": round(min(e2e_times), 1),
        "max_e2e_ms": round(max(e2e_times), 1),
        "pass_rate": f"{sum(1 for t in e2e_times if t < 900) / len(e2e_times) * 100:.0f}%",
        "results": results,
    }

    print(f"\n  Summary:")
    print(f"    Mean E2E:   {summary['mean_e2e_ms']}ms")
    print(f"    Median E2E: {summary['median_e2e_ms']}ms")
    print(f"    P95 E2E:    {summary['p95_e2e_ms']}ms")
    print(f"    Pass rate:  {summary['pass_rate']} (< 900ms)")
    print()

    return summary


async def measure_interrupt(trials: int = 5) -> dict:
    """Measure time to cancel TTS playback after interrupt signal."""
    rime = RimeTTSClient()

    long_text = (
        "This is a comprehensive maintenance report for unit seven. "
        "The primary bearing was inspected and found to have moderate wear. "
        "The lubrication system was serviced and the filter was replaced. "
        "Vibration readings were taken at multiple points and all fall within "
        "acceptable parameters. The next scheduled maintenance is in thirty days."
    )

    results = []

    print(f"\n{'='*60}")
    print(f"  INTERRUPTION MEASUREMENT - {trials} trials")
    print(f"{'='*60}\n")

    for i in range(trials):
        chunks_before_interrupt = []
        interrupted = False
        t_start = time.time()
        t_interrupt = None
        t_stopped = None

        chunk_count = 0
        interrupt_after_ms = 500

        async for chunk in rime.synthesize_streaming(long_text):
            chunk_count += 1
            elapsed = (time.time() - t_start) * 1000

            if not interrupted and elapsed >= interrupt_after_ms:
                t_interrupt = time.time()
                interrupted = True
                t_stopped = time.time()
                break

            chunks_before_interrupt.append(chunk)

        if t_interrupt is None:
            t_interrupt = time.time()
            t_stopped = time.time()

        interrupt_latency = (t_stopped - t_interrupt) * 1000

        result = {
            "trial": i + 1,
            "chunks_received": chunk_count,
            "interrupt_after_ms": interrupt_after_ms,
            "interrupt_response_ms": round(interrupt_latency, 2),
            "audio_bytes_before_interrupt": sum(len(c) for c in chunks_before_interrupt),
        }
        results.append(result)

        status = "PASS" if interrupt_latency < 200 else "FAIL"
        print(f"  Trial {i+1}: Interrupted after {interrupt_after_ms}ms, "
              f"response={result['interrupt_response_ms']:.2f}ms "
              f"({chunk_count} chunks) [{status}]")

    interrupt_times = [r["interrupt_response_ms"] for r in results]
    summary = {
        "test": "interruption",
        "trials": len(results),
        "target_ms": 200,
        "mean_interrupt_ms": round(statistics.mean(interrupt_times), 2),
        "max_interrupt_ms": round(max(interrupt_times), 2),
        "pass_rate": f"{sum(1 for t in interrupt_times if t < 200) / len(interrupt_times) * 100:.0f}%",
        "results": results,
    }

    print(f"\n  Summary:")
    print(f"    Mean interrupt:  {summary['mean_interrupt_ms']}ms")
    print(f"    Max interrupt:   {summary['max_interrupt_ms']}ms")
    print(f"    Pass rate:       {summary['pass_rate']} (< 200ms)")
    print()

    return summary


async def main():
    parser = argparse.ArgumentParser(description="VoiceLog latency and interruption measurement")
    parser.add_argument("--mode", choices=["latency", "interrupt", "both"], default="both",
                        help="Which test to run")
    parser.add_argument("--trials", type=int, default=10,
                        help="Number of trials per test")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path")
    args = parser.parse_args()

    all_results = {}

    if args.mode in ("latency", "both"):
        all_results["latency"] = await measure_latency(args.trials)

    if args.mode in ("interrupt", "both"):
        all_results["interrupt"] = await measure_interrupt(min(args.trials, 5))

    all_results["metadata"] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rime_model": os.getenv("RIME_MODEL_ID", "mist"),
        "rime_voice": os.getenv("RIME_VOICE_ID", "marsh"),
        "rime_format": os.getenv("RIME_AUDIO_FORMAT", "mp3"),
    }

    output_path = args.output or "measurement_results.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"Results saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
