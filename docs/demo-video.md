# Two-minute demo

[Watch or download the demo](https://github.com/hashkanna/first-response/releases/tag/v1.0.0) · [Direct MP4](https://github.com/hashkanna/first-response/releases/download/v1.0.0/first-response-demo.mp4)

The finished video is exactly **120 seconds**, 1920 × 1080 at 30 fps, with burned captions and a subtitle track. It combines eight actual UI screenshots from the generated timeout and coupon runs documented in [the execution evidence](generated-run-evidence.md).

This is an edited walkthrough, not a continuous screen recording. Scenes 1–7 have separately synthesized macOS narration and are labeled accordingly. From 01:48, the final scene includes the entire 10.36-second **actual Gemini Live response** to a typed, read-only question about the resolved coupon incident. Its transcript and provider events are [recorded here](evidence/gemini-recovery-audio.json). Captions for this clip are approximate and explicitly labeled; they are not word-aligned. A human microphone was not used for this recording.

The walkthrough shows the real five-second timeout candidate failing a regression, inspection and approval of the 3,000-millisecond repair, fresh Modal recovery, and three passing coupon alternatives. No test outcome was edited or selected by the narrator. The generated code executes only in Modal; the local runtime copy stores the approved patch as data.

[Build receipt](evidence/demo-video.json) includes source-image and original-audio hashes, scene timing, and output metadata. To assemble new captures locally:

```bash
python3 scripts/make_demo_video.py \
  --manifest .runtime/demo-captures/video-manifest.json \
  --target-duration 120 --voice Samantha --rate 174 --overwrite
```

The capture manifest and raw frames are local runtime artifacts, not part of the source checkout. Use [the narration guide](demo-narration.txt) and the local capture companion for a new run. The assembler requires macOS, Swift/AppKit, `say`, FFmpeg, and ffprobe. It refuses to exceed 120 seconds or truncate supplied audio.
