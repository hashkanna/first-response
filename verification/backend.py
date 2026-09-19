"""Explicit verification backend selection; cloud failures never fall back silently."""

import importlib
import os


def get_verifier():
    name = os.environ.get("VERIFICATION_BACKEND", "local").strip().lower()
    if name not in {"local", "modal"}:
        raise ValueError("VERIFICATION_BACKEND must be local or modal")
    module = importlib.import_module("verification.modal_runner" if name == "modal" else "verification.runner")
    return name, module
