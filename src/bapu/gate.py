"""Clause gate: check OpenSpec delta specs clause by clause before any code is written.

    bapu-gate PATH [--specs-dir DIR] [--json]
    bapu-gate PATH --online [--model ID] [--receipt FILE | --no-receipt] [--json]
    bapu-gate PATH --check-receipt [--receipt FILE] [--model ID]
    bapu-gate --self-test [--online]

PATH is an OpenSpec change directory (its delta specs are ``specs/**/spec.md``) or one spec file.

Offline (the default; no key, no network) the gate checks structure only:

* inside a ``#### Scenario:`` block every non-blank line is one ``- **GIVEN|WHEN|THEN|AND**`` step;
* every requirement, except a REMOVED one, has at least one scenario;
* every scenario has a WHEN step and a THEN step;
* a delta that creates a new capability has a ``## Purpose`` section;
* headings use the exact forms ``### Requirement: <name>`` and ``#### Scenario: <name>`` with an
  ASCII colon, operation headings are ``## ADDED|MODIFIED|REMOVED|RENAMED Requirements``, and no
  scenario sits outside a requirement;
* every delta spec holds at least one requirement.

Verdict STRUCTURE-OK (exit 0) or HOLD (exit 1).

Online (``--online``; needs TYPESAFE_API_KEY) every requirement of a structurally sound delta is
also scored by Jev, one observable property per question:

  per requirement  single_behavior  one SHALL/MUST, one behaviour
                   observable       decidable from outside by someone who never read the code
                   no_impl_detail   no internal names, library choices or algorithms
  per scenario     exercises        a concrete case with a concrete outcome, not a restatement
                   testable         a test could set up the WHEN and observe the THEN

Each requirement is asked twice, once in the original wording and once in a paraphrase of the
same questions; the stored score is the lower of the two. A clause HOLDs when either ask is below
THRESHOLD (0.5) or inside HOLD_BAND (0.45 to 0.55, both ends included). Verdict PASS (exit 0),
HOLD (exit 1), or PASS-UNJUDGED (exit 1) when nothing was judged. The online run writes a receipt
that ``--check-receipt`` later re-derives offline against the files as they are.

Exit codes: 0 pass, 1 hold, 2 usage error, missing input or no judgment from the API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__, jev

THRESHOLD = 0.5
#: Either ask landing here, both ends included, holds the clause: a score this close to the
#: threshold can cross it when the question is merely reworded.
HOLD_BAND = (0.45, 0.55)
STATISTIC = "min of the original and the paraphrase ask"
REQ_KEYS = ("single_behavior", "observable", "no_impl_detail")
SCN_KEYS = ("exercises", "testable")
RECEIPT_NAME = ".bapu-gate.json"
RECEIPT_VERSION = 1
TOOL = "bapu-gate"

STRUCTURE_OK, PASS, HOLD, PASS_UNJUDGED = "STRUCTURE-OK", "PASS", "HOLD", "PASS-UNJUDGED"

_OP_RE = re.compile(r"^## (ADDED|MODIFIED|REMOVED|RENAMED) Requirements\s*$")
#: A heading shaped like an operation that is not exactly one of the four (``## Added
#: Requirements``, ``## ADDED requirements``, ``## ADDED Requirements:``, ``### ADDED ...``): left
#: alone, the requirements under it would silently lose their operation, and with it the
#: Purpose rule for a new capability.
_OP_LIKE_RE = re.compile(
    r"^#{1,6}\s*(?:ADDED|MODIFIED|REMOVED|RENAMED)\b|^##\s+\S+\s+requirements?\b",
    re.IGNORECASE,
)
_REQ_RE = re.compile(r"^### Requirement:[ \t]*(\S.*?)\s*$")
_SCN_RE = re.compile(r"^#### Scenario:[ \t]*(\S.*?)\s*$")
_THREE_HASH_SCN_RE = re.compile(r"^###\s+Scenario:")
#: Any heading that names a Requirement or a Scenario without being the exact form above:
#: a full-width colon, the wrong number of hashes, a missing name.
_LOOSE_HEAD_RE = re.compile(r"^#{2,}\s*(Requirement|Scenario)\b", re.IGNORECASE)
_STEP_RE = re.compile(r"^-\s+\*\*(GIVEN|WHEN|THEN|AND)\*\*\s*(.*)$")
_PURPOSE_RE = re.compile(r"^## Purpose\s*$", re.MULTILINE)


@dataclass
class Scenario:
    name: str
    line: int
    given: list[str] = field(default_factory=list)
    when: list[str] = field(default_factory=list)
    then: list[str] = field(default_factory=list)


@dataclass
class Requirement:
    op: str  # ADDED, MODIFIED, REMOVED, RENAMED, or "" outside an operation section
    name: str
    line: int
    text_lines: list[str] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.text_lines)


@dataclass
class Delta:
    path: str  # relative to the change directory, "/"-separated
    file: Path
    capability: str
    requirements: list[Requirement]
    has_purpose: bool
    new_capability: bool
    raw: bytes  # the bytes that were parsed; receipts hash these, never a later re-read


@dataclass
class Change:
    name: str
    directory: Path
    specs_dir: Path | None
    deltas: list[Delta]
    problems: list[str]


def parse_spec(text: str) -> tuple[list[Requirement], list[str]]:
    """Requirements of one spec file, and the lines that break its structure."""
    requirements: list[Requirement] = []
    problems: list[str] = []
    op = ""
    current: Requirement | None = None
    scenario: Scenario | None = None
    swallow = False  # inside a block whose heading was malformed: its lines belong to nothing
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        op_match = _OP_RE.match(line)
        if op_match:
            op, current, scenario, swallow = op_match.group(1), None, None, False
            continue
        if _OP_LIKE_RE.match(line):
            problems.append(
                f"line {number}: unknown operation heading {stripped[:60]!r}; write "
                "'## ADDED|MODIFIED|REMOVED|RENAMED Requirements'"
            )
            op, current, scenario, swallow = "", None, None, True
            continue
        req_match = _REQ_RE.match(line)
        scn_match = _SCN_RE.match(line)
        loose = _LOOSE_HEAD_RE.match(line)
        if not (req_match or scn_match) and (loose or _THREE_HASH_SCN_RE.match(line)):
            if _THREE_HASH_SCN_RE.match(line):
                problems.append(
                    f"line {number}: scenario heading has three hashes; "
                    "write '#### Scenario: <name>'"
                )
            else:
                problems.append(
                    f"line {number}: malformed heading {stripped[:60]!r}; write "
                    "'### Requirement: <name>' or '#### Scenario: <name>' with an ASCII colon"
                )
            if loose is None or loose.group(1).lower() == "scenario":
                scenario, swallow = None, True  # keep the requirement, drop the block
            else:
                current, scenario, swallow = None, None, False
            continue
        if req_match:
            current = Requirement(op=op, name=req_match.group(1), line=number)
            requirements.append(current)
            scenario, swallow = None, False
            continue
        if scn_match:
            if current is None:
                problems.append(
                    f"line {number}: scenario {scn_match.group(1)!r} is outside any requirement"
                )
                scenario, swallow = None, True
                continue
            scenario, swallow = Scenario(name=scn_match.group(1), line=number), False
            current.scenarios.append(scenario)
            continue
        if line.startswith("## ") or line.startswith("# "):
            current, scenario, swallow = None, None, False
            continue
        if swallow:
            continue
        if scenario is not None:
            step = _STEP_RE.match(stripped)
            if step and step.group(2).strip():
                kind, body = step.group(1), step.group(2).strip()
                key = {"GIVEN": "given", "WHEN": "when", "THEN": "then"}.get(kind)
                if key is None:  # AND continues the kind of step before it
                    key = "then" if scenario.then else ("when" if scenario.when else "given")
                getattr(scenario, key).append(body)
            elif step:
                problems.append(f"line {number}: empty {step.group(1)} step in {scenario.name!r}")
            elif stripped:
                problems.append(
                    f"line {number}: prose inside scenario {scenario.name!r}: "
                    f"{stripped[:60]!r}; every non-blank line of a scenario is one "
                    "'- **GIVEN|WHEN|THEN|AND**' step"
                )
            continue
        if current is not None and stripped:
            current.text_lines.append(stripped)
    return requirements, problems


def _default_specs_dir(directory: Path) -> Path | None:
    """``<openspec>/specs`` for the nearest ancestor named ``openspec``, else None."""
    resolved = directory.resolve()
    for candidate in (resolved, *resolved.parents):
        if candidate.name == "openspec":
            return candidate / "specs"
    return None


def _find_specs(spec_root: Path) -> list[Path]:
    """Every ``spec.md`` under ``spec_root``, following symlinked directories (each real
    directory once), as paths under ``spec_root``. A linked delta that were skipped would let
    the change pass without it."""
    found: list[Path] = []
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(spec_root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        if "spec.md" in filenames:
            found.append(Path(dirpath) / "spec.md")
    return sorted(found)


def load(target: Path, specs_dir: Path | None = None) -> Change:
    """The change at ``target``: a change directory, or one spec file inside one."""
    target = Path(target)
    spec_root: Path | None
    if target.is_dir():
        directory, spec_root = target, target / "specs"
        files = _find_specs(spec_root) if spec_root.is_dir() else []
    elif target.is_file():
        target = target.resolve()
        spec_root = next((p for p in target.parents if p.name == "specs"), None)
        directory = spec_root.parent if spec_root is not None else target.parent
        files = [target]
    else:
        raise FileNotFoundError(f"no such change directory or spec file: {target}")
    canon = specs_dir if specs_dir is not None else _default_specs_dir(directory)
    deltas: list[Delta] = []
    problems: list[str] = []
    for file in files:
        raw = file.read_bytes()
        text = raw.decode("utf-8")
        requirements, found = parse_spec(text)
        if spec_root is not None:
            rel = file.relative_to(directory).as_posix()
            capability = file.parent.relative_to(spec_root).as_posix()
        else:
            rel, capability = file.name, file.parent.name
        problems.extend(f"{rel}: {p}" for p in found)
        new = canon is None or not (canon / capability / "spec.md").is_file()
        has_purpose = _PURPOSE_RE.search(text) is not None
        deltas.append(Delta(rel, file, capability, requirements, has_purpose, new, raw))
    return Change(directory.resolve().name, directory, canon, deltas, problems)


def structure_problems(change: Change) -> list[str]:
    """Every structural problem of the change; any entry makes the verdict HOLD."""
    problems = list(change.problems)
    if not change.deltas:
        problems.append("no delta spec: expected specs/<capability>/spec.md in the change")
    for delta in change.deltas:
        if not delta.requirements:
            problems.append(f"{delta.path}: holds no '### Requirement:' block")
        for req in delta.requirements:
            if req.op == "REMOVED":
                continue
            if not req.scenarios:
                problems.append(f"{delta.path}: requirement {req.name!r} has no scenario")
            for scn in req.scenarios:
                missing = [k for k in ("WHEN", "THEN") if not getattr(scn, k.lower())]
                if missing:
                    problems.append(
                        f"{delta.path}: scenario {scn.name!r} has no {' or '.join(missing)} step"
                    )
        adds = any(r.op == "ADDED" for r in delta.requirements)
        if delta.new_capability and adds and not delta.has_purpose:
            hint = (
                ""
                if change.specs_dir is not None
                else " (no openspec/specs directory found; pass --specs-dir if it exists elsewhere)"
            )
            problems.append(
                f"{delta.path}: new capability {delta.capability!r} has no '## Purpose' "
                f"section{hint}"
            )
    return problems


def original_questions(req: Requirement) -> dict[str, dict[str, Any]]:
    """The first ask: one noul per property, over ``requirement_state(req)``."""
    questions: dict[str, dict[str, Any]] = {
        "single_behavior": {
            "type": "noul",
            "instructions": (
                "Does `requirement.text` state exactly one observable behaviour under one SHALL "
                "or MUST? Several behaviours joined by 'and also' or its equivalent in any "
                "language, that could each be tested on their own, mean no."
            ),
            "criteria": {
                "true": "one behaviour, one SHALL/MUST",
                "false": "several behaviours or none",
            },
        },
        "observable": {
            "type": "noul",
            "instructions": (
                "Could a tester who has never seen the code decide from outside whether "
                "`requirement.text` holds: an output line, a refusal code, an exit code, a file "
                "that exists, a named test that goes red, an outbound request recorded by a fake "
                "endpoint? An absence or an equality against a reference is also decidable from "
                "outside: a module absent from the import closure, an argument list equal to a "
                "baseline. File names, refusal codes, thresholds, numbers, argument lists and "
                "import-closure membership are observable outputs."
            ),
            "criteria": {
                "true": "decidable from outside",
                "false": "only checkable by reading the code",
            },
        },
        "no_impl_detail": {
            "type": "noul",
            "instructions": (
                "Is `requirement.text` free of internal implementation choices such as internal "
                "function or class names, a library choice, or a step-by-step algorithm? Paths "
                "that are part of the interface, command names, CLI flags and option values, "
                "refusal codes and numbers are NOT implementation detail."
            ),
            "criteria": {
                "true": "no implementation detail",
                "false": "names an implementation choice",
            },
        },
    }
    for i in range(len(req.scenarios)):
        questions[f"exercises_{i}"] = {
            "type": "noul",
            "instructions": (
                f"Does `scenarios[{i}]` describe a specific situation (a concrete input, state or "
                "deliberately introduced defect) with a specific outcome that would test "
                "`requirement.text`, rather than restating the requirement in other words?"
            ),
            "criteria": {
                "true": "a concrete case with a concrete outcome",
                "false": "a restatement or vague",
            },
        }
        questions[f"testable_{i}"] = {
            "type": "noul",
            "instructions": (
                f"Could an automated test be written from `scenarios[{i}]` as it stands: its WHEN "
                "describes an input, state or deliberately planted defect a test could set up, and "
                "its THEN names a result the test could observe (a named test failing, a refusal "
                "code, an exit code, an output line, a file that exists or not)?"
            ),
            "criteria": {
                "true": "a test could be written from it",
                "false": "nothing to set up or nothing observable",
            },
        }
    return questions


def paraphrase_questions(req: Requirement) -> dict[str, dict[str, Any]]:
    """The second ask: the same question ids and the same criteria, reworded. A clause that
    passes under one wording only is not a pass."""
    questions: dict[str, dict[str, Any]] = {
        "single_behavior": {
            "type": "noul",
            "instructions": (
                "Count the separate behaviours that `requirement.text` obliges the system to "
                "show. Is that count exactly one, stated with a single SHALL or MUST, with no "
                "second obligation appended that could be checked independently?"
            ),
            "criteria": {
                "true": "a single obligation that is checked as one thing",
                "false": "two or more independent obligations, or no obligation at all",
            },
        },
        "observable": {
            "type": "noul",
            "instructions": (
                "Imagine a black-box tester with no access to the source. Could they tell from the "
                "outside whether `requirement.text` is met, for example from an exit status, a "
                "printed line, a file created or absent, a module absent from the import closure, "
                "an argument list equal to a baseline, an error code, a named test failing, or "
                "an outbound request recorded by a fake endpoint? File names, error codes, limits, "
                "numbers, argument lists and import-closure membership count as things they can "
                "see."
            ),
            "criteria": {
                "true": "checkable from the outside by a black-box tester",
                "false": "can only be confirmed by inspecting the source",
            },
        },
        "no_impl_detail": {
            "type": "noul",
            "instructions": (
                "Does `requirement.text` avoid naming how it is built, such as an internal "
                "function or class name, a library it relies on, or a step-by-step algorithm? A "
                "path that is part of the interface, a command name, CLI flags and option values, "
                "a refusal code and numbers belong to the contract and do not count."
            ),
            "criteria": {
                "true": "names nothing about how it is built",
                "false": "names an internal function or class name, a library or an algorithm",
            },
        },
    }
    for i in range(len(req.scenarios)):
        questions[f"exercises_{i}"] = {
            "type": "noul",
            "instructions": (
                f"Is `scenarios[{i}]` a concrete test case for `requirement.text`: a particular "
                "starting condition or planted fault, followed by a particular expected result, "
                "and not just the requirement said again in different words?"
            ),
            "criteria": {
                "true": "a particular case with a particular expected result",
                "false": "a rewording of the requirement, or too vague to be a case",
            },
        }
        questions[f"testable_{i}"] = {
            "type": "noul",
            "instructions": (
                f"Given only `scenarios[{i}]`, could someone write an automated check: the WHEN "
                "part can be arranged by a test (an input, a state, a planted fault) and the THEN "
                "part is something the test can assert (an exit code, an error code, a printed "
                "line, a file present or missing, a named test failing)?"
            ),
            "criteria": {
                "true": "both the setup and the expected result are automatable",
                "false": "the setup cannot be arranged or the result cannot be asserted",
            },
        }
    return questions


def requirement_state(req: Requirement) -> dict[str, Any]:
    """What the judge sees for one requirement: its text and its scenarios, nothing else."""
    return {
        "requirement": {"name": req.name, "text": req.text},
        "scenarios": [
            {"name": s.name, "given": s.given, "when": s.when, "then": s.then}
            for s in req.scenarios
        ],
    }


#: ``asker(requirement) -> (original answers, paraphrase answers, {ask: answering model})``
Asker = Callable[[Requirement], tuple[dict, dict, dict]]


def jev_asker(model: str = jev.DEFAULT_MODEL, key: str | None = None) -> Asker:
    """Two Jev requests per requirement, one per wording, both pinned to ``model``."""

    def ask(req: Requirement) -> tuple[dict, dict, dict]:
        state = requirement_state(req)
        original = jev.judge(state, original_questions(req), model=model, key=key)
        paraphrase = jev.judge(state, paraphrase_questions(req), model=model, key=key)
        models = {"original": original.get("model"), "paraphrase": paraphrase.get("model")}
        return original["answers"], paraphrase["answers"], models

    return ask


def _pair(original: dict, paraphrase: dict, qid: str) -> tuple[float, dict[str, float]]:
    """(stored score, both asks) for one question: the stored score is the lower ask."""
    raw = {"original": jev.noul(original, qid), "paraphrase": jev.noul(paraphrase, qid)}
    return min(raw.values()), raw


def score_change(change: Change, asker: Asker | None) -> list[dict[str, Any]]:
    """One row per requirement; ``asker=None`` leaves every row unjudged."""
    rows: list[dict[str, Any]] = []
    for delta in change.deltas:
        for req in delta.requirements:
            row: dict[str, Any] = {"file": delta.path, "op": req.op, "name": req.name}
            if req.op == "REMOVED" or asker is None:
                row["judged"] = False
                row["scenarios"] = [{"name": s.name} for s in req.scenarios]
                rows.append(row)
                continue
            original, paraphrase, models = asker(req)
            row["judged"] = True
            row["models"] = dict(models)
            row["raw"] = {}
            for k in REQ_KEYS:
                row[k], row["raw"][k] = _pair(original, paraphrase, k)
            row["scenarios"] = []
            for i, s in enumerate(req.scenarios):
                scn: dict[str, Any] = {"name": s.name, "raw": {}}
                for k in SCN_KEYS:
                    scn[k], scn["raw"][k] = _pair(original, paraphrase, f"{k}_{i}")
                row["scenarios"].append(scn)
            rows.append(row)
    return rows


def score_hold(where: str, key: str, raw: dict[str, float]) -> str | None:
    """The hold line for one question, or None: either ask below THRESHOLD, else either ask
    inside HOLD_BAND (both ends included)."""
    shown = ", ".join(f"{name}={p}" for name, p in raw.items())
    if any(p < THRESHOLD for p in raw.values()):
        return f"{where}: {key} ({shown}) < {THRESHOLD}"
    low, high = HOLD_BAND
    if any(low <= p <= high for p in raw.values()):
        return f"{where}: {key} ({shown}) inside the hold band [{low}, {high}]"
    return None


def verdict(rows: list[dict[str, Any]], problems: list[str]) -> tuple[str, list[str]]:
    """PASS needs at least one judged requirement: a REMOVED-only delta is PASS-UNJUDGED, so
    "no judge ran" can never read as "the judge agreed"."""
    holds = [f"structure: {p}" for p in problems]
    for row in rows:
        if not row.get("judged"):
            continue
        for k in REQ_KEYS:
            holds.append(score_hold(row["name"], k, row["raw"][k]) or "")
        for s in row["scenarios"]:
            for k in SCN_KEYS:
                holds.append(score_hold(f"{row['name']} / {s['name']}", k, s["raw"][k]) or "")
    holds = [h for h in holds if h]
    if holds:
        return HOLD, holds
    if not any(r.get("judged") for r in rows):
        return PASS_UNJUDGED, ["no requirement was judged (a REMOVED-only delta)"]
    return PASS, []


def files_sha256(change: Change) -> str:
    """One digest over the path and the parsed bytes of every delta spec, in order: the bytes
    that were judged, not whatever the file holds by the time the digest is taken."""
    digest = hashlib.sha256()
    for delta in change.deltas:
        digest.update(delta.path.encode("utf-8") + b"\0")
        digest.update(delta.raw + b"\0")
    return digest.hexdigest()


def population_line(change: Change, rows: list[dict[str, Any]], model: str | None) -> str:
    scenarios = sum(len(r["scenarios"]) for r in rows)
    return (
        f"POPULATION target={change.name} deltas={len(change.deltas)} "
        f"requirements={len(rows)} scenarios={scenarios} model={model or 'offline'} "
        f"files_sha256={files_sha256(change)[:12]}"
    )


def run_gate(
    change: Change, asker: Asker | None = None, model: str | None = None
) -> dict[str, Any]:
    """The report for one change. Offline when ``asker`` is None. Online scoring runs only on
    a structurally sound change: a structural HOLD is already the verdict."""
    problems = structure_problems(change)
    online = asker is not None
    rows = score_change(change, asker if online and not problems else None)
    if not online:
        result = HOLD if problems else STRUCTURE_OK
        holds = [f"structure: {p}" for p in problems]
    elif problems:
        result = HOLD
        holds = [f"structure: {p}" for p in problems]
        holds.append("online scoring skipped: fix the structure first")
    else:
        result, holds = verdict(rows, [])
    answered = sorted({str(m) for r in rows for m in r.get("models", {}).values()})
    return {
        "tool": TOOL,
        "tool_version": __version__,
        "receipt_version": RECEIPT_VERSION,
        "target": change.name,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "online" if online else "offline",
        "model_requested": model if online else None,
        "model_answered": answered[0] if len(answered) == 1 else (answered or None),
        "threshold": THRESHOLD,
        "hold_band": list(HOLD_BAND),
        "statistic": STATISTIC,
        "files_sha256": files_sha256(change),
        "population": population_line(change, rows, model if online else None),
        "structure": problems,
        "requirements": rows,
        "verdict": result,
        "holds": holds,
    }


def check_receipt(
    change: Change, receipt: Path, model: str = jev.DEFAULT_MODEL
) -> tuple[bool, str]:
    """(True, reason) only for a PASS receipt that is current for the change as it stands.

    Everything is re-derived: the digest of the delta specs, the structure, one judged row per
    requirement and scenario in order, the answering model of every ask, and every stored score
    against this module's threshold and hold band. The receipt's own verdict line is necessary
    but never sufficient. What stays out of reach is a receipt whose scores were fabricated and
    whose digest was recomputed to match.
    """
    if not receipt.is_file():
        return False, f"no receipt at {receipt}"
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        return False, f"receipt unreadable ({type(exc).__name__})"
    try:
        return _receipt_is_current(data, change, model)
    except (AttributeError, TypeError, KeyError) as exc:
        return False, f"receipt malformed ({type(exc).__name__}: {exc})"


def _receipt_is_current(data: Any, change: Change, model: str) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "receipt is not a JSON object"
    if data.get("tool") != TOOL or data.get("receipt_version") != RECEIPT_VERSION:
        return False, f"not a {TOOL} receipt of version {RECEIPT_VERSION}"
    if data.get("verdict") != PASS:
        return False, f"receipt verdict is {data.get('verdict')!r}, not {PASS}"
    if data.get("files_sha256") != files_sha256(change):
        return False, "stale: the delta specs changed after the receipt was written"
    problems = structure_problems(change)
    if problems:
        return False, "structure: " + "; ".join(problems)
    rows = data.get("requirements")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return False, "receipt requirements is not a list of objects"
    expected = [(d.path, r) for d in change.deltas for r in d.requirements]
    if len(rows) != len(expected):
        return False, f"{len(rows)} receipt rows for {len(expected)} requirements"
    judged = 0
    for (path, req), row in zip(expected, rows):
        if row.get("file") != path or row.get("name") != req.name:
            return False, f"receipt row {row.get('name')!r} is not requirement {req.name!r}"
        if req.op == "REMOVED":
            continue
        if row.get("judged") is not True:
            return False, f"requirement {req.name!r} was not judged"
        judged += 1
        models = row.get("models")
        if (
            not isinstance(models, dict)
            or set(models) != {"original", "paraphrase"}
            or any(m != model for m in models.values())
        ):
            return False, f"requirement {req.name!r} was not answered by {model} on both asks"
        bad = _stored_scores_hold(req.name, row, REQ_KEYS)
        if bad:
            return False, bad
        scenarios = row.get("scenarios")
        if not isinstance(scenarios, list) or [s.get("name") for s in scenarios] != [
            s.name for s in req.scenarios
        ]:
            return False, f"the scenarios of {req.name!r} do not match the change"
        for scn in scenarios:
            bad = _stored_scores_hold(f"{req.name} / {scn['name']}", scn, SCN_KEYS)
            if bad:
                return False, bad
    if judged == 0:
        return False, "no requirement was judged"
    return True, "current PASS"


def _stored_scores_hold(where: str, holder: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    raws = holder.get("raw")
    if not isinstance(raws, dict):
        return f"{where}: no raw asks recorded"
    for k in keys:
        raw = raws.get(k)
        if not isinstance(raw, dict) or set(raw) != {"original", "paraphrase"}:
            return f"{where}: {k} lacks its original and paraphrase asks"
        if not all(jev.is_probability(v) for v in raw.values()):
            return f"{where}: {k} holds a malformed score {raw!r}"
        if holder.get(k) != min(raw.values()):
            return f"{where}: stored {k} is not the lower of its two asks"
        hold = score_hold(where, k, raw)
        if hold is not None:
            return f"the recorded asks hold: {hold}"
    return None


# --------------------------------------------------------------------------------------------
# Self-test: planted known positives and a known negative, checked before the gate is trusted.

GOOD_DELTA = """# Delta

## Purpose

An example capability used only by the gate's self-test: exports refuse to overwrite.

## ADDED Requirements

### Requirement: Existing export is not overwritten
The export command SHALL exit 3 with the message `output exists` when `out/export.json`
already exists and `--force` is not given.

#### Scenario: A second export without --force is refused
- **GIVEN** `out/export.json` was written by an earlier run
- **WHEN** `export --out out` runs again without `--force`
- **THEN** the command exits 3 and prints `output exists`
"""

BAD_DELTA = """# Delta

## Purpose

A deliberately bad example capability used only by the gate's self-test.

## ADDED Requirements

### Requirement: Exporter behaves well
The exporter SHALL validate the input and also write the audit log and also rotate old
exports and also be fast, using the `_Validator` helper class.

#### Scenario: Exporter validates the input
- **WHEN** the exporter runs
- **THEN** the exporter behaves well and validates the input
"""

#: (name, delta text, text every expected hold line must contain)
_STRUCTURAL_POSITIVES = (
    ("three-hash", GOOD_DELTA.replace("#### Scenario:", "### Scenario:"), "three hashes"),
    (
        "full-width-colon",
        GOOD_DELTA.replace("### Requirement:", "### Requirement\uff1a"),
        "malformed heading",
    ),
    (
        "prose",
        GOOD_DELTA.rstrip("\n") + "\nThe command SHALL also rotate logs.\n",
        "prose inside scenario",
    ),
    ("no-then", GOOD_DELTA.replace("- **THEN**", "- **AND**"), "has no THEN step"),
    ("no-purpose", GOOD_DELTA.replace("## Purpose\n", "## Context\n"), "no '## Purpose'"),
    (
        "no-scenario",
        GOOD_DELTA.split("#### Scenario:")[0],
        "has no scenario",
    ),
)


def _write_change(root: Path, name: str, delta: str | None) -> Path:
    directory = root / "openspec" / "changes" / name
    (directory / "specs" / "example").mkdir(parents=True, exist_ok=True)
    if delta is not None:
        (directory / "specs" / "example" / "spec.md").write_text(delta, encoding="utf-8")
    return directory


def _canned(p: float) -> Asker:
    def ask(req: Requirement) -> tuple[dict, dict, dict]:
        answers = {k: {"noul": p} for k in REQ_KEYS}
        for i in range(len(req.scenarios)):
            answers[f"exercises_{i}"] = {"noul": p}
            answers[f"testable_{i}"] = {"noul": p}
        pinned = {"original": jev.DEFAULT_MODEL, "paraphrase": jev.DEFAULT_MODEL}
        return answers, answers, pinned

    return ask


def self_test(online: bool = False, model: str = jev.DEFAULT_MODEL) -> int:
    """Offline: every structural known positive HOLDs, the known negative is STRUCTURE-OK, and
    the verdict rule holds on canned scores. With ``online``: Jev must PASS the good delta and
    HOLD the bad one before its scores are worth anything."""
    problems: list[str] = []
    checks = 0
    with tempfile.TemporaryDirectory(prefix="bapu-gate-self-test-") as tmp:
        root = Path(tmp)
        for name, text, expect in _STRUCTURAL_POSITIVES:
            checks += 1
            report = run_gate(load(_write_change(root, name, text)))
            if report["verdict"] != HOLD or not any(expect in h for h in report["holds"]):
                problems.append(f"{name}: expected HOLD naming {expect!r}, got {report['holds']}")
        checks += 1
        report = run_gate(load(_write_change(root, "no-delta", None)))
        if report["verdict"] != HOLD:
            problems.append(f"no-delta: expected HOLD, got {report['verdict']}")
        good = load(_write_change(root, "good", GOOD_DELTA))
        bad = load(_write_change(root, "bad", BAD_DELTA))
        checks += 1
        if run_gate(good)["verdict"] != STRUCTURE_OK:
            problems.append(f"good offline: expected {STRUCTURE_OK}, got {run_gate(good)['holds']}")
        for label, change, p, expect in (
            ("canned good", good, 0.92, PASS),
            ("canned bad", bad, 0.08, HOLD),
            ("canned band", good, 0.55, HOLD),
        ):
            checks += 1
            got = run_gate(change, _canned(p), jev.DEFAULT_MODEL)["verdict"]
            if got != expect:
                problems.append(f"{label}: expected {expect}, got {got}")
        checks += 1
        mixed = score_change(good, lambda r: (*_canned(0.9)(r)[:1], *_canned(0.3)(r)[1:]))
        if verdict(mixed, [])[0] != HOLD or mixed[0]["single_behavior"] != 0.3:
            problems.append("min statistic: a low paraphrase ask must hold the clause")
        checks += 1
        try:
            jev.noul({"single_behavior": {"noul": None}}, "single_behavior")
            problems.append("missing answer: expected JevError, not a score")
        except jev.JevError:
            pass
        if online:
            key = jev.api_key()
            for label, change, expect in (("online good", good, PASS), ("online bad", bad, HOLD)):
                checks += 1
                try:
                    report = run_gate(change, jev_asker(model, key), model)
                except jev.JevError as exc:
                    print(f"{TOOL}: self-test: no judgment from the API: {exc}", file=sys.stderr)
                    return 2
                print(f"  {label}: {report['verdict']} {report['requirements'][0]}")
                if report["verdict"] != expect:
                    problems.append(f"{label}: expected {expect}, got {report['holds']}")
    print(json.dumps({"checks": checks, "problems": problems}, indent=1))
    return 0 if not problems else 1


def _print_report(report: dict[str, Any]) -> None:
    print(report["population"])
    for row in report["requirements"]:
        if not row.get("judged"):
            continue
        scores = [(row[k], k) for k in REQ_KEYS]
        scores += [(s[k], f"{s['name']} / {k}") for s in row["scenarios"] for k in SCN_KEYS]
        low, where = min(scores)
        print(f"  judged: {row['name']}: lowest score {low:.3f} ({where})")
    for hold in report["holds"]:
        print(f"  hold: {hold}")
    print(f"verdict: {report['verdict']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bapu-gate",
        description="Check OpenSpec delta specs clause by clause before code is written.",
        epilog=(
            "Offline by default. --online needs TYPESAFE_API_KEY. Exit codes: 0 STRUCTURE-OK or "
            "PASS, 1 HOLD or PASS-UNJUDGED, 2 usage error, missing input or no API judgment."
        ),
    )
    parser.add_argument("path", nargs="?", type=Path, help="change directory or spec file")
    parser.add_argument("--specs-dir", type=Path, help="canonical specs directory")
    parser.add_argument("--online", action="store_true", help="also score clauses with Jev")
    parser.add_argument("--model", default=jev.DEFAULT_MODEL, help="exact Jev model id")
    parser.add_argument(
        "--receipt", type=Path, help=f"receipt path (default <change>/{RECEIPT_NAME})"
    )
    parser.add_argument("--no-receipt", action="store_true", help="online: write no receipt")
    parser.add_argument(
        "--check-receipt", action="store_true", help="offline: is the receipt a current PASS?"
    )
    parser.add_argument("--self-test", action="store_true", help="run the planted checks")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.self_test:
        if args.path is not None:
            parser.error("--self-test takes no PATH")
        if args.online and not jev.api_key_is_set():
            print(f"{TOOL}: {jev.ENV_KEY} is not set; --online needs it", file=sys.stderr)
            return 2
        return self_test(online=args.online, model=args.model)
    if args.path is None:
        parser.error("PATH is required (a change directory or a spec file)")
    if args.check_receipt and args.online:
        parser.error("--check-receipt is offline; drop --online")
    if args.no_receipt and args.receipt is not None:
        parser.error("--receipt and --no-receipt contradict each other")
    try:
        change = load(args.path, args.specs_dir)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    receipt = args.receipt if args.receipt is not None else change.directory / RECEIPT_NAME

    if args.check_receipt:
        ok, why = check_receipt(change, receipt, args.model)
        print(f"receipt {'current' if ok else 'NOT current'}: {why}")
        return 0 if ok else 1

    asker = None
    if args.online:
        try:
            asker = jev_asker(args.model, jev.api_key())
        except jev.JevError as exc:
            print(f"{TOOL}: {exc}", file=sys.stderr)
            return 2
    try:
        report = run_gate(change, asker, args.model)
    except jev.JevError as exc:
        print(f"{TOOL}: no judgment from the API, no receipt written: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        _print_report(report)
    if args.online and not args.no_receipt:
        try:
            receipt.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", "utf-8")
        except OSError as exc:
            print(f"{TOOL}: cannot write the receipt: {exc}", file=sys.stderr)
            return 2
        print(f"receipt: {receipt}", file=sys.stderr if args.json else sys.stdout)
    return 0 if report["verdict"] in (PASS, STRUCTURE_OK) else 1


if __name__ == "__main__":
    raise SystemExit(main())
