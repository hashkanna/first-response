"""Optional standalone clean shop: uvicorn shop.app.main:app --port 8001."""

import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from shop.app.cart import Cart, Coupon
from shop.app.catalog import list_products
from shop.app.checkout import checkout
from shop.app.payments import PaymentTimeout
from shop.app.store import save_order

app = FastAPI(title="Toy Shop", version="1.0.0")


class CheckoutInput(BaseModel):
    sku: str = "coffee"
    quantity: int = Field(default=1, ge=1, le=100)
    coupon: str | None = None


@app.get("/catalog")
def catalog():
    return [asdict(product) for product in list_products()]


@app.post("/checkout")
def checkout_route(body: CheckoutInput):
    cart = Cart(coupon=Coupon(body.coupon) if body.coupon else None)
    try:
        cart.add(body.sku, body.quantity)
        receipt = checkout(cart)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PaymentTimeout as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    runtime = Path(os.environ.get("WAR_ROOM_RUNTIME", ".runtime"))
    runtime.mkdir(parents=True, exist_ok=True)
    return {"order_id": save_order(runtime / "orders.sqlite3", receipt), **receipt}
