"""Bound provider errors before exposing them in incident events."""

import os
import re


def safe_error_detail(error: Exception, limit: int = 300) -> str:
    detail = str(error)
    # Providers normally redact credentials themselves. Do not depend on that
    # behavior when an HTTP error or adapter exception reaches the browser.
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "PYDANTIC_AI_GATEWAY_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "LOGFIRE_TOKEN"):
        if value := os.environ.get(name):
            detail = detail.replace(value, "[redacted]")
    detail = re.sub(r"(?i)([?&](?:key|api_key|token)=)[^\s&\"']+", r"\1[redacted]", detail)
    detail = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]", detail)
    return detail[:limit]
