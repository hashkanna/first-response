# Toy-shop fault fixtures

These patches document the two known fault injections. The hub applies the same
exact edits from `agent/fixtures.py` to `.runtime/shop/`; it never changes the
checked-in shop. Candidate fixes are also authored fixtures, not generated code.

`bad_config.patch` changes the payment timeout from 3000 milliseconds to 3. The
local payment provider requires 80 milliseconds. Every one of the twelve probe
checkouts fails with `PaymentTimeout`.

`null_error.patch` removes the optional-coupon check. The six probe carts without
a coupon raise `AttributeError`; the six with a coupon still work.

The `.py.txt` files show the reproduction tests. The verifier writes these into
a separate working copy, proves they fail before proposing fixes, and executes
each candidate's reproduction and 24-test regression suite independently.

To trigger a fault with the hub running:

```sh
curl -X POST http://127.0.0.1:8000/faults/bad_config/apply
curl -X POST http://127.0.0.1:8000/faults/reset
curl -X POST http://127.0.0.1:8000/faults/null_error/apply
```

The runtime remains broken until an operator approves the verified candidate.
Approval reruns both test groups and twelve checkout probes before declaring
the incident resolved. It produces a downloadable patch, not a GitHub PR.
