"""Seed-red runner: prove each test by planting the defect it guards.

    bapu-seedred TABLE [--root DIR] [--only ID ...] [--json]
    bapu-seedred TABLE --check [--root DIR]

A table names, row by row, one planted defect and the one test that must catch it::

    {"rows": [{
        "id": "cap",
        "file": "retry.py",
        "anchor": "        if delay > cap:",
        "replacement": "        if False:",
        "test": "tests/test_retry.py::test_delays_never_exceed_the_cap",
        "why": "without the cap the delays grow without bound"
    }]}

For every row the runner:

1. checks that the anchor occurs exactly once in the file, starting at the beginning of a line;
2. runs the named test on the untouched file, which must pass ("before");
3. applies the replacement and runs the test again, which must FAIL ("after");
4. writes the original bytes back and verifies them byte for byte;
5. runs the test once more, which must pass ("restored").

A row is RED only when before=passed, after=failed and restored=passed. A mutation that stays
green is a finding about the TEST: it does not guard the line the row names. Outcomes are read
from pytest's final count line, never from its exit code: pytest also exits non-zero for a
collection error, and a mutation that merely breaks an import would otherwise look caught.

Nothing is mutated unless every selected row passes the static checks first: the anchor matches
exactly once, the replacement differs from it, a mutated ``.py`` file still compiles, the named
test file exists, and ids and rows are unique.

Exit codes: 0 every row RED; 1 at least one row NOT-RED; 2 an invalid table or usage error, a run
with no pytest result (a collection error, a crash or a timeout), a target file git could not
restore (uncommitted, untracked or ignored), or a file that could not be restored.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__

TOOL = "bapu-seedred"

PASSED, FAILED, NO_RESULT, TIMEOUT, NOT_RUN = "passed", "failed", "no-result", "timeout", "not-run"
RED, NOT_RED, NO_VERDICT, SKIPPED = "RED", "NOT-RED", "NO-RESULT", "SKIPPED"

ROW_KEYS = frozenset({"id", "file", "anchor", "replacement", "test", "why"})
REQUIRED_KEYS = ("id", "file", "anchor", "replacement", "test")

#: pytest's final count line in both renderings, ``==== 1 failed, 2 passed in 0.12s ====`` and
#: ``3 passed in 0.12s``, with the wall clock pytest appends past a minute. It must start with a
#: digit and end with the duration, which keeps ``no tests ran in 0.01s`` and warning summaries
#: out. The last matching line wins: a test that runs a nested pytest prints that run first.
_COUNT_LINE = re.compile(r"^(?:=+ )?\d+ \w+.* in \d+\.\d+s(?: \(\d+:\d{2}:\d{2}\))?(?: =+)?$")
_FAILED_COUNT = re.compile(r"(\d+) failed")
_PASSED_COUNT = re.compile(r"(\d+) passed")
#: pytest's short summary line for a failure, ``FAILED path::name - NameError: ...``.
_FAILED_LINE = re.compile(r"^FAILED .+? - (.*)$")
_EXCEPTION_NAME = re.compile(r"^([A-Za-z_][\w.]*)(?::|$)")

#: A mutated run that fails with one of these says the replacement broke the module (a typo, a
#: removed import), not that the test noticed the behaviour it guards.
BROKEN_MODULE = frozenset(
    {
        "NameError",
        "UnboundLocalError",
        "ImportError",
        "ModuleNotFoundError",
        "SyntaxError",
        "IndentationError",
        "TabError",
    }
)
_PREDEFINED = frozenset(dir(builtins)) | {
    "__annotations__",
    "__builtins__",
    "__class__",
    "__dict__",
    "__doc__",
    "__file__",
    "__loader__",
    "__module__",
    "__name__",
    "__package__",
    "__path__",
    "__qualname__",
    "__spec__",
}


class TableError(ValueError):
    """The table cannot be run as written."""


class RestoreError(RuntimeError):
    """A mutated file could not be put back exactly as it was."""


@dataclass(frozen=True)
class Row:
    id: str
    file: str
    anchor: str
    replacement: str
    test: str
    why: str = ""

    @property
    def test_file(self) -> str:
        return self.test.split("::", 1)[0]


#: ``runner(row) -> (outcome, output)``; the outcome is one of PASSED, FAILED, NO_RESULT, TIMEOUT.
Runner = Callable[[Row], tuple[str, str]]


def load_table(path: Path) -> list[Row]:
    """The rows of a JSON table: ``{"rows": [...]}`` or a bare list. ``anchor`` and
    ``replacement`` may be a string or a list of lines joined with newlines (end the list with
    ``""`` to include the final newline). TableError lists every problem at once."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise TableError(f"cannot read {path}: {exc}") from None
    raw_rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(raw_rows, list):
        raise TableError("expected {'rows': [...]} or a JSON list of rows")
    rows: list[Row] = []
    problems: list[str] = []
    for i, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            problems.append(f"row {i}: not a JSON object")
            continue
        unknown = sorted(set(raw) - ROW_KEYS)
        if unknown:
            problems.append(f"row {i}: unknown key(s) {unknown}")
        missing = [k for k in REQUIRED_KEYS if k not in raw]
        if missing:
            problems.append(f"row {i}: missing key(s) {missing}")
            continue
        rid = raw["id"]
        if isinstance(rid, bool) or not isinstance(rid, (str, int)) or not str(rid).strip():
            problems.append(f"row {i}: 'id' must be a non-empty string or an integer")
            continue
        values: dict[str, str] = {}
        for key in ("file", "test", "why"):
            value = raw.get(key, "")
            if not isinstance(value, str):
                problems.append(f"row {rid}: {key!r} must be a string")
                value = ""
            values[key] = value
        for key in ("anchor", "replacement"):
            value = raw[key]
            if isinstance(value, list) and all(isinstance(line, str) for line in value):
                value = "\n".join(value)
            if not isinstance(value, str):
                problems.append(f"row {rid}: {key!r} must be a string or a list of lines")
                value = ""
            values[key] = value
        rows.append(
            Row(
                str(rid),
                values["file"],
                values["anchor"],
                values["replacement"],
                values["test"],
                values["why"],
            )
        )
    if problems:
        raise TableError("\n".join(problems))
    return rows


def _aligned_starts(text: str, anchor: str) -> list[int]:
    """Offsets where ``anchor`` begins at the start of a line.

    Only the start is pinned. An anchor written at four spaces would otherwise also match the
    same statement indented to eight, and "exactly once" would pass for the wrong line. The end
    stays free: an anchor may stop mid-line or carry its own trailing newline.
    """
    starts = []
    index = text.find(anchor)
    while index != -1:
        if index == 0 or text[index - 1] == "\n":
            starts.append(index)
        index = text.find(anchor, index + 1)
    return starts


def count_anchor(text: str, anchor: str) -> int:
    """How many times ``anchor`` occurs in ``text`` starting at a line boundary."""
    return len(_aligned_starts(text, anchor)) if anchor else 0


def replace_anchor(text: str, anchor: str, replacement: str) -> str:
    """``text`` with the first line-aligned ``anchor`` replaced. It shares ``_aligned_starts``
    with ``count_anchor``, so what is counted is what is mutated."""
    starts = _aligned_starts(text, anchor) if anchor else []
    if not starts:
        return text
    return text[: starts[0]] + replacement + text[starts[0] + len(anchor) :]


def _inside(root: Path, rel: str) -> Path | None:
    """``root / rel`` when ``rel`` is a relative path that stays inside ``root``, else None."""
    if not rel or Path(rel).is_absolute():
        return None
    path = root / rel
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return path


def _read_text(path: Path) -> str:
    """The file as text that round-trips to the same bytes, whatever they are."""
    return path.read_bytes().decode("utf-8", "surrogateescape")


def new_undefined_names(original: str, mutated: str) -> list[str]:
    """Names the mutated module reads that nothing in it binds, that are not builtins, and that
    appear nowhere in the original text: a typo in a replacement, which would fail the test with
    a NameError instead of the defect. Module-wide, so it errs towards staying quiet."""
    try:
        tree = ast.parse(mutated)
    except (SyntaxError, ValueError):
        return []
    loaded: set[str] = set()
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (loaded if isinstance(node.ctx, ast.Load) else bound).add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.alias):
            bound.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif type(node).__name__.startswith("Match"):  # match-statement captures (3.10+)
            for attr in ("name", "rest"):
                value = getattr(node, attr, None)
                if isinstance(value, str):
                    bound.add(value)
    known = set(re.findall(r"[A-Za-z_]\w*", original)) | _PREDEFINED
    return sorted(loaded - bound - known)


def row_problems(row: Row, root: Path) -> list[str]:
    """Everything that stops one row from being a valid experiment, checked without running."""
    where = f"row {row.id}"
    problems: list[str] = []
    if not row.anchor:
        problems.append(f"{where}: the anchor is empty")
    elif row.replacement == row.anchor:
        problems.append(f"{where}: the replacement equals the anchor, so nothing is mutated")
    if "::" not in row.test:
        problems.append(f"{where}: test {row.test!r} is not a pytest node id (path::name)")
    target = _inside(root, row.file)
    if target is None:
        problems.append(f"{where}: file {row.file!r} is not a relative path inside the root")
    elif not target.is_file():
        problems.append(f"{where}: file {row.file} does not exist")
    elif row.anchor:
        text = _read_text(target)
        hits = count_anchor(text, row.anchor)
        if hits != 1:
            problems.append(
                f"{where}: anchor matches {hits} times in {row.file} "
                "(expected exactly 1, starting at the beginning of a line)"
            )
        elif target.suffix == ".py":
            mutated = replace_anchor(text, row.anchor, row.replacement)
            try:
                compile(mutated, row.file, "exec")
            except (SyntaxError, ValueError) as exc:
                problems.append(f"{where}: the mutated {row.file} does not compile ({exc})")
            else:
                undefined = new_undefined_names(text, mutated)
                if undefined:
                    problems.append(
                        f"{where}: the replacement uses {undefined}, which nothing in {row.file} "
                        "defines; the test would fail with a NameError, not because of the defect"
                    )
    test_path = _inside(root, row.test_file)
    if test_path is None or not test_path.is_file():
        problems.append(f"{where}: test file {row.test_file} does not exist")
    return problems


def table_problems(rows: list[Row], root: Path, selected: list[Row] | None = None) -> list[str]:
    """Problems of the whole table (empty, duplicate ids, duplicate rows) and of each selected
    row. One experiment written twice would count one claim twice in "N/N went red"."""
    problems: list[str] = []
    if not rows:
        problems.append("the table has no rows; nothing to check is not a pass")
    ids = [r.id for r in rows]
    repeated_ids = sorted({i for i in ids if ids.count(i) > 1})
    if repeated_ids:
        problems.append(f"ids used by more than one row: {repeated_ids}")
    seeds = [(r.file, r.anchor, r.replacement, r.test) for r in rows]
    repeated_rows = sorted({r.id for r, s in zip(rows, seeds) if seeds.count(s) > 1})
    if repeated_rows:
        problems.append(f"rows {repeated_rows} are the same experiment written twice")
    for row in rows if selected is None else selected:
        problems.extend(row_problems(row, root))
    return problems


def failure_of(output: str) -> str:
    """The exception pytest's short summary names for the last failing test ("AssertionError"
    for a plain assert), or "" when the output has no such line."""
    kinds = []
    for line in output.splitlines():
        match = _FAILED_LINE.match(line.strip())
        if match is None:
            continue
        message = match.group(1)
        if message.startswith("assert"):
            kinds.append("AssertionError")
            continue
        name = _EXCEPTION_NAME.match(message)
        kinds.append(name.group(1).rsplit(".", 1)[-1] if name else "")
    return kinds[-1] if kinds else ""


def outcome_of(output: str) -> str:
    """PASSED or FAILED from pytest's last count line; NO_RESULT when there is none, or when it
    reports only errors, skips or deselections."""
    counts = [s for s in (line.strip() for line in output.splitlines()) if _COUNT_LINE.match(s)]
    if counts:
        if _FAILED_COUNT.search(counts[-1]):
            return FAILED
        if _PASSED_COUNT.search(counts[-1]):
            return PASSED
    return NO_RESULT


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _child_env() -> dict[str, str]:
    # No bytecode is written by the runs, so none compiled from a mutation can outlive it. A
    # wide terminal keeps pytest from cutting the short summary line, which names the exception
    # a test failed with: cut to 80 columns, the name is usually gone.
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "COLUMNS": "4096"}


def _detail(output: str) -> str:
    """The last three lines worth reading, with runs of whitespace collapsed (the widened
    terminal pads pytest's progress line) and pytest's separator rules skipped."""
    lines = [" ".join(line.split())[:300] for line in output.splitlines()]
    lines = [line for line in lines if line and not re.match(r"^[=_-]{3,}", line)]
    return " | ".join(lines[-3:])


def pytest_runner(
    root: Path,
    python: str = sys.executable,
    timeout: float = 600.0,
    extra_args: tuple[str, ...] = (),
) -> Runner:
    """Run one named test in a fresh pytest process with ``root`` as the working directory."""

    def run(row: Row) -> tuple[str, str]:
        argv = [python, "-m", "pytest", row.test, "-q", "--no-header", "--tb=short"]
        argv += ["--color=no", "-p", "no:cacheprovider", *extra_args]
        try:
            proc = subprocess.run(
                argv,
                cwd=root,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                env=_child_env(),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            partial = _as_text(exc.stdout) + _as_text(exc.stderr)
            return TIMEOUT, f"{partial}\n(timed out after {timeout:g}s)"
        except OSError as exc:
            return NO_RESULT, f"could not start {python}: {exc}"
        output = proc.stdout + proc.stderr
        return outcome_of(output), output

    return run


def _drop_bytecode(path: Path) -> None:
    if path.suffix != ".py":
        return
    for compiled in (path.parent / "__pycache__").glob(f"{path.stem}.*.pyc"):
        with contextlib.suppress(OSError):
            compiled.unlink()


def _write_mutation(path: Path, data: bytes, stat: os.stat_result) -> None:
    with open(path, "wb") as handle:
        handle.write(data)
    # Cached bytecode is validated against the source's mtime in whole seconds and its size. An
    # mtime at least one second away from the original's means no bytecode compiled from the
    # original can stand in for the mutation, wherever the cache lives.
    mtime = max(time.time_ns(), stat.st_mtime_ns + 1_000_000_000)
    os.utime(path, ns=(stat.st_atime_ns, mtime))
    _drop_bytecode(path)


def _save_backup(path: Path, original: bytes) -> str:
    handle, name = tempfile.mkstemp(prefix="bapu-seedred-", suffix=f"-{path.name}")
    with os.fdopen(handle, "wb") as out:
        out.write(original)
    return name


class _Interrupts:
    """While a table runs, SIGINT, SIGTERM and SIGHUP raise KeyboardInterrupt, except during a
    restore: a signal that lands there is held until the file is back, because an exception in
    the middle of the write would leave the file neither mutated nor original."""

    def __init__(self) -> None:
        self.holding = False
        self.pending: int | None = None

    def handler(self, signum: int, frame: Any) -> None:
        if self.holding:
            self.pending = signum
            return
        raise KeyboardInterrupt(f"signal {signum}")


_INTERRUPTS = _Interrupts()


@contextlib.contextmanager
def _interrupts_held() -> Iterator[None]:
    _INTERRUPTS.holding = True
    try:
        yield
    finally:
        _INTERRUPTS.holding = False
        signum, _INTERRUPTS.pending = _INTERRUPTS.pending, None
    # Reached only when the restore succeeded; a failed restore raises RestoreError instead.
    if signum is not None:
        raise KeyboardInterrupt(f"signal {signum}")


def restore(path: Path, original: bytes, stat: os.stat_result) -> None:
    """Write ``original`` back with its timestamps and verify it byte for byte. When that fails
    the original bytes are saved to a temporary file whose path RestoreError names."""
    with _interrupts_held():
        problem = ""
        try:
            with open(path, "wb") as handle:
                handle.write(original)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            if path.read_bytes() != original:
                problem = "its bytes differ from the original after the restore"
        except OSError as exc:
            problem = f"the restore failed: {exc}"
        _drop_bytecode(path)
        if problem:
            backup = _save_backup(path, original)
            raise RestoreError(f"{path}: {problem}; the original bytes are saved at {backup}")


def row_verdict(before: str, after: str, restored: str) -> str:
    states = (before, after, restored)
    if any(s in (NO_RESULT, TIMEOUT) for s in states):
        return NO_VERDICT
    return RED if states == (PASSED, FAILED, PASSED) else NOT_RED


def reason(before: str, after: str, restored: str) -> str:
    if before in (NO_RESULT, TIMEOUT):
        return f"the run on the untouched file gave no pytest result ({before})"
    if before != PASSED:
        return "the test already fails on the untouched file, so its red proves nothing"
    if after in (NO_RESULT, TIMEOUT):
        return (
            f"the run with the defect planted gave no pytest result ({after}); a collection "
            "error, a crash or a hang is not a failing test"
        )
    if after == PASSED:
        return "the mutation survived: the test still passes with the defect planted"
    if restored in (NO_RESULT, TIMEOUT):
        return f"the run after the restore gave no pytest result ({restored})"
    if restored != PASSED:
        return "the test fails after the file was restored"
    return "the test fails with the defect planted and passes without it"


def run_row(row: Row, root: Path, runner: Runner) -> dict[str, Any]:
    """Before, after and restored runs for one row; the file is restored even on an exception."""
    path = root / row.file
    stat = path.stat()
    original = path.read_bytes()
    text = original.decode("utf-8", "surrogateescape")
    hits = count_anchor(text, row.anchor)
    if hits != 1:
        raise TableError(
            f"row {row.id}: anchor matches {hits} times in {row.file} (expected exactly 1); "
            "the file changed after the table was checked"
        )
    mutated = replace_anchor(text, row.anchor, row.replacement).encode("utf-8", "surrogateescape")
    before, output = runner(row)  # ``output`` ends up as the run that decided the verdict
    after, restored, failure = NOT_RUN, NOT_RUN, ""
    if before == PASSED:
        try:
            _write_mutation(path, mutated, stat)
            after, output = runner(row)
        finally:
            restore(path, original, stat)
        if after == FAILED:
            failure = failure_of(output)
        restored, restored_output = runner(row)
        if after == FAILED and restored != PASSED:
            output = restored_output
    verdict, why = row_verdict(before, after, restored), reason(before, after, restored)
    if verdict == RED and failure in BROKEN_MODULE:
        verdict = NOT_RED
        why = (
            f"the mutated run failed with {failure}: the replacement broke the module, which is "
            "not the behaviour the test claims to guard"
        )
    return {
        "id": row.id,
        "file": row.file,
        "test": row.test,
        "before": before,
        "after": after,
        "restored": restored,
        "failure": failure,
        "verdict": verdict,
        "reason": why,
        "detail": _detail(output),
    }


@contextlib.contextmanager
def _signals_raise() -> Iterator[None]:
    """While rows run, SIGINT, SIGTERM and SIGHUP (where it exists) raise KeyboardInterrupt, so
    the ``finally`` that restores a mutated file runs for all three; see ``_Interrupts``."""
    previous: dict[int, Any] = {}
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            previous[sig] = signal.signal(sig, _INTERRUPTS.handler)
        except (ValueError, OSError):  # not the main thread, or not supported here
            continue
    try:
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, signal.SIG_DFL if old is None else old)


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    def count(verdict: str) -> int:
        return sum(1 for r in results if r["verdict"] == verdict)

    return {
        "tool": TOOL,
        "tool_version": __version__,
        "mutations": len(results),
        "red": count(RED),
        "not_red": count(NOT_RED),
        "no_result": count(NO_VERDICT),
        "skipped": count(SKIPPED),
        "rows": results,
    }


def run_table(
    rows: list[Row],
    root: Path,
    runner: Runner,
    *,
    keep_going: bool = False,
    on_row: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run every row in order. A row with no pytest result stops the rest, which are SKIPPED,
    unless ``keep_going``: whatever swallowed that result is likely still there."""
    results: list[dict[str, Any]] = []
    stopped = False
    with _signals_raise():
        for row in rows:
            if stopped:
                result = {
                    "id": row.id,
                    "file": row.file,
                    "test": row.test,
                    "before": NOT_RUN,
                    "after": NOT_RUN,
                    "restored": NOT_RUN,
                    "failure": "",
                    "verdict": SKIPPED,
                    "reason": "not run: an earlier row gave no pytest result",
                    "detail": "",
                }
            else:
                result = run_row(row, root, runner)
                stopped = result["verdict"] == NO_VERDICT and not keep_going
            results.append(result)
            if on_row is not None:
                on_row(result)
    return summarise(results)


def exit_code(summary: dict[str, Any]) -> int:
    if summary["no_result"] or summary["skipped"]:
        return 2
    return 0 if summary["red"] == summary["mutations"] else 1


def uncollected(rows: list[Row], root: Path, python: str, timeout: float) -> list[str]:
    """Named tests pytest cannot collect: a renamed test rots exactly like a moved anchor."""
    problems = []
    for test in sorted({r.test for r in rows}):
        argv = [python, "-m", "pytest", "--collect-only", "-q", "--no-header", "--color=no"]
        argv += ["-p", "no:cacheprovider", test]
        try:
            proc = subprocess.run(
                argv,
                cwd=root,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                env=_child_env(),
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            problems.append(f"test {test}: collection did not finish ({exc})")
            continue
        collected = [line for line in proc.stdout.splitlines() if "::" in line]
        if proc.returncode != 0 or not collected:
            problems.append(f"test {test}: pytest collects nothing for it (renamed or removed?)")
    return problems


def dirty_targets(root: Path, files: list[str]) -> list[str] | None:
    """``git status`` lines for target files that git could not restore (uncommitted, untracked
    or ignored), or None when ``root`` is not inside a git work tree or git is not installed.
    Any other git failure is an error: "git could not tell" is not "nothing to protect"."""
    git = shutil.which("git")
    if git is None:
        return None
    env = {**os.environ, "LC_ALL": "C"}  # git's messages in English, so they can be read
    inside = subprocess.run(
        [git, "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if inside.returncode != 0:
        if "not a git repository" in inside.stderr.lower():
            return None
        raise TableError(f"git could not inspect {root}: {inside.stderr.strip()}")
    if inside.stdout.strip() != "true":
        return None
    status = subprocess.run(
        [git, "-C", str(root), "status", "--porcelain", "--ignored", "--untracked-files=all"]
        + ["--", *files],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if status.returncode != 0:
        raise TableError(f"git status failed in {root}: {status.stderr.strip()}")
    return [line for line in status.stdout.splitlines() if line.strip()]


def _print_row(result: dict[str, Any]) -> None:
    print(
        f"[{result['id']}] {result['verdict']:<9} before={result['before']} "
        f"after={result['after']} restored={result['restored']}  {result['test']}"
    )
    if result["verdict"] != RED:
        print(f"      {result['reason']}")
        if result["detail"]:
            print(f"      last output: {result['detail']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bapu-seedred",
        description="Prove tests by planting the defect each one guards: it must go red.",
        epilog=(
            "Exit codes: 0 every row RED, 1 a row NOT-RED, 2 invalid table, usage error, a run "
            "with no pytest result, a target git could not restore, or a failed restore."
        ),
    )
    parser.add_argument("table", type=Path, help="JSON table of rows")
    parser.add_argument(
        "--root", type=Path, default=Path("."), help="directory the table's paths are relative to"
    )
    parser.add_argument("--only", nargs="+", metavar="ID", help="run only these row ids")
    parser.add_argument(
        "--check", action="store_true", help="validate the table and collect its tests; no runs"
    )
    parser.add_argument("--python", default=sys.executable, help="interpreter that runs pytest")
    parser.add_argument(
        "--pytest-arg",
        action="append",
        default=[],
        metavar="ARG",
        help="extra pytest argument, repeatable; write --pytest-arg=-x",
    )
    parser.add_argument("--timeout", type=float, default=600.0, help="seconds per pytest run")
    parser.add_argument(
        "--keep-going", action="store_true", help="continue after a run with no pytest result"
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="run even when git could not restore a file the table mutates",
    )
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    root: Path = args.root
    if not root.is_dir():
        print(f"{TOOL}: --root {root} is not a directory", file=sys.stderr)
        return 2
    try:
        rows = load_table(args.table)
    except TableError as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    selected = rows
    if args.only:
        known = [r.id for r in rows]
        missing = [i for i in args.only if i not in known]
        if missing:
            print(
                f"{TOOL}: --only names ids that are not in the table: {missing}; "
                f"known ids: {', '.join(known)}",
                file=sys.stderr,
            )
            return 2
        selected = [r for r in rows if r.id in set(args.only)]
    problems = table_problems(rows, root, selected)

    if args.check:
        if not problems:
            problems = uncollected(selected, root, args.python, args.timeout)
        print(f"{len(selected)} rows checked, {len(problems)} problems")
        for problem in problems:
            print(f"  {problem}")
        return 0 if not problems else 2
    if problems:
        for problem in problems:
            print(f"{TOOL}: {problem}", file=sys.stderr)
        print(f"{TOOL}: nothing was mutated", file=sys.stderr)
        return 2
    if not args.allow_dirty:
        try:
            dirty = dirty_targets(root, sorted({r.file for r in selected}))
        except TableError as exc:
            print(f"{TOOL}: {exc}", file=sys.stderr)
            return 2
        if dirty:
            print(
                f"{TOOL}: git could not restore files this run would mutate (uncommitted, "
                "untracked or ignored):\n  "
                + "\n  ".join(dirty)
                + "\ncommit them first, or pass --allow-dirty",
                file=sys.stderr,
            )
            return 2

    runner = pytest_runner(root, args.python, args.timeout, tuple(args.pytest_arg))
    try:
        summary = run_table(
            selected,
            root,
            runner,
            keep_going=args.keep_going,
            on_row=None if args.json else _print_row,
        )
    except (RestoreError, TableError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"{TOOL}: interrupted; the file under mutation was restored", file=sys.stderr)
        return 130
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    else:
        print(f"\n{summary['red']}/{summary['mutations']} mutations went red")
        if summary["not_red"]:
            print(
                "A mutation that stays green is a finding about the test: it does not guard "
                "the line its row names. Suspect the test before the code.",
                file=sys.stderr,
            )
    return exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
