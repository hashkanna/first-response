from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price_cents: int


PRODUCTS = {
    "coffee": Product("coffee", "Night shift coffee", 1200),
    "mug": Product("mug", "On-call mug", 1800),
    "notebook": Product("notebook", "Incident notebook", 900),
}


def get_product(sku: str) -> Product:
    if sku not in PRODUCTS:
        raise ValueError(f"Unknown product: {sku}")
    return PRODUCTS[sku]


def list_products() -> list[Product]:
    return list(PRODUCTS.values())
