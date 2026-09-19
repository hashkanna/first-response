# Final integration check — 19 September 2026

The final service ran the generated timeout workflow as incident `inc-14f63b6d27a3`. The UI measured 10.6 seconds to verified candidates. Gemini proposed 3,000, 1,000 and 5,000 millisecond repairs; the first two passed all 25 checks, while the third failed `test_provider_timeout_remains_enforced`.

In the actual browser, a typed question asked why the five-second candidate failed. Gemini Live answered that it did not raise the expected `PaymentTimeout` exception in that regression test. The answer matched the recorded log and left the incident unchanged.

A separate synthetic-PCM session said “Apply the verified fix.” The provider transcribed the affirmative request but supplied no final-transcription flag. The relay emitted a `review_requested` event for this incident and its verified candidate; its approval tool returned false. Stage stayed `fix_verified`, with no approval. [Exact receipt](evidence/voice-review.json). This receipt proves the review event and unchanged state, not a completed spoken reply: capture stopped at the first two PCM output bytes. The [separate recovery recording](evidence/gemini-recovery-audio.json) contains a complete 10.36-second native response.

Finally, the actual browser sent the explicit typed command “Approve the verified fix.” The client included the incident identifier, Gemini invoked the approval tool, and the hub applied the verified 3,000-millisecond patch. Fresh Modal verification passed 25 tests and all twelve checkout probes. The UI displayed “Incident resolved” and the downloadable patch. [Final status and complete event evidence](evidence/final-integration.json).

Automated tests separately cover stale speech after reset, new speech revoking prior typed approval, delayed negation, stale typed incident identifiers, and review confirmation bound to its original incident. Human microphone and headset testing remains a rehearsal step.

Final local verification: **168 Python tests passed**, **36 frontend tests passed**, and the TypeScript/Vite production build succeeded. The only Python warning was an upstream Starlette/AnyIO deprecation.
