"""Local capture companion file and request boundaries; never calls a provider."""
import base64
import io
import json
from email.parser import Parser
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from scripts.demo_capture import CaptureStore, MAX_REQUEST_BYTES, ORIGIN, handler_for, jpeg_dimensions

# Small baseline JPEG with quantization/Huffman tables and a single image scan.
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////"
    "////////////////////////////////////////////////////2wBDAf//////////"
    "////////////////////////////////////////////////////////////////////"
    "////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAU"
    "EAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAA"
    "AAAAAAAAAAAAAAA A/9oADAMBAAIRAxEAPwCKAAf/2Q==".replace(" ", "")
)


def form(store, **changes):
    fields = {"nonce": [store.nonce], "name": ["01-incident"], "caption": ["Actual incident screen"], "frame": [base64.b64encode(JPEG).decode()]}
    fields.update({name: [value] for name, value in changes.items()})
    return fields


def test_real_jpeg_frame_saved_with_manifest_and_actual_save_time(tmp_path):
    store = CaptureStore(tmp_path / "captures")
    assert jpeg_dimensions(JPEG) == (1, 1)
    entry = store.save(form(store))
    assert (store.root / "01-incident.jpg").read_bytes() == JPEG
    assert entry["saved_at"].endswith("+00:00")
    assert entry["bytes"] == len(JPEG)
    assert json.loads((store.root / "manifest.json").read_text()) == [entry]


@pytest.mark.parametrize("changes,error", [
    ({"nonce": "wrong"}, PermissionError),
    ({"name": "../../escape"}, ValueError),
    ({"name": "/tmp/escape"}, ValueError),
    ({"name": ".hidden"}, ValueError),
    ({"frame": "<script>alert(1)</script>"}, ValueError),
    ({"frame": base64.b64encode(b"not a JPEG").decode()}, ValueError),
    ({"caption": "x" * 1001}, ValueError),
])
def test_invalid_submissions_write_nothing(tmp_path, changes, error):
    store = CaptureStore(tmp_path / "captures")
    with pytest.raises(error):
        store.save(form(store, **changes))
    assert not store.root.exists()


def test_existing_frame_and_symlinks_are_never_overwritten(tmp_path):
    store = CaptureStore(tmp_path / "captures")
    store.save(form(store))
    with pytest.raises(FileExistsError):
        store.save(form(store))
    outside = tmp_path / "outside"
    outside.write_text("keep")
    (store.root / "02-frame.jpg").symlink_to(outside)
    with pytest.raises(FileExistsError):
        store.save(form(store, name="02-frame"))
    assert outside.read_text() == "keep"


@pytest.mark.parametrize("data", [JPEG[:-1], JPEG + b"extra", b"\xff\xd8\xff\xd9", JPEG[:20] + b"\xff\xff" + JPEG[22:]])
def test_incomplete_or_malformed_jpeg_is_rejected(data):
    with pytest.raises(ValueError):
        jpeg_dimensions(data)


def test_duplicate_fields_and_oversized_decoded_payload_are_rejected(tmp_path):
    store = CaptureStore(tmp_path / "captures")
    fields = form(store)
    fields["nonce"].append(store.nonce)
    with pytest.raises(ValueError):
        store.save(fields)
    with pytest.raises(ValueError, match="4 MB"):
        store.save(form(store, frame=base64.b64encode(b"x" * (MAX_REQUEST_BYTES + 1)).decode()))


@pytest.fixture
def capture_server(tmp_path):
    store = CaptureStore(tmp_path / "captures")
    class Connection:
        def __init__(self, request):
            self.request = io.BytesIO(request)
            self.response = io.BytesIO()
        def makefile(self, *args): return self.request
        def sendall(self, data): self.response.write(data)
        def settimeout(self, timeout): pass
    def request(method="POST", body=None, headers=None):
        encoded = (body or "").encode()
        configured = {"Host": "127.0.0.1:9009", "Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(encoded))}
        configured.update(headers or {})
        path = "/save" if method == "POST" else "/"
        wire = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{name}: {value}\r\n" for name, value in configured.items()) + "\r\n"
        connection = Connection(wire.encode() + encoded)
        handler_for(store)(connection, ("127.0.0.1", 12345), SimpleNamespace())
        head, page = connection.response.getvalue().split(b"\r\n\r\n", 1)
        status_line, raw_headers = head.decode().split("\r\n", 1)
        return int(status_line.split()[1]), dict(Parser().parsestr(raw_headers)), page.decode()
    yield store, request


def test_http_form_requires_origin_nonce_and_rejects_cross_site(capture_server):
    store, request = capture_server
    body = urlencode({name: values[0] for name, values in form(store).items()})
    status, headers, page = request("GET")
    assert status == 200 and store.nonce in page
    assert "Access-Control-Allow-Origin" not in headers
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert request(body=body, headers={"Origin": "https://example.com"})[0] == 403
    assert request(body=body, headers={"Host": "evil.example:9009"})[0] == 403
    assert request(body=body, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert request(body=body.replace(store.nonce, "wrong"))[0] == 403
    assert not store.root.exists()
    assert request(body=body)[0] == 201
    assert request(body=body)[0] == 409


def test_http_rejects_oversized_and_chunked_bodies_before_reading(capture_server):
    store, request = capture_server
    assert request(headers={"Content-Length": str(MAX_REQUEST_BYTES + 1)})[0] == 413
    assert request(headers={"Transfer-Encoding": "chunked"})[0] == 415
    assert request(body="{}", headers={"Content-Type": "application/json"})[0] == 415
    assert not store.root.exists()
