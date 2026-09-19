#!/usr/bin/env python3
"""Assemble <=120s of explicitly labelled, narrated screenshot highlights.

Requires macOS say, Swift/AppKit, ffmpeg and ffprobe. Python uses only stdlib.
No browser control, external service, image generation, or cloud API is used.

Example:
  python3 scripts/make_demo_video.py \
    --manifest .runtime/demo-captures/manifest.json --target-duration 120

Manifest: {"title": "First Response", "scenes": [
  {"image": "01-alert.png", "heading": "The alert", "narration": "Exact approved narration."}
]}

Image paths resolve relative to the manifest or --captures-dir. Optional scene
duration values are minimum holds; actual speech must fit. Spare target time is
distributed among scenes. Missing narration and unresolved placeholders fail.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

FPS = 30
WIDTH, HEIGHT = 1920, 1080
SAMPLE_RATE = 48_000
SAMPLES_PER_FRAME = SAMPLE_RATE // FPS
MAX_SECONDS = 120.0
LEAD_FRAMES = 8
TRAIL_FRAMES = 12
PHRASE_GAP_SECONDS = 0.09
DISCLOSURE = "EDITED HIGHLIGHTS  /  NARRATION: macOS SAY"
REPO = Path(__file__).resolve().parents[1]

# Homebrew ffmpeg may lack drawtext/libass. AppKit renders text and fits the
# supplied screenshot into a static frame, without opening any window or app UI.
SWIFT_RENDERER = r'''
import AppKit
import Foundation

struct RenderJob: Decodable {
    let image: String
    let output: String
    let heading: String
    let caption: String
    let disclosure: String
    let index: String
}

func drawText(_ text: String, _ rect: NSRect, size: CGFloat,
              color: NSColor, alignment: NSTextAlignment = .left,
              weight: NSFont.Weight = .regular) {
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = alignment
    paragraph.lineBreakMode = .byWordWrapping
    paragraph.lineSpacing = 5
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: size, weight: weight),
        .foregroundColor: color,
        .paragraphStyle: paragraph,
    ]
    let string = NSAttributedString(string: text, attributes: attributes)
    let measured = string.boundingRect(with: NSSize(width: rect.width, height: 1000),
                                      options: [.usesLineFragmentOrigin, .usesFontLeading])
    guard measured.height <= rect.height + 1 else {
        fatalError("Text exceeds its readable frame area; shorten heading/caption")
    }
    string.draw(with: rect, options: [.usesLineFragmentOrigin, .usesFontLeading])
}

let jobs = try JSONDecoder().decode([RenderJob].self,
    from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
for job in jobs {
    guard let source = NSImage(contentsOfFile: job.image), source.size.width > 0,
          source.size.height > 0,
          let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 1920,
              pixelsHigh: 1080, bitsPerSample: 8, samplesPerPixel: 4,
              hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
              bytesPerRow: 0, bitsPerPixel: 0),
          let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        fatalError("Cannot read screenshot or initialize frame")
    }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    NSColor(calibratedRed: 0.032, green: 0.044, blue: 0.065, alpha: 1).setFill()
    NSRect(x: 0, y: 0, width: 1920, height: 1080).fill()

    let area = NSRect(x: 32, y: 180, width: 1856, height: 780)
    let scale = min(area.width / source.size.width, area.height / source.size.height)
    let fitted = NSSize(width: source.size.width * scale, height: source.size.height * scale)
    let destination = NSRect(x: area.midX - fitted.width / 2,
                             y: area.midY - fitted.height / 2,
                             width: fitted.width, height: fitted.height)
    source.draw(in: destination, from: .zero, operation: .copy, fraction: 1)

    drawText(job.disclosure, NSRect(x: 42, y: 1038, width: 1670, height: 25),
             size: 15, color: NSColor(calibratedWhite: 0.66, alpha: 1), weight: .medium)
    drawText(job.index, NSRect(x: 1730, y: 1038, width: 148, height: 25),
             size: 15, color: NSColor(calibratedWhite: 0.66, alpha: 1), alignment: .right)
    drawText(job.heading, NSRect(x: 42, y: 983, width: 1836, height: 46),
             size: 31, color: .white, weight: .semibold)
    NSColor(calibratedRed: 0.27, green: 0.63, blue: 1, alpha: 1).setFill()
    NSRect(x: 42, y: 970, width: 82, height: 3).fill()
    if !job.caption.isEmpty {
        drawText(job.caption, NSRect(x: 95, y: 48, width: 1730, height: 110),
                 size: 36, color: .white, alignment: .center, weight: .medium)
    }
    NSGraphicsContext.restoreGraphicsState()
    guard let png = bitmap.representation(using: .png, properties: [:]) else {
        fatalError("Could not encode composed screenshot")
    }
    try png.write(to: URL(fileURLWithPath: job.output), options: .atomic)
}
'''


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            value.update(chunk)
    return value.hexdigest()


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 120) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} failed ({result.returncode}):\n{result.stderr[-3000:]}")
    return result.stdout


def tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise ValueError(f"Required local tool is missing: {name}")
    return found


def checked_text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be nonempty text, at most {maximum} characters")
    text = " ".join(value.split())
    if re.search(r"\{\{|\}\}|\[(?:INSERT|VERIFY|FAULT|PASS|RESULT|VOICE|ACTUAL|CHOOSE)[^\]]*\]|\bTODO\b", text, re.I):
        raise ValueError(f"{field} contains an unresolved factual placeholder")
    return text


def read_manifest(path: Path, captures_dir: Path | None) -> tuple[dict, list[dict]]:
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or not isinstance(document.get("scenes"), list):
        raise ValueError("Manifest must be an object containing a scenes array")
    if not 1 <= len(document["scenes"]) <= 24:
        raise ValueError("Supply between 1 and 24 actual screenshot scenes")
    base = captures_dir or path.parent
    scenes = []
    for index, raw in enumerate(document["scenes"], start=1):
        if not isinstance(raw, dict) or not isinstance(raw.get("image"), str):
            raise ValueError(f"Scene {index} must name an actual screenshot image")
        image = Path(raw["image"]).expanduser()
        image = (base / image).resolve() if not image.is_absolute() else image.resolve()
        if not image.is_file() or image.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError(f"Scene {index} screenshot is missing or unsupported: {image}")
        minimum = raw.get("duration")
        if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum) or not 0 < minimum <= MAX_SECONDS):
            raise ValueError(f"Scene {index} duration must be a positive minimum hold of at most 120 seconds")
        scenes.append({"image": image, "heading": checked_text(raw.get("heading"), f"Scene {index} heading", maximum=95),
                       "narration": checked_text(raw.get("narration"), f"Scene {index} narration", maximum=2500),
                       "requested_duration": minimum})
    return document, scenes


def caption_phrases(text: str) -> list[str]:
    """Keep sentence/phrase boundaries where possible; bound two-line captions."""
    sentences = re.split(r"(?<=[.!?;])\s+", text)
    phrases = []
    for sentence in sentences:
        current: list[str] = []
        for word in sentence.split():
            if len(word) > 55:
                raise ValueError("Narration contains a word too long for readable captions; shorten identifiers or URLs")
            if current and (len(" ".join([*current, word])) > 108 or len(current) >= 18):
                phrases.append(" ".join(current))
                current = []
            current.append(word)
        if current:
            phrases.append(" ".join(current))
    return phrases


def srt_time(frame: int) -> str:
    milliseconds = round(frame * 1000 / FPS)
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def write_silence(output: wave.Wave_write, samples: int) -> None:
    block = b"\0\0" * min(samples, SAMPLE_RATE)
    while samples:
        count = min(samples, SAMPLE_RATE)
        output.writeframesraw(block[:count * 2])
        samples -= count


def distribute_frames(scenes: list[dict], target_frames: int) -> None:
    minimums = []
    for scene in scenes:
        speech_frames = sum(part["frames"] for part in scene["parts"])
        required = LEAD_FRAMES + speech_frames + TRAIL_FRAMES
        requested = scene["requested_duration"]
        if requested is not None and requested * FPS + 1e-6 < required:
            raise ValueError(f"Scene '{scene['heading']}' needs at least {required / FPS:.2f}s for its narration; requested minimum was {requested}s")
        minimums.append(max(required, math.ceil(requested * FPS) if requested else 0))
    if sum(minimums) > target_frames:
        raise ValueError(f"Narration and minimum holds need {sum(minimums) / FPS:.2f}s, exceeding the {target_frames / FPS:.2f}s target. Shorten narration or deliberately choose a faster --rate.")
    spare = target_frames - sum(minimums)
    weights = [max(1, sum(part["frames"] for part in scene["parts"])) for scene in scenes]
    shares = [spare * weight // sum(weights) for weight in weights]
    for index in range(spare - sum(shares)):
        shares[index % len(shares)] += 1
    for scene, minimum, share in zip(scenes, minimums, shares):
        scene["duration_frames"] = minimum + share


def make_video(args: argparse.Namespace) -> dict:
    manifest = args.manifest.expanduser().resolve()
    document, scenes = read_manifest(manifest, args.captures_dir.expanduser().resolve() if args.captures_dir else None)
    if not math.isfinite(args.target_duration) or not 1 <= args.target_duration <= MAX_SECONDS:
        raise ValueError("Target duration must be between 1 and 120 seconds")
    if not 100 <= args.rate <= 220:
        raise ValueError("Narration rate must be between 100 and 220 words per minute")
    target_frames = round(args.target_duration * FPS)
    target = target_frames / FPS
    if target > MAX_SECONDS:
        raise ValueError("Frame-rounded target exceeds 120 seconds")
    if args.validate_only:
        return {"validated": True, "scenes": len(scenes), "target_duration_s": target,
                "notice": "Speech has not been synthesized; final duration is not yet verified."}

    commands = {name: tool(name) for name in ("say", "ffmpeg", "ffprobe", "swiftc")}
    output_dir = args.output_dir.expanduser().resolve()
    movie = output_dir / "first-response-demo.mp4"
    if movie.exists() and not args.overwrite:
        raise ValueError(f"Output already exists: {movie}. Use --overwrite for an intentional revision.")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("speech", "frames", "renderer-cache"):
        (output_dir / name).mkdir(exist_ok=True)
    print(f"Synthesizing local narration for {len(scenes)} captured scenes.", flush=True)
    for scene_index, scene in enumerate(scenes, start=1):
        scene["parts"] = []
        for phrase_index, phrase in enumerate(caption_phrases(scene["narration"]), start=1):
            stem = output_dir / "speech" / f"{scene_index:02}-{phrase_index:02}"
            text_path, aiff_path, wav_path = stem.with_suffix(".txt"), stem.with_suffix(".aiff"), stem.with_suffix(".wav")
            text_path.write_text(phrase)
            say = [commands["say"], "-r", str(args.rate), "-f", str(text_path), "-o", str(aiff_path)]
            if args.voice:
                say.extend(["-v", args.voice])
            run(say)
            run([commands["ffmpeg"], "-hide_banner", "-loglevel", "error", "-y", "-i", str(aiff_path),
                 "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)])
            with wave.open(str(wav_path), "rb") as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, SAMPLE_RATE):
                    raise RuntimeError("Unexpected narration PCM format")
                samples = audio.getnframes()
            if samples <= 0:
                raise RuntimeError("macOS say produced empty narration")
            frames = math.ceil((samples / SAMPLE_RATE + PHRASE_GAP_SECONDS) * FPS)
            scene["parts"].append({"text": phrase, "wav": wav_path, "samples": samples, "frames": frames})
        print(f"  Scene {scene_index}: {scene['heading']}", flush=True)
    distribute_frames(scenes, target_frames)

    narration = output_dir / "narration.wav"
    subtitles = output_dir / "subtitles.srt"
    jobs: list[dict] = []
    holds: list[tuple[str, int]] = []
    cues: list[dict] = []
    cursor = 0

    def frame(scene: dict, caption: str, index: int) -> str:
        relative = f"frames/frame-{len(jobs) + 1:04}.png"
        jobs.append({"image": str(scene["image"]), "output": str(output_dir / relative),
                     "heading": scene["heading"], "caption": caption, "disclosure": DISCLOSURE,
                     "index": f"{index:02} / {len(scenes):02}"})
        return relative

    with wave.open(str(narration), "wb") as audio_out:
        audio_out.setnchannels(1)
        audio_out.setsampwidth(2)
        audio_out.setframerate(SAMPLE_RATE)
        for index, scene in enumerate(scenes, start=1):
            scene["start_frame"] = cursor
            blank = frame(scene, "", index)
            holds.append((blank, LEAD_FRAMES))
            write_silence(audio_out, LEAD_FRAMES * SAMPLES_PER_FRAME)
            cursor += LEAD_FRAMES
            for part in scene["parts"]:
                holds.append((frame(scene, part["text"], index), part["frames"]))
                cues.append({"text": part["text"], "start_frame": cursor, "end_frame": cursor + part["frames"]})
                with wave.open(str(part["wav"]), "rb") as source:
                    audio_out.writeframesraw(source.readframes(source.getnframes()))
                write_silence(audio_out, part["frames"] * SAMPLES_PER_FRAME - part["samples"])
                cursor += part["frames"]
            remaining = scene["duration_frames"] - (cursor - scene["start_frame"])
            holds.append((blank, remaining))
            write_silence(audio_out, remaining * SAMPLES_PER_FRAME)
            cursor += remaining
    if cursor != target_frames:
        raise RuntimeError("Internal timeline did not match its exact frame budget")
    subtitles.write_text("\n\n".join(f"{index}\n{srt_time(cue['start_frame'])} --> {srt_time(cue['end_frame'])}\n{cue['text']}" for index, cue in enumerate(cues, start=1)) + "\n")

    renderer_source = output_dir / "render-frames.swift"
    renderer_source.write_text(SWIFT_RENDERER)
    renderer = output_dir / "render-frames"
    run([commands["swiftc"], "-O", "-module-cache-path", str(output_dir / "renderer-cache"),
         str(renderer_source), "-o", str(renderer)], timeout=180)
    render_jobs = output_dir / "render-jobs.json"
    render_jobs.write_text(json.dumps(jobs, indent=2))
    print(f"Rendering {len(jobs)} captioned frames; screenshots are fitted without cropping.", flush=True)
    run([str(renderer), str(render_jobs)], timeout=180)
    concat = output_dir / "frames.ffconcat"
    concat.write_text("ffconcat version 1.0\n" + "".join(f"file '{name}'\nduration {frames / FPS:.9f}\n" for name, frames in holds) + f"file '{holds[-1][0]}'\n")
    title = checked_text(document.get("title", "First Response"), "Video title", maximum=150)
    print(f"Encoding {WIDTH}×{HEIGHT}, {FPS}fps, target {target:.3f}s.", flush=True)
    run([commands["ffmpeg"], "-hide_banner", "-loglevel", "warning", "-y",
         "-f", "concat", "-safe", "0", "-i", "frames.ffconcat", "-i", "narration.wav", "-i", "subtitles.srt",
         "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0", "-vf", f"fps={FPS}",
         "-frames:v", str(target_frames), "-t", f"{target:.9f}",
         "-c:v", "libx264", "-preset", "fast", "-tune", "stillimage", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-c:s", "mov_text", "-disposition:s:0", "0",
         "-metadata", f"title={title}", "-metadata", "comment=Edited screenshot highlights with separately synthesized macOS narration; not continuous real-time capture.",
         "-metadata:s:s:0", "language=eng", "-movflags", "+faststart", str(movie)], cwd=output_dir, timeout=900)
    probe = json.loads(run([commands["ffprobe"], "-v", "error", "-show_format", "-show_streams", "-of", "json", str(movie)]))
    duration = float(probe["format"]["duration"])
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    if duration > MAX_SECONDS + 0.000001 or abs(duration - target) > 1 / FPS + 0.002:
        raise RuntimeError(f"Encoded duration {duration:.6f}s failed the <=120s / target-duration check")
    if (video["width"], video["height"]) != (WIDTH, HEIGHT) or video.get("nb_frames") != str(target_frames):
        raise RuntimeError("Encoded dimensions or frame count did not match the declared export")
    receipt = {
        "created_at": datetime.now(timezone.utc).isoformat(), "title": title,
        "disclosure": "Edited screenshot highlights with synthesized narration; not continuous real-time capture.",
        "manifest": str(manifest), "manifest_sha256": digest(manifest),
        "video": str(movie), "video_sha256": digest(movie), "duration_s": duration,
        "target_duration_s": target, "width": WIDTH, "height": HEIGHT, "fps": FPS, "frames": target_frames,
        "video_codec": video["codec_name"], "audio_codec": audio["codec_name"],
        "narration": str(narration), "narration_sha256": digest(narration),
        "narration_engine": "macOS say", "voice": args.voice or "macOS system default", "speech_rate_wpm": args.rate,
        "subtitles": str(subtitles), "subtitles_sha256": digest(subtitles), "subtitle_cues": len(cues),
        "subtitle_timing": "Each caption uses its separately synthesized and measured speech segment; frame-aligned padding follows speech.",
        "facts_supplied_by_manifest": document.get("facts", {}),
        "scenes": [{"image": str(scene["image"]), "image_sha256": digest(scene["image"]), "heading": scene["heading"],
                    "narration": scene["narration"], "start_s": scene["start_frame"] / FPS,
                    "duration_s": scene["duration_frames"] / FPS, "requested_minimum_s": scene["requested_duration"]} for scene in scenes],
    }
    (output_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (output_dir / "ffprobe.json").write_text(json.dumps(probe, indent=2) + "\n")
    return {"video": str(movie), "duration_s": duration, "narration": str(narration),
            "subtitles": str(subtitles), "receipt": str(output_dir / "receipt.json")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--captures-dir", type=Path, help="Override the base for relative screenshot paths")
    parser.add_argument("--output-dir", type=Path, default=REPO / ".runtime/demo-video")
    parser.add_argument("--target-duration", type=float, default=120)
    parser.add_argument("--rate", type=int, default=164, help="macOS narration words/minute; default 164")
    parser.add_argument("--voice", help="An already available macOS say voice; default is the system voice")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--validate-only", action="store_true", help="Validate supplied paths/text without synthesizing or rendering")
    args = parser.parse_args()
    try:
        result = make_video(args)
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        print(f"Video assembly failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
