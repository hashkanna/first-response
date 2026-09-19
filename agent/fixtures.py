"""Authored faults, reproductions and candidate edits, never model-written code."""

from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

from core.contracts import FixCandidate, ReproTest

TIMEOUT_CLEAN = "PAYMENT_TIMEOUT_MS = 3000"
TIMEOUT_BROKEN = "PAYMENT_TIMEOUT_MS = 3"
COUPON_CLEAN = "coupon_code = cart.coupon.code if cart.coupon is not None else None"
COUPON_BROKEN = "coupon_code = cart.coupon.code"


@dataclass(frozen=True)
class Edit:
    path: str
    before: str
    after: str


@dataclass(frozen=True)
class CandidatePlan:
    candidate_id: str
    title: str
    rationale: str
    edit: Edit


@dataclass(frozen=True)
class FaultFixture:
    name: str
    title: str
    edit: Edit
    service: str
    explanation: str
    repro_code: str
    candidates: tuple[CandidatePlan, ...]


FIXTURES = {
    "bad_config": FaultFixture(
        name="bad_config",
        title="Payment timeout regression",
        edit=Edit("app/config.py", TIMEOUT_CLEAN, TIMEOUT_BROKEN),
        service="payments",
        explanation="The payment timeout changed from 3000 ms to 3 ms. The local provider requires 80 ms, so checkout raises PaymentTimeout.",
        repro_code='''from shop.app.cart import Cart
from shop.app.checkout import checkout

def test_repro_payment_timeout():
    cart = Cart()
    cart.add("coffee")
    assert checkout(cart)["payment"]["status"] == "paid"
''',
        candidates=(
            CandidatePlan("timeout-30ms", "Raise timeout to 30 ms", "Try a small timeout increase while keeping a tight budget.", Edit("app/config.py", TIMEOUT_BROKEN, "PAYMENT_TIMEOUT_MS = 30")),
            CandidatePlan("timeout-unbounded", "Relax timeout to five minutes", "Give the provider a much larger response window; verify that the timeout guard still works.", Edit("app/config.py", TIMEOUT_BROKEN, "PAYMENT_TIMEOUT_MS = 300000")),
            CandidatePlan("timeout-restore", "Restore the 3000 ms budget", "Restore the known timeout budget while preserving slow-provider rejection.", Edit("app/config.py", TIMEOUT_BROKEN, TIMEOUT_CLEAN)),
        ),
    ),
    "null_error": FaultFixture(
        name="null_error",
        title="Missing coupon regression",
        edit=Edit("app/checkout.py", COUPON_CLEAN, COUPON_BROKEN),
        service="checkout",
        explanation="Checkout reads cart.coupon.code without checking whether a coupon exists. Carts without a coupon raise AttributeError before payment.",
        repro_code='''from shop.app.cart import Cart
from shop.app.checkout import checkout

def test_repro_missing_coupon():
    cart = Cart()
    cart.add("coffee")
    receipt = checkout(cart)
    assert receipt["payment"]["amount_cents"] == 1200
    assert receipt["discount_cents"] == 0
''',
        candidates=(
            CandidatePlan("coupon-empty-code", "Default an empty coupon code", "Fall back when the code is empty; test whether this also handles an absent coupon.", Edit("app/checkout.py", COUPON_BROKEN, 'coupon_code = cart.coupon.code or ""')),
            CandidatePlan("coupon-disable", "Bypass coupon lookup", "Avoid coupon access; check that valid discounts still behave correctly.", Edit("app/checkout.py", COUPON_BROKEN, "coupon_code = None")),
            CandidatePlan("coupon-guard", "Guard the optional coupon", "Read the code only when a coupon exists and preserve all valid discounts.", Edit("app/checkout.py", COUPON_BROKEN, COUPON_CLEAN)),
        ),
    ),
}


def apply_edit(root: Path, edit: Edit) -> None:
    target = root / edit.path
    original = target.read_text()
    # Exact line replacement prevents the 3 ms edit from matching 3000 ms.
    lines = original.splitlines(keepends=True)
    matched = [index for index, line in enumerate(lines) if line.strip() == edit.before]
    if len(matched) != 1:
        raise ValueError(f"Expected one authored edit location in {edit.path}; found {len(matched)}")
    index = matched[0]
    indent = lines[index][:len(lines[index]) - len(lines[index].lstrip())]
    newline = "\n" if lines[index].endswith("\n") else ""
    lines[index] = indent + edit.after + newline
    target.write_text("".join(lines))


def patch_for(root: Path, edit: Edit) -> str:
    original = (root / edit.path).read_text()
    lines = original.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.strip() == edit.before]
    if len(matches) != 1:
        raise ValueError("Fixture base does not match the active runtime")
    index = matches[0]
    indent = lines[index][:len(lines[index]) - len(lines[index].lstrip())]
    lines[index] = indent + edit.after + ("\n" if lines[index].endswith("\n") else "")
    return "".join(unified_diff(original.splitlines(keepends=True), lines, fromfile=f"a/{edit.path}", tofile=f"b/{edit.path}"))


def build_candidates(root: Path, fixture: FaultFixture) -> list[FixCandidate]:
    return [FixCandidate(candidate_id=plan.candidate_id, title=plan.title, rationale=plan.rationale, patch=patch_for(root, plan.edit), files_touched=[f"shop/{plan.edit.path}"]) for plan in fixture.candidates]


def repro_for(fixture: FaultFixture) -> ReproTest:
    return ReproTest(path=f"tests/test_repro_{fixture.name}.py", code=fixture.repro_code)
