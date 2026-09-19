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
VERIFICATION_BACKEND=modal ./scripts/dev.sh
```

Skip `modal setup` if this machine already has a working Modal profile. The SDK
uses that profile or its supported `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` environment
variables. Credentials belong on the host only; never put them in source control.
A browser login alone does not authenticate the Python SDK.

Run these commands from the repository root. If port 8000 is already occupied,
start with `VERIFICATION_BACKEND=modal WAR_ROOM_PORT=8001 ./scripts/dev.sh`.
The launcher sets the frontend to the matching hub port. When running the hub
separately, pass `--host 127.0.0.1 --port 8001` to uvicorn and set the frontend's
`VITE_HUB_URL=http://127.0.0.1:8001` in its environment or `web/.env.local`.

`--prepare-only` authenticates and builds the reusable Python 3.12 / pytest 8.4.2
image without running shop code. A fault check then launches one reproduction
sandbox followed by three candidate sandboxes in parallel. The script exits
unsuccessfully if the broken reproduction does not fail or the candidates do not
produce exactly one verified fix. This uses real Modal compute and credits.

Each candidate reports the actual reproduction plus regression count. The current
shop has 24 regression cases, so a candidate runs **25 checks** including its one
reproduction. The separately recorded browser fixtures retain their original
24-test rehearsal counts and are identified as recorded data.

## Boundary and lifecycle

`verification/modal_runner.py` mirrors the local runner's asynchronous
`check_reproduction` and `verify_candidate` signatures, including `apply=False`
for checking the runtime after human approval.

The runner captures the supplied broken shop directory before its first remote
await. It uploads only Python source plus the reproduction, validates relative
paths, rejects symlinks and limits upload size. It never uploads the repository
root, `.env`, git history, credentials or SQLite data. Each candidate receives an
independent copy of that snapshot; the authored exact-line edit is applied inside
the sandbox. The same unchanged regression suite tests every candidate. Logs
include a sandbox ID and the source snapshot's SHA-256 digest.

The image contains pytest before any tests start. Sandboxes request 0.25 CPU and
256 MiB, with limits of one CPU and 512 MiB. They have a 60-second lifetime,
20-second execution limits, no exposed ports, no mounted volumes, no injected
secrets or OIDC identity token, and outbound networking blocked. Both termination
and connection detachment run on success, failure and cancellation. The sandbox
lifetime also bounds remote execution if the host process disappears.

A reproduction counts only when pytest exits with a test failure and reports one
failed test; a collection error or timeout is insufficient. A candidate is offered
only when its edit applies and both the reproduction and full suite pass. Cloud
or infrastructure errors propagate to the hub as failures.

## Current limits

The two faults, reproductions and candidate edits are authored fixtures; the
investigator is not generating patches with an LLM. Modal is the real execution
and isolation layer. The payment provider is a deterministic toy function, so
this validates the rehearsed software behavior rather than production payments.

The runtime is copied from the supplied local snapshot rather than checking out a
remote commit. If you expand the app to arbitrary model-generated changes, retain
the network and credential boundary, use a trusted regression suite, and extend
the validated edit mechanism to the intended patch format.

## API references

The implementation follows the current official [Sandbox API](https://modal.com/docs/sdk/py/latest/Sandbox),
[networking controls](https://modal.com/docs/guide/sandbox-networking),
[filesystem API](https://modal.com/docs/guide/sandbox-files), and
[image build API](https://modal.com/docs/sdk/py/latest/Image).
