"""Small PCM activity detector for explicit Gemini Live speech boundaries.

This does not transcribe or classify language. Browser echo cancellation and
noise suppression still run before PCM reaches this server.
"""
from __future__ import annotations

import math
import struct
from collections import deque
from typing import Any, Awaitable, Callable


class PcmActivityDetector:
    def __init__(self, send: Callable[..., Awaitable[Any]], *, rms_threshold: float = 250, end_silence_ms: float = 500) -> None:
        self.send = send
        self.rms_threshold = rms_threshold
        self.end_silence_ms = end_silence_ms
        self.active = False
        self.speech_ms = 0.0
        self.silence_ms = 0.0
        self.prefix: deque[bytes] = deque(maxlen=8)
        self.received_bytes = 0
        self.forwarded_bytes = 0
        self.started_turns = 0
        self.ended_turns = 0
        self.peak = 0

    async def forward(self, pcm: bytes) -> None:
        await self.send(audio={"data": pcm, "mime_type": "audio/pcm;rate=16000"})
        self.forwarded_bytes += len(pcm)

    async def feed(self, pcm: bytes) -> None:
        if not pcm or len(pcm) % 2:
            raise ValueError("PCM16 frames must contain complete samples")
        samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        self.peak = max(self.peak, max(abs(sample) for sample in samples))
        self.received_bytes += len(pcm)
        duration_ms = len(samples) / 16
        voiced = rms >= self.rms_threshold
        if not self.active:
            self.prefix.append(pcm)
            self.speech_ms = self.speech_ms + duration_ms if voiced else 0
            if self.speech_ms < 40:
                return
            self.active = True
            self.started_turns += 1
            self.silence_ms = 0
            await self.send(activity_start={})
            for chunk in self.prefix:
                await self.forward(chunk)
            self.prefix.clear()
            return
        await self.forward(pcm)
        self.silence_ms = 0 if voiced else self.silence_ms + duration_ms
        if self.silence_ms >= self.end_silence_ms:
            await self.finish()

    async def finish(self) -> None:
        if self.active:
            await self.send(activity_end={})
            self.ended_turns += 1
        self.active = False
        self.speech_ms = self.silence_ms = 0
        self.prefix.clear()

    def receipt(self) -> dict[str, int | str]:
        return {"mode": "server_vad", "received_bytes": self.received_bytes, "forwarded_bytes": self.forwarded_bytes, "started_turns": self.started_turns, "ended_turns": self.ended_turns, "peak_pcm16": self.peak}
