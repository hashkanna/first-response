from dataclasses import dataclass, field

from shop.app.catalog import get_product


@dataclass(frozen=True)
class Coupon:
    code: str


@dataclass
class Cart:
    items: dict[str, int] = field(default_factory=dict)
    coupon: Coupon | None = None

    def add(self, sku: str, quantity: int = 1) -> None:
        get_product(sku)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ValueError("Quantity must be a positive integer")
        self.items[sku] = self.items.get(sku, 0) + quantity

    @property
    def subtotal_cents(self) -> int:
        return sum(get_product(sku).price_cents * quantity for sku, quantity in self.items.items())
