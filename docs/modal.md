# Modal verification

Set `VERIFICATION_BACKEND=modal` to run the broken-code reproduction and each
candidate in real Modal Sandboxes. The `local` backend remains an explicit option
for the reviewed fixture code. A Modal error fails the investigation; the hub does
not silently substitute local execution or recorded results.

## Setup and check

Use the same project interpreter for dependencies, authentication checks, and the hub:

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m modal setup
.venv/bin/python -m scripts.check_modal --prepare-only
.venv/bin/python -m scripts.check_modal --fault bad_config
.venv/bin/python -m scripts.check_modal --fault null_error
VERIFICATION_BACKEND=modal REPAIR_BACKEND=authored ./scripts/dev.sh
```

Skip `modal setup` if this machine already has a working Modal profile. The SDK
uses that profile or its supported `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` environment
variables. Credentials belong on the host only; never put them in source control.
A browser login alone does not authenticate the Python SDK.

Run these commands from the repository root. If port 8000 is already occupied,
start with `VERIFICATION_BACKEND=modal REPAIR_BACKEND=authored WAR_ROOM_PORT=8001 ./scripts/dev.sh`.
The launcher sets the frontend to the matching hub port. When running the hub
separately, pass `--host 127.0.0.1 --port 8001` to uvicorn and set the frontend's
`VITE_HUB_URL=http://127.0.0.1:8001` in its environment or `web/.env.local`.

`--prepare-only` authenticates and builds the reusable Python 3.12 / pytest 8.4.2
image without running shop code. Each `--fault` check uses the authored fixture
repairs and launches one reproduction sandbox followed by three candidate
sandboxes in parallel. The script exits
unsuccessfully if the broken reproduction does not fail or the candidates do not
produce exactly one verified authored fix. This uses real Modal compute and credits.
It checks the verifier, not Gemini repair generation. To run generated repairs
through the hub, choose `REPAIR_BACKEND=gemini` with Modal and working Gemini
credentials; zero, one or several generated candidates may pass.

Each candidate reports the actual reproduction plus regression count. The current
shop has 24 regression cases, so a candidate runs **25 checks** including its one
reproduction. The separately recorded browser fixtures retain their original
24-test rehearsal counts and are identified as recorded data.

## Boundary and lifecycle

`verification/modal_runner.py` mirrors the local runner's asynchronous
`check_reproduction` and `verify_candidate` signatures, including `apply=False`
for checking the runtime after human approval.
Generated plans use `verify_generated`; `verify_generated_recovery` repeats both
pytest checks and the 12 checkout probes inside Modal after approval. The local
runner rejects generated plans and source outside the reviewed fixture variants.

The runner captures the supplied broken shop directory before its first remote
await. It uploads only Python source plus the reproduction, validates relative
paths, rejects symlinks and limits upload size. It never uploads the repository
root, `.env`, git history, credentials or SQLite data. Each candidate receives an
independent copy of that snapshot; the selected exact-line edit is applied as data
by trusted bootstrap code inside the sandbox. The same unchanged regression suite
tests every candidate. Logs include a sandbox ID and a SHA256 digest. Authored
smoke checks hash the uploaded source plus reproduction; generated plans share a
base digest of the original Python source and immutable suite/probe, excluding
the separately supplied trusted reproduction.

Generated edits are screened on the host as text and AST data. They may change one
existing assignment expression in an existing application module. Tests, probes,
entrypoints and imports remain unchanged. Snapshot binding and symlink-safe writes
guard approval; neither generated modules nor their recovery probes are imported
or executed on the host. The structural screen is defense in depth; Modal supplies
the execution isolation. See [generated repairs](repair-generation.md).

The image contains pytest before any tests start. Sandboxes request 0.25 CPU and
256 MiB, with limits of one CPU and 512 MiB. They have a 60-second lifetime,
20-second execution limits, no exposed ports, no mounted volumes, no injected
secrets or OIDC identity token, and outbound networking blocked. Both termination
and connection detachment run on success, failure and cancellation. The sandbox
lifetime also bounds remote execution if the host process disappears.

A reproduction counts only when pytest exits with a test failure and reports one
failed test; a collection error or timeout is insufficient. A candidate is offered
only when its edit applies, both the reproduction and full suite pass, tests
actually ran and no failures were reported. Cloud
or infrastructure errors propagate to the hub as failures.

## Current limits

The two faults and verification tests remain authored fixtures. Repair candidates
are either authored alternatives or actual Gemini-generated bounded edits,
selected explicitly by `REPAIR_BACKEND`. Both faults have completed generated
verification and recovery in Modal; see [actual execution evidence](generated-run-evidence.md).
The payment provider is a deterministic toy function, so passing demonstrates the
controlled shop behavior rather than production payment safety.

The runtime is copied from the supplied local snapshot rather than checking out a
remote commit. If you expand the app to arbitrary model-generated changes, retain
the network and credential boundary, use a trusted regression suite, and extend
the validated edit mechanism to the intended patch format.

## API references

The implementation follows the current official [Sandbox API](https://modal.com/docs/sdk/py/latest/Sandbox),
[networking controls](https://modal.com/docs/guide/sandbox-networking),
[filesystem API](https://modal.com/docs/guide/sandbox-files), and
[image build API](https://modal.com/docs/sdk/py/latest/Image).
