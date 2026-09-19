"""Opt-in loopback-only development setup; credentials live in process memory."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

COOKIE = "war_room_setup_session"
HEADERS = {
    "Cache-Control": "no-store", "Pragma": "no-cache",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "Referrer-Policy": "same-origin", "X-Content-Type-Options": "nosniff",
}
STYLE = "body{font:17px system-ui;background:#0b1014;color:#e7eef4;max-width:620px;margin:70px auto;padding:24px;line-height:1.6}h1{font-size:29px}input{display:block;background:#172129;color:white;border:1px solid #536370;border-radius:8px;padding:14px;width:94%;font-size:18px;margin:12px 0 22px}button{background:#b6f477;color:#162110;padding:13px 22px;border:0;border-radius:8px;font-size:17px;cursor:pointer}small{color:#a1b1bd}label{font-weight:600}"


def _loopback(address: str | None) -> bool:
    if not address:
        return False
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return address == "localhost"


def _check_local(request: Request) -> str:
    if os.getenv("WAR_ROOM_ENABLE_SETUP", "").lower() not in {"1", "true", "yes"}:
        raise HTTPException(404, "Not found")
    server = request.scope.get("server")
    if (not request.client or not _loopback(request.client.host)
            or not server or not _loopback(server[0])
            or not _loopback(request.url.hostname) or request.url.scheme != "http"):
        raise HTTPException(403, "Development setup is available only on a local loopback connection.")
    return f"{request.url.scheme}://{request.url.netloc}"


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>War Room · Local credential setup</title><style>{STYLE}</style><body>{body}</body></html>', headers=HEADERS)


def create_setup_router() -> APIRouter:
    router = APIRouter()
    sessions: dict[str, tuple[str, float]] = {}  # Single-use nonces, never API keys.

    @router.get("/setup", response_class=HTMLResponse)
    async def setup_page(request: Request) -> HTMLResponse:
        _check_local(request)
        now = time.monotonic()
        for identity in list(sessions):
            if sessions[identity][1] <= now:
                sessions.pop(identity, None)
        if len(sessions) > 64:
            sessions.clear()
        session_id, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[session_id] = (nonce, now + 300)
        configured = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        response = _page(
            '<small>DEVELOPMENT SETUP · LOOPBACK ONLY</small><h1>Connect the existing Gemini key</h1>'
            '<p>Paste the existing hackathon API key from Google AI Studio. It will be held only in this running server process and removed when the server stops. This page does not create a key.</p>'
            + ('<p>A key is already configured. Submitting another replaces it for this process.</p>' if configured else '')
            + f'<form method="post" action="/setup" autocomplete="off"><input type="hidden" name="csrf" value="{nonce}">'
            '<label for="api-key">Existing Gemini API key</label><input id="api-key" name="key" type="password" autocomplete="off" spellcheck="false" required minlength="20" maxlength="256">'
            '<button type="submit">Use key in memory</button></form>'
            '<small>The key is never returned, logged by this handler, or written to a file. Model access and quota are checked by Google when you start a real session.</small>'
        )
        response.set_cookie(COOKIE, session_id, max_age=300, httponly=True, samesite="strict", path="/setup")
        return response

    @router.post("/setup", response_class=HTMLResponse)
    async def configure_key(request: Request) -> HTMLResponse:
        origin = _check_local(request)
        referer = urlsplit(request.headers.get("referer", ""))
        if request.headers.get("origin") != origin or f"{referer.scheme}://{referer.netloc}" != origin or referer.path != "/setup":
            raise HTTPException(403, "Open the local setup page and submit its form directly.")
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"application/json", "application/x-www-form-urlencoded"}:
            raise HTTPException(415, "Use the local form or a JSON setup request.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4096:
                raise HTTPException(413, "Setup request is too large.")
        try:
            if content_type == "application/json":
                payload = json.loads(body)
            else:
                values = parse_qs(body.decode("utf-8"), strict_parsing=True, max_num_fields=3)
                payload = {name: items[0] for name, items in values.items() if len(items) == 1}
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid setup request.") from None
        if not isinstance(payload, dict):
            raise HTTPException(400, "Invalid setup request.")
        session_id = request.cookies.get(COOKIE, "")
        expected, supplied = sessions.get(session_id), payload.get("csrf")
        if not expected or expected[1] <= time.monotonic() or not isinstance(supplied, str) or not secrets.compare_digest(expected[0], supplied):
            raise HTTPException(403, "The setup form expired. Reload the page and try again.")
        key = payload.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{20,256}", key.strip()):
            raise HTTPException(400, "Enter the existing Google API key without surrounding text.")
        sessions.pop(session_id, None)
        os.environ["GEMINI_API_KEY"] = key.strip()
        response = _page(
            '<small>CONFIGURED IN MEMORY</small><h1>The existing key is connected</h1>'
            '<p>The server will use it for Gemini Live and the investigator. No key was saved to a file or returned to this page.</p>'
            '<p>Start a real Live session or investigation to verify model access. The key expires from this server when it stops.</p>'
            '<p>You can close this setup tab and return to the war room.</p>'
        )
        response.delete_cookie(COOKIE, path="/setup")
        return response

    return router
