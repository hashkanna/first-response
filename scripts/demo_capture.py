"""Development-only form for saving real browser screenshots on localhost.

Run ``.venv/bin/python -m scripts.demo_capture`` and open the printed URL.
Paste the base64 result of Page.captureScreenshot(format="jpeg") into the form.
No browser automation, uploads to third parties, or hub endpoints are involved.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import html
import json
import re
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

HOST, PORT = "127.0.0.1", 9009
ORIGIN = f"http://{HOST}:{PORT}"
MAX_REQUEST_BYTES = 4 * 1024 * 1024
CAPTURE_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "demo-captures"


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Validate JPEG marker/segment boundaries, dimensions, scans and final EOI."""
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("Frame must be a complete JPEG image")
    cursor, dimensions, saw_scan = 2, None, False
    while cursor < len(data):
        if data[cursor] != 0xFF:
            raise ValueError("Invalid JPEG marker")
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            raise ValueError("Truncated JPEG marker")
        marker = data[cursor]
        cursor += 1
        if marker == 0xD9:
            if cursor != len(data) or not saw_scan or dimensions is None:
                raise ValueError("JPEG is missing image data or has trailing content")
            return dimensions
        if marker in (0, 0xD8) or 0xD0 <= marker <= 0xD7:
            raise ValueError("Unexpected JPEG marker")
        if cursor + 2 > len(data):
            raise ValueError("Truncated JPEG segment")
        length = int.from_bytes(data[cursor:cursor + 2], "big")
        if length < 2 or cursor + length > len(data):
            raise ValueError("Invalid JPEG segment length")
        segment = data[cursor + 2:cursor + length]
        cursor += length
        if marker in (0xC0, 0xC1, 0xC2):
            if len(segment) < 6:
                raise ValueError("Invalid JPEG image header")
            height, width = int.from_bytes(segment[1:3], "big"), int.from_bytes(segment[3:5], "big")
            components = segment[5]
            if not 1 <= width <= 16384 or not 1 <= height <= 16384 or components not in (1, 3, 4) or len(segment) != 6 + 3 * components:
                raise ValueError("Unsupported JPEG dimensions or components")
            dimensions = width, height
        if marker == 0xDA:
            if dimensions is None or len(segment) < 4 or len(segment) != 4 + 2 * segment[0]:
                raise ValueError("Invalid JPEG scan header")
            saw_scan = True
            # Entropy data escapes FF as FF00. Restart markers belong to scans.
            while cursor < len(data):
                if data[cursor] != 0xFF:
                    cursor += 1
                    continue
                next_byte = cursor + 1
                while next_byte < len(data) and data[next_byte] == 0xFF:
                    next_byte += 1
                if next_byte >= len(data):
                    raise ValueError("Truncated JPEG scan")
                if data[next_byte] == 0 or 0xD0 <= data[next_byte] <= 0xD7:
                    cursor = next_byte + 1
                    continue
                break
    raise ValueError("JPEG end marker is missing")


class CaptureStore:
    def __init__(self, root: Path = CAPTURE_ROOT):
        self.root = root
        self.nonce = secrets.token_urlsafe(32)
        self.lock = threading.Lock()

    def save(self, fields: dict[str, list[str]]) -> dict:
        if set(fields) != {"nonce", "name", "caption", "frame"} or any(len(values) != 1 for values in fields.values()):
            raise ValueError("Expected one nonce, name, caption and frame")
        if not hmac.compare_digest(fields["nonce"][0], self.nonce):
            raise PermissionError("Invalid form nonce; reload this page")
        name, caption = fields["name"][0].strip(), fields["caption"][0].strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
            raise ValueError("Name must use 1–80 letters, numbers, underscores or hyphens")
        if len(caption) > 1000 or any(ord(char) < 32 and char not in "\n\t" for char in caption):
            raise ValueError("Caption must be at most 1000 characters")
        encoded = fields["frame"][0].strip()
        if encoded.startswith("data:image/jpeg;base64,"):
            encoded = encoded.removeprefix("data:image/jpeg;base64,")
        try:
            frame = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Frame must contain valid JPEG base64") from exc
        if not frame or len(frame) > MAX_REQUEST_BYTES:
            raise ValueError("Frame exceeds the 4 MB limit")
        width, height = jpeg_dimensions(frame)
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            if self.root.is_symlink():
                raise ValueError("Capture directory cannot be a symlink")
            manifest_path = self.root / "manifest.json"
            if manifest_path.is_symlink():
                raise ValueError("Capture manifest cannot be a symlink")
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
            if not isinstance(manifest, list):
                raise ValueError("Existing manifest must be an array")
            destination = self.root / f"{name}.jpg"
            # Exclusive creation prevents accidental overwrites and follows no symlink.
            with destination.open("xb") as stream:
                stream.write(frame)
            entry = {"name": name, "file": destination.name, "caption": caption,
                     "saved_at": datetime.now(timezone.utc).isoformat(),
                     "bytes": len(frame), "width": width, "height": height,
                     "source": "Browser screenshot supplied through localhost capture form"}
            manifest.append(entry)
            temporary = self.root / f".manifest-{secrets.token_hex(8)}.json"
            try:
                with temporary.open("x") as stream:
                    json.dump(manifest, stream, indent=2)
                    stream.write("\n")
                temporary.replace(manifest_path)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
            finally:
                temporary.unlink(missing_ok=True)
            return entry


def handler_for(store: CaptureStore):
    class CaptureHandler(BaseHTTPRequestHandler):
        server_version = "LocalCapture/1.0"

        def log_message(self, format, *args):
            # Never log screenshot payloads, captions, or form tokens.
            pass

        def respond(self, status: int, message: str = "") -> None:
            page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>First Response · demo capture</title>
<style>body{{font:16px system-ui;background:#101720;color:#edf3fa;max-width:900px;margin:48px auto;padding:0 24px}}label{{display:block;margin:20px 0 6px}}input,textarea{{box-sizing:border-box;width:100%;padding:12px;background:#1b2633;color:inherit;border:1px solid #496071;border-radius:6px}}button{{margin-top:20px;padding:12px 20px;font:inherit;background:#7ae5c3;border:0;border-radius:6px}}p{{line-height:1.6}}output{{display:block;color:#7ae5c3}}</style>
<h1>Save a real demo frame</h1><p>Local capture companion. Paste JPEG base64 from the browser screenshot. Files stay in <code>.runtime/demo-captures/</code>. Maximum request size: 4 MB.</p>
<output>{html.escape(message)}</output><form action="/save" method="post">
<input type="hidden" name="nonce" value="{store.nonce}">
<label for="name">Frame name</label><input id="name" name="name" required maxlength="80" pattern="[A-Za-z0-9][A-Za-z0-9_-]*" placeholder="01-alert">
<label for="caption">Caption</label><input id="caption" name="caption" maxlength="1000" placeholder="The checkout incident begins">
<label for="frame">JPEG frame (base64)</label><textarea id="frame" name="frame" rows="16" required spellcheck="false"></textarea>
<button type="submit">Save frame</button></form></html>"""
            encoded = page.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)
            self.close_connection = True

        def do_GET(self):
            if self.headers.get("Host") != f"{HOST}:{PORT}":
                return self.respond(403, "Open the companion using its localhost URL")
            if self.path != "/":
                return self.respond(404, "Page not found")
            self.respond(200)

        def do_POST(self):
            if (self.path != "/save" or self.headers.get("Host") != f"{HOST}:{PORT}"
                or self.headers.get("Origin") != ORIGIN
                or self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin"):
                return self.respond(403, "Only a submission from this localhost form is accepted")
            if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/x-www-form-urlencoded":
                return self.respond(415, "Use the provided HTML form")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.respond(400, "Invalid request length")
            if not 0 < length <= MAX_REQUEST_BYTES:
                return self.respond(413, "Request exceeds the 4 MB limit")
            self.connection.settimeout(10)
            try:
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError("Incomplete form submission")
                fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True, strict_parsing=True, max_num_fields=4)
                entry = store.save(fields)
            except PermissionError as exc:
                return self.respond(403, str(exc))
            except FileExistsError:
                return self.respond(409, "That frame name already exists; choose a new name")
            except (ValueError, UnicodeError, TimeoutError) as exc:
                return self.respond(400, str(exc))
            except OSError:
                return self.respond(500, "Unable to save the local frame")
            self.respond(201, f"Saved {entry['file']} · {entry['width']} × {entry['height']} · {entry['saved_at']}")

    return CaptureHandler


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), handler_for(CaptureStore()))
    print(f"Local demo capture: {ORIGIN}/", flush=True)
    print(f"Saved frames: {CAPTURE_ROOT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
