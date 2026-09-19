"""Deterministic local payment provider; it never contacts a payment network."""

from shop.app.config import PAYMENT_TIMEOUT_MS

PROVIDER_LATENCY_MS = 80


class PaymentTimeout(TimeoutError):
    pass


def charge(amount_cents: int, *, latency_ms: int = PROVIDER_LATENCY_MS) -> dict:
    if amount_cents <= 0:
        raise ValueError("Payment amount must be positive")
    if latency_ms > PAYMENT_TIMEOUT_MS:
        raise PaymentTimeout(
            f"Payment provider needs {latency_ms} ms; timeout is {PAYMENT_TIMEOUT_MS} ms"
        )
    return {"status": "paid", "amount_cents": amount_cents, "provider": "local-fixture"}
