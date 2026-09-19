import pytest

from shop.app.cart import Cart, Coupon
from shop.app.catalog import get_product, list_products
from shop.app.checkout import checkout
from shop.app.config import PAYMENT_TIMEOUT_MS
from shop.app.payments import PaymentTimeout, charge
from shop.app.store import get_order, save_order


def test_catalog_has_three_products():
    assert len(list_products()) == 3


def test_coffee_price():
    assert get_product("coffee").price_cents == 1200


def test_unknown_product():
    with pytest.raises(ValueError):
        get_product("unknown")


def test_catalog_prices_are_positive():
    assert all(product.price_cents > 0 for product in list_products())


def test_cart_starts_empty():
    assert Cart().subtotal_cents == 0


def test_cart_add():
    cart = Cart()
    cart.add("coffee")
    assert cart.subtotal_cents == 1200


def test_cart_accumulates():
    cart = Cart()
    cart.add("coffee", 2)
    cart.add("coffee")
    assert cart.items == {"coffee": 3}


def test_cart_mixed_products():
    cart = Cart()
    cart.add("coffee")
    cart.add("mug")
    assert cart.subtotal_cents == 3000


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True])
def test_cart_rejects_invalid_quantity(quantity):
    with pytest.raises(ValueError):
        Cart().add("coffee", quantity)


def test_cart_instances_are_independent():
    first, second = Cart(), Cart()
    first.add("mug")
    assert second.items == {}


def test_empty_checkout_is_rejected():
    with pytest.raises(ValueError):
        checkout(Cart())


def test_checkout_without_coupon():
    cart = Cart()
    cart.add("coffee")
    assert checkout(cart)["payment"]["amount_cents"] == 1200


def test_checkout_with_coupon():
    cart = Cart(coupon=Coupon("SAVE10"))
    cart.add("mug")
    assert checkout(cart)["payment"]["amount_cents"] == 1620


def test_unknown_coupon_has_no_discount():
    cart = Cart(coupon=Coupon("UNKNOWN"))
    cart.add("mug")
    assert checkout(cart)["discount_cents"] == 0


def test_discount_is_integer_cents():
    cart = Cart(coupon=Coupon("SAVE10"))
    cart.add("notebook")
    assert checkout(cart)["discount_cents"] == 90


def test_payment_success():
    assert charge(500)["status"] == "paid"


def test_payment_rejects_zero():
    with pytest.raises(ValueError):
        charge(0)


def test_provider_timeout_remains_enforced():
    with pytest.raises(PaymentTimeout):
        charge(500, latency_ms=5000)


def test_timeout_has_reasonable_budget():
    assert 1000 <= PAYMENT_TIMEOUT_MS <= 5000


def test_order_round_trip(tmp_path):
    path = tmp_path / "orders.sqlite3"
    order = {"amount": 100}
    order_id = save_order(path, order)
    assert get_order(path, order_id) == order


def test_missing_order(tmp_path):
    path = tmp_path / "orders.sqlite3"
    save_order(path, {"amount": 100})
    assert get_order(path, 999) is None
