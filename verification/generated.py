"""Bounded generated edits and immutable snapshot identity; never executes code.

The structural screen permits one existing assignment's expression to change.
It is defense in depth, not an execution sandbox. Generated code, including
recovery probes after approval, must execute only in Modal.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path, PurePosixPath

MAX_SOURCE_BYTES = 1_000_000
MAX_FILE_BYTES = 64_000
MAX_FILES = 200
MAX_EDIT_CHARS = 2000
TRUSTED_SHOP = Path(__file__).resolve().parents[1] / "shop"


@dataclass(frozen=True)
class GeneratedEdit:
    path: str
    before: str
    after: str


@dataclass(frozen=True)
class GeneratedPlan:
    candidate_id: str
    title: str
    rationale: str
    edit: GeneratedEdit
    base_sha256: str


def snapshot_files(shop_root: Path) -> dict[str, str]:
    if shop_root.is_symlink():
        raise ValueError("Symlinks are not allowed in verification source")
    root = shop_root.resolve(strict=True)
    files: dict[str, str] = {}
    total = 0
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
            raise ValueError("Symlinks are not allowed in verification source")
        if not path.resolve().is_relative_to(root):
            raise ValueError("Source escaped the shop root")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Verification source exceeds the bounded snapshot size")
        content = path.read_text()
        size = len(content.encode())
        total += size
        if size > MAX_FILE_BYTES or total > MAX_SOURCE_BYTES or len(files) >= MAX_FILES:
            raise ValueError("Verification source exceeds the bounded snapshot size")
        files[relative.as_posix()] = content
    if "__init__.py" not in files or "tests/test_shop.py" not in files or "probe.py" not in files:
        raise ValueError("Expected trusted shop source, probe and regression suite")
    return files


def fingerprint(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def snapshot_sha256(shop_root: Path) -> str:
    """Fingerprint the broken Python source and tests, excluding added repro code."""
    return fingerprint(snapshot_files(shop_root))


def _validate_trusted_files(files: dict[str, str]) -> None:
    # Model-editable source is restricted to existing application modules. Test,
    # package entrypoint and probe source must match the checked-in clean fixtures.
    expected = snapshot_files(TRUSTED_SHOP)
    if set(files) != set(expected):
        raise ValueError("Snapshot must contain exactly the trusted shop Python file set")
    for name, content in files.items():
        if not name.startswith("app/") or name.endswith("/__init__.py"):
            if content != expected[name]:
                raise ValueError(f"Trusted verification source changed: {name}")


def _path(edit: GeneratedEdit, files: dict[str, str]) -> str:
    if not isinstance(edit, GeneratedEdit) or not isinstance(edit.path, str):
        raise ValueError("A generated edit needs a canonical source path")
    path = PurePosixPath(edit.path)
    if (path.is_absolute() or ".." in path.parts or "\\" in edit.path
        or len(path.parts) != 2 or path.parts[0] != "app"
        or path.suffix != ".py" or path.name.startswith("_")
        or path.name.startswith("test") or path.name == "conftest.py"
        or str(path) != edit.path or str(path) not in files):
        raise ValueError("Generated edits may target only existing app/*.py modules, excluding entrypoints and tests")
    for value in (edit.before, edit.after):
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_EDIT_CHARS or any(c in value for c in "\n\r\0"):
            raise ValueError("Generated edits must contain one bounded nonempty source line")
    if edit.before.strip() == edit.after.strip():
        raise ValueError("Generated edit must change the source")
    return str(path)


def _replace(source: str, before: str, after: str) -> tuple[str, int]:
    lines = source.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.strip() == before.strip()]
    if len(matches) != 1:
        raise ValueError("Generated edit must match exactly one source line")
    i = matches[0]
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
    lines[i] = indent + after.strip() + ("\n" if lines[i].endswith("\n") else "")
    return "".join(lines), i + 1


def _screen_assignment(original: str, proposed: str, line: int) -> None:
    try:
        before_tree, after_tree = ast.parse(original), ast.parse(proposed)
    except SyntaxError as exc:
        raise ValueError("Generated edit must remain valid Python") from exc
    old = [node for node in ast.walk(before_tree) if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.lineno == line and node.end_lineno == line]
    new = [node for node in ast.walk(after_tree) if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.lineno == line and node.end_lineno == line]
    if len(old) != 1 or len(new) != 1 or old[0].value is None or new[0].value is None:
        raise ValueError("Generated repair may change only one existing single-line assignment")
    # Replace only the expression in a copy, then compare the entire tree. This
    # catches semicolons, target changes, new statements, imports and control flow.
    expected = copy.deepcopy(before_tree)
    assignment = next(node for node in ast.walk(expected) if type(node) is type(old[0]) and getattr(node, "lineno", None) == line)
    assignment.value = copy.deepcopy(new[0].value)
    if ast.dump(expected) != ast.dump(after_tree):
        raise ValueError("Generated repair cannot change assignment targets or surrounding structure")
    names = {node.id for node in ast.walk(old[0].value) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(old[0].value) if isinstance(node, ast.Attribute)}
    allowed = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Attribute, ast.IfExp,
               ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.UAdd, ast.USub,
               ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
               ast.Compare, ast.Eq, ast.NotEq, ast.Is, ast.IsNot, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
               ast.Call)
    nodes = list(ast.walk(new[0].value))
    if len(nodes) > 120:
        raise ValueError("Generated expression is too complex")
    for node in nodes:
        if not isinstance(node, allowed):
            raise ValueError(f"Generated expression uses unsupported structure: {type(node).__name__}")
        if isinstance(node, ast.Constant):
            if type(node.value) not in (str, int, float, bool, type(None)):
                raise ValueError("Unsupported generated constant")
            if isinstance(node.value, str) and len(node.value) > 2000:
                raise ValueError("Generated string is too long")
            if type(node.value) in (int, float) and not -1_000_000_000 <= node.value <= 1_000_000_000:
                raise ValueError("Generated numeric constant is out of bounds")
        if isinstance(node, ast.Name) and node.id not in names | {"getattr"}:
            raise ValueError("Generated expression references a new or dynamic name")
        if isinstance(node, ast.Attribute) and (node.attr not in attributes or node.attr.startswith("_")):
            raise ValueError("Generated expression references a new or private attribute")
        if isinstance(node, ast.Call):
            if (not isinstance(node.func, ast.Name) or node.func.id != "getattr" or node.keywords
                or len(node.args) != 3 or not isinstance(node.args[0], (ast.Name, ast.Attribute))
                or not isinstance(node.args[1], ast.Constant) or not isinstance(node.args[1].value, str)
                or node.args[1].value.startswith("_") or node.args[1].value not in attributes
                or not isinstance(node.args[2], ast.Constant) or node.args[2].value is not None):
                raise ValueError("Only getattr(existing_object, existing_attribute, None) is allowed")


def validated_snapshot(shop_root: Path, plan: GeneratedPlan, *, applied: bool = False) -> tuple[dict[str, str], dict[str, str]]:
    """Return immutable base/proposed data; recovery reconstructs the base in memory."""
    if not isinstance(plan, GeneratedPlan):
        raise ValueError("A GeneratedPlan is required")
    if not isinstance(plan.base_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", plan.base_sha256):
        raise ValueError("Generated plan needs a SHA256 source fingerprint")
    if not isinstance(plan.candidate_id, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,100}", plan.candidate_id):
        raise ValueError("Generated candidate identifier is invalid")
    if any(not isinstance(value, str) or not value.strip() or len(value) > limit for value, limit in ((plan.title, 200), (plan.rationale, 2000))):
        raise ValueError("Generated candidate metadata is empty or too long")
    files = snapshot_files(shop_root)
    _validate_trusted_files(files)
    name = _path(plan.edit, files)
    base = dict(files)
    if applied:
        base[name], _ = _replace(base[name], plan.edit.after, plan.edit.before)
    if fingerprint(base) != plan.base_sha256:
        raise ValueError("Generated plan belongs to a different or changed source snapshot")
    proposed, line = _replace(base[name], plan.edit.before, plan.edit.after)
    _screen_assignment(base[name], proposed, line)
    patched = {**base, name: proposed}
    if applied and files != patched:
        raise ValueError("Applied runtime differs from the generated plan")
    return base, patched


def validate_generated_plan(shop_root: Path, plan: GeneratedPlan) -> None:
    validated_snapshot(shop_root, plan)


def generated_patch(shop_root: Path, plan: GeneratedPlan) -> str:
    base, patched = validated_snapshot(shop_root, plan)
    path = plan.edit.path
    return "".join(unified_diff(base[path].splitlines(keepends=True), patched[path].splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}"))


def apply_generated_plan(shop_root: Path, plan: GeneratedPlan) -> None:
    """Write validated source as inert text. Never import, run or probe it here."""
    base, patched = validated_snapshot(shop_root, plan)
    # Open each editable directory/file without following a last-moment symlink.
    # The hub owns concurrent incident operations; this also rejects path swaps
    # between validation and opening the destination for an inert text write.
    root_fd = os.open(shop_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        app_fd = os.open("app", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            file_fd = os.open(PurePosixPath(plan.edit.path).name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=app_fd)
            with os.fdopen(file_fd, "r+", encoding="utf-8") as stream:
                if os.fstat(stream.fileno()).st_nlink != 1 or stream.read(MAX_FILE_BYTES + 1) != base[plan.edit.path]:
                    raise ValueError("Generated target changed after snapshot validation")
                stream.seek(0)
                stream.write(patched[plan.edit.path])
                stream.truncate()
        finally:
            os.close(app_fd)
    finally:
        os.close(root_fd)
