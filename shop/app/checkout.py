from shop.app.cart import Cart
from shop.app.payments import charge


def checkout(cart: Cart) -> dict:
    if not cart.items:
        raise ValueError("Cannot check out an empty cart")
    coupon_code = cart.coupon.code if cart.coupon is not None else None
    subtotal = cart.subtotal_cents
    discount = subtotal // 10 if coupon_code == "SAVE10" else 0
    payment = charge(subtotal - discount)
    return {"subtotal_cents": subtotal, "discount_cents": discount, "payment": payment}
