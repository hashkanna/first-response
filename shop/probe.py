"""Exercise the currently loaded shop and report actual exceptions as JSON."""

import json
import time
import traceback

from shop.app.cart import Cart, Coupon
from shop.app.checkout import checkout


def probe() -> dict:
    records = []
    for index in range(12):
        cart = Cart(coupon=Coupon("SAVE10") if index % 2 else None)
        cart.add("coffee")
        started = time.perf_counter()
        try:
            receipt = checkout(cart)
            records.append({"ok": True, "coupon": bool(cart.coupon), "amount_cents": receipt["payment"]["amount_cents"]})
        except Exception as exc:
            records.append({"ok": False, "coupon": bool(cart.coupon), "exception": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        records[-1]["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    failed = sum(not record["ok"] for record in records)
    return {"requests": len(records), "failed": failed, "error_rate": failed / len(records), "records": records}


if __name__ == "__main__":
    print(json.dumps(probe()))
