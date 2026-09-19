import asyncio
import struct
from unittest.mock import AsyncMock

from live.audio import PcmActivityDetector

VOICE = struct.pack("<320h", *([1500, -1500] * 160))
SILENCE = b"\x00" * 640


def test_silence_does_not_start_turn_and_speech_is_preserved_with_prefix():
    async def scenario():
        send = AsyncMock()
        detector = PcmActivityDetector(send)
        await detector.feed(SILENCE)
        send.assert_not_awaited()
        await detector.feed(VOICE)
        send.assert_not_awaited()
        await detector.feed(VOICE)
        calls = send.await_args_list
        assert calls[0].kwargs == {"activity_start": {}}
        assert b"".join(call.kwargs["audio"]["data"] for call in calls if "audio" in call.kwargs) == SILENCE + VOICE + VOICE
        assert detector.receipt()["started_turns"] == 1
        assert detector.receipt()["peak_pcm16"] == 1500
    asyncio.run(scenario())


def test_trailing_silence_ends_turn_and_new_speech_can_interrupt_next_reply():
    async def scenario():
        send = AsyncMock()
        detector = PcmActivityDetector(send)
        await detector.feed(VOICE)
        await detector.feed(VOICE)
        for _ in range(25):
            await detector.feed(SILENCE)
        assert send.await_args.kwargs == {"activity_end": {}}
        await detector.feed(VOICE)
        await detector.feed(VOICE)
        await detector.finish()
        assert detector.receipt()["started_turns"] == detector.receipt()["ended_turns"] == 2
        assert sum(call.kwargs == {"activity_start": {}} for call in send.await_args_list) == 2
        assert sum(call.kwargs == {"activity_end": {}} for call in send.await_args_list) == 2
        assert not any("audio_stream_end" in call.kwargs for call in send.await_args_list)
    asyncio.run(scenario())


def test_a_short_noise_click_and_empty_stop_do_not_become_a_voice_turn():
    async def scenario():
        send = AsyncMock()
        detector = PcmActivityDetector(send)
        await detector.feed(VOICE)
        await detector.feed(SILENCE)
        await detector.finish()
        send.assert_not_awaited()
    asyncio.run(scenario())
