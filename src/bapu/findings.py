"""Findings verifier: check review findings against the evidence they quote.

    bapu-findings FILE [--allow-unquoted] [--out FILE] [--json]
    bapu-findings FILE --online [--model ID] [--allow-unquoted] [--out FILE] [--json]
    bapu-findings --self-test [--online]

A finding is a claim a reviewer makes about a change, the evidence quoted for it (the commands
that were run and their output, verbatim), and the claim split into sub-claims: single
observations, each quoting the part of the evidence it rests on::

    {"findings": [{
        "id": "F1",
        "claim": "The resumed export reports success although its own check fails.",
        "evidence": "$ export --resume\\nok=True\\n$ export check\\nchecksum mismatch",
        "claimed_severity": "P1",
        "subclaims": [
            {"text": "The resumed export reports ok=True.", "quote": "ok=True"},
            {"text": "The check reports a checksum mismatch.", "quote": "checksum mismatch"}
        ]
    }]}

Offline (the default; no key, no network) every sub-claim must carry a quote that appears
verbatim in the evidence. A finding that cites output it did not paste goes back to its author
as NEEDS-EVIDENCE before anyone spends time on it; the others are QUOTED. Quoting is necessary,
not sufficient: a verbatim quote can still be read wrongly.

Online (``--online``; needs TYPESAFE_API_KEY) Jev is also asked, for every sub-claim, whether the
evidence shows that one observation. Support is not the complement of refutation, so a sub-claim
the evidence does not show gets a second question, whether the evidence shows it to be FALSE:

  SHOWN         P(shown) at or above GREY_LOW (0.3); takes part in the minimum
  CONTRADICTED  below GREY_LOW, and P(false) above GREY_HIGH (0.75): the finding is REFUTED
  ABSENT        below GREY_LOW, and the evidence is merely silent: NEEDS-EVIDENCE

The whole claim is asked too. When every sub-claim is SHOWN, a whole claim below 0.3 means the
claim says more than its sub-claims (NEEDS-EVIDENCE); otherwise the lowest of the SHOWN
probabilities and the whole claim decides: 0.3 to 0.75 ESCALATE (a stronger reviewer decides),
above 0.75 CONFIRMED. CONFIRMED means the quoted evidence shows what the finding says. It does
not mean the finding is true: a premise that fails elsewhere, or a code path production never
reaches, sits outside the quotes. Reproduce a finding before acting on it. Severity and
reachability are also asked and reported as data and flags; neither changes a verdict.

Exit codes: 0 the evidence settled every finding (QUOTED offline; CONFIRMED or REFUTED online),
1 at least one finding is left with a person (NEEDS-EVIDENCE, UNCHECKED, ESCALATE), 2 usage or
input error, or (online) no judgment from the API for at least one finding.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from . import __version__, jev

GREY_LOW, GREY_HIGH = 0.3, 0.75
#: Reachability is reported, not gated: below this it only raises a flag.
REACHABILITY_FLAG_BELOW = 0.6
TOOL = "bapu-findings"

QUOTED, UNCHECKED, NEEDS_EVIDENCE = "QUOTED", "UNCHECKED", "NEEDS-EVIDENCE"
CONFIRMED, REFUTED, ESCALATE = "CONFIRMED", "REFUTED", "ESCALATE"
SHOWN, CONTRADICTED, ABSENT = "SHOWN", "CONTRADICTED", "ABSENT"
#: Verdicts that leave the finding with a person: exit 1.
ATTENTION = frozenset({NEEDS_EVIDENCE, UNCHECKED, ESCALATE})

SEVERITY_LEVELS = [
    {
        "level": "P2",
        "description": (
            "a wording, naming, or documentation gap; behaviour is correct or the wrong case "
            "cannot be reached from a production caller"
        ),
    },
    {
        "level": "P1",
        "description": (
            "a guard narrower than the property it protects, a test that asserts a label "
            "instead of the property, two checks sharing one refusal code, a spec or docstring "
            "that contradicts the code; the wrong case is reachable but announced or bounded"
        ),
    },
    {
        "level": "P0",
        "description": (
            "a silent wrong result on a production path: a verdict overwritten, a failure "
            "reported as ok, a wrong identity acted on, a control that admits what it exists "
            "to refuse"
        ),
    },
]

SUPPORTED_INSTRUCTIONS = (
    "A code reviewer made `claim` about a change and quoted `evidence`: the reproduction "
    "command they ran and its output. Judge only whether the quoted evidence, read on its own, "
    "shows the behaviour the claim describes. If the output shows a different behaviour, or the "
    "output the claim rests on is not there, it does not."
)
REACHABLE_INSTRUCTIONS = (
    "Judge whether the input used in `evidence` is one the production code path could have "
    "produced on its own, as opposed to an object built by hand, monkeypatched, or edited to "
    "have the shape the claim needs. A hand-built shape proves the code would misbehave on "
    "it, not that production reaches it."
)
SEVERITY_INSTRUCTIONS = (
    "Assuming the claim is true as stated, rate how badly it would hurt the software under "
    "review, on the levels defined."
)
FALSE_INSTRUCTIONS = (
    "The quoted `evidence` was already judged not to SHOW this observation. Judge the "
    "different question: does the evidence positively show the observation to be FALSE -- "
    "does the quoted output state a result that cannot hold at the same time as it? "
    "Evidence that simply does not mention the point does not show it to be false."
)

#: ``judge(state, questions) -> answers``; the online mode's only way to reach a model.
Judge = Callable[[dict, dict], dict]


class InputError(ValueError):
    """The findings file is not usable as given."""


def load_findings(path: Path) -> list[dict[str, Any]]:
    """The findings in ``path``, validated; InputError lists every problem at once."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from None
    findings = data.get("findings") if isinstance(data, dict) else data
    if not isinstance(findings, list):
        raise InputError("expected {'findings': [...]} or a JSON list of findings")
    if not findings:
        raise InputError("the file holds no finding; nothing to check is not a pass")
    problems: list[str] = []
    seen: set[str] = set()
    for i, finding in enumerate(findings):
        if not isinstance(finding, dict):
            problems.append(f"finding {i}: not a JSON object")
            continue
        fid = finding.get("id")
        if isinstance(fid, bool) or not isinstance(fid, (str, int)) or str(fid).strip() == "":
            problems.append(f"finding {i}: 'id' must be a non-empty string or an integer")
        elif str(fid) in seen:
            problems.append(f"finding {i}: id {fid!r} is used twice")
        else:
            seen.add(str(fid))
        for key in ("claim", "evidence"):
            value = finding.get(key)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"finding {i}: {key!r} must be a non-empty string")
        subclaims = finding.get("subclaims", [])
        if not isinstance(subclaims, list):
            problems.append(f"finding {i}: 'subclaims' must be a list")
            continue
        for j, sub in enumerate(subclaims):
            text = sub.get("text") if isinstance(sub, dict) else sub
            if not isinstance(text, str) or not text.strip():
                problems.append(f"finding {i}: sub-claim {j} needs a non-empty text")
            quote = sub.get("quote") if isinstance(sub, dict) else None
            if quote is not None and (not isinstance(quote, str) or not quote.strip()):
                problems.append(f"finding {i}: sub-claim {j} has an empty or non-string quote")
    if problems:
        raise InputError("\n".join(problems))
    return findings


def normalise_subclaims(raw: Any) -> list[dict[str, Any]]:
    """Accept ``["text", ...]`` or ``[{"text": ..., "quote": ...}, ...]``."""
    out: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            out.append({"text": str(item.get("text", "")), "quote": item.get("quote")})
        else:
            out.append({"text": str(item), "quote": None})
    return out


def missing_quotes(evidence: str, subclaims: list[dict[str, Any]]) -> list[int]:
    """Indices whose quote is not a verbatim substring of ``evidence``. No model call."""
    return [
        i for i, sub in enumerate(subclaims) if sub.get("quote") and sub["quote"] not in evidence
    ]


def check_quotes(finding: dict[str, Any], require_quotes: bool = True) -> dict[str, Any]:
    """The offline row: NEEDS-EVIDENCE, QUOTED, or UNCHECKED (only with unquoted sub-claims
    allowed, when there is nothing quoted to check)."""
    evidence = finding["evidence"]
    subs = normalise_subclaims(finding.get("subclaims"))
    row: dict[str, Any] = {
        "id": finding["id"],
        "claimed_severity": finding.get("claimed_severity"),
        "subclaims": len(subs),
    }
    bad = missing_quotes(evidence, subs)
    if bad:
        why = f"quote not found verbatim in the evidence: sub-claim(s) {bad}"
        return {**row, "verdict": NEEDS_EVIDENCE, "why": why}
    unquoted = [i for i, sub in enumerate(subs) if not sub.get("quote")]
    if not subs and require_quotes:
        why = "no sub-claims: split the claim into single observations that quote the evidence"
        return {**row, "verdict": NEEDS_EVIDENCE, "why": why}
    if unquoted and require_quotes:
        why = f"sub-claim(s) {unquoted} quote nothing from the evidence"
        return {**row, "verdict": NEEDS_EVIDENCE, "why": why}
    if subs and not unquoted:
        return {**row, "verdict": QUOTED, "why": "every sub-claim quotes the evidence verbatim"}
    why = "unquoted sub-claims allowed: nothing quoted to check offline"
    return {**row, "verdict": UNCHECKED, "why": why}


def support_questions(subclaims: list[str]) -> dict[str, dict[str, Any]]:
    """One noul per sub-claim, plus the whole claim, reachability and severity."""
    questions: dict[str, dict[str, Any]] = {}
    for i, text in enumerate(subclaims):
        questions[f"shown_{i}"] = {
            "type": "noul",
            "instructions": f"Does the quoted `evidence` show this single observation: {text}",
            "criteria": {
                "true": "the evidence shows it",
                "false": (
                    "the evidence does not show it, whether because it shows something else "
                    "or because it is silent on the point"
                ),
            },
        }
    questions["supported"] = {
        "type": "noul",
        "instructions": SUPPORTED_INSTRUCTIONS,
        "criteria": {
            "true": "the quoted output shows the described behaviour",
            "false": "it shows something else or the key output is missing",
        },
    }
    questions["reachable"] = {
        "type": "noul",
        "instructions": REACHABLE_INSTRUCTIONS,
        "criteria": {
            "true": "the input came from a production path",
            "false": "the input was built by hand or patched",
        },
    }
    questions["severity"] = {
        "type": "score",
        "instructions": SEVERITY_INSTRUCTIONS,
        "criteria": SEVERITY_LEVELS,
    }
    return questions


def contradiction_questions(items: list[tuple[int, str]]) -> dict[str, dict[str, Any]]:
    """The second pass, asked only for the low tail: does the evidence show it to be FALSE?"""
    return {
        f"false_{i}": {
            "type": "noul",
            "instructions": f"{FALSE_INSTRUCTIONS}\n\nThe observation: {text}",
            "criteria": {
                "true": "the quoted output states a result that cannot hold together with it",
                "false": (
                    "the evidence does not show it to be false, including when it is silent "
                    "on the point"
                ),
            },
        }
        for i, text in items
    }


def classify(p_supported: float) -> str:
    """CONFIRMED / REFUTED / ESCALATE from the support probability alone."""
    if GREY_LOW <= p_supported <= GREY_HIGH:
        return ESCALATE
    return REFUTED if p_supported < GREY_LOW else CONFIRMED


def subclaim_status(p_shown: float, p_false: float | None) -> str:
    """SHOWN / CONTRADICTED / ABSENT for one observation. A low P(shown) says only that the
    evidence does not establish it; whether the evidence establishes the opposite is a second,
    separately asked question."""
    if p_shown >= GREY_LOW:
        return SHOWN
    if p_false is not None and p_false > GREY_HIGH:
        return CONTRADICTED
    return ABSENT


def verdict_from(statuses: list[str], p_shown: list[float], p_whole: float) -> tuple[str, str]:
    """A true observation the reviewer forgot to quote looks, by score alone, exactly like a
    false one, so silence neither refutes nor drags the minimum down: it returns the finding
    to its author. The whole claim counts too: a claim that says more than its sub-claims, each
    shown, goes back to its author as well."""
    if not statuses:
        return classify(p_whole), "whole claim only"
    if CONTRADICTED in statuses:
        return REFUTED, f"the evidence contradicts sub-claim {statuses.index(CONTRADICTED)}"
    absent = [i for i, status in enumerate(statuses) if status == ABSENT]
    if absent:
        return NEEDS_EVIDENCE, f"the evidence is silent on sub-claim(s) {absent}"
    if p_whole < GREY_LOW:
        return NEEDS_EVIDENCE, "each sub-claim is shown, but the claim as a whole is not"
    shown = [p for p, status in zip(p_shown, statuses) if status == SHOWN]
    return classify(min([*shown, p_whole])), "minimum over the shown sub-claims and the claim"


def jev_judge(model: str = jev.DEFAULT_MODEL, key: str | None = None) -> Judge:
    def judge(state: dict, questions: dict) -> dict:
        return jev.judge(state, questions, model=model, key=key)["answers"]

    return judge


def judge_finding(finding: dict[str, Any], row: dict[str, Any], judge: Judge) -> dict[str, Any]:
    """The online row for one finding that passed the quote check."""
    subs = normalise_subclaims(finding.get("subclaims"))
    state = {"claim": finding["claim"], "evidence": finding["evidence"]}
    base = {**row, "quote_check": row["verdict"]}
    try:
        answers = judge(state, support_questions([s["text"] for s in subs]))
        p_whole = jev.noul(answers, "supported")
        p_shown = [jev.noul(answers, f"shown_{i}") for i in range(len(subs))]
        reach = jev.noul(answers, "reachable")
        p_false: list[float | None] = [None] * len(subs)
        low = [i for i, p in enumerate(p_shown) if p < GREY_LOW]
        if low:
            second = judge(state, contradiction_questions([(i, subs[i]["text"]) for i in low]))
            for i in low:
                p_false[i] = jev.noul(second, f"false_{i}")
    except jev.JevError as exc:
        return {**base, "verdict": ESCALATE, "why": f"no judgment: {exc}", "api_error": str(exc)}
    statuses = [subclaim_status(a, b) for a, b in zip(p_shown, p_false)]
    result, why = verdict_from(statuses, p_shown, p_whole)
    shown = [p for p, status in zip(p_shown, statuses) if status == SHOWN]
    severity_answer = answers.get("severity") or {}
    severity = jev.top_level(severity_answer)
    flags = ["reachability_unclear"] if reach < REACHABILITY_FLAG_BELOW else []
    if any(not s.get("quote") for s in subs):
        flags.append("unquoted_subclaims")
    claimed = str(finding.get("claimed_severity") or "")
    if claimed and severity and severity != claimed:
        flags.append("severity_disputed")
    return {
        **base,
        "p_supported": round(min([*shown, p_whole]), 3),
        "p_whole_claim": round(p_whole, 3),
        "p_subclaims": [round(p, 3) for p in p_shown],
        "subclaim_status": statuses,
        "p_contradicted": [None if p is None else round(p, 3) for p in p_false],
        "p_reachable": round(reach, 3),
        "severity": severity,
        "severity_probabilities": severity_answer.get("probabilities", {}),
        "verdict": result,
        "why": why,
        "flags": flags,
    }


def verify(
    findings: list[dict[str, Any]], *, require_quotes: bool = True, judge: Judge | None = None
) -> list[dict[str, Any]]:
    """One row per finding. Offline when ``judge`` is None; a finding that fails the quote
    check never reaches the judge."""
    rows = []
    for finding in findings:
        row = check_quotes(finding, require_quotes)
        if judge is not None and row["verdict"] != NEEDS_EVIDENCE:
            row = judge_finding(finding, row, judge)
        rows.append(row)
    return rows


def exit_code(rows: list[dict[str, Any]]) -> int:
    """2 when the API gave no answer for some finding; 1 when some finding is left with a
    person (NEEDS-EVIDENCE, UNCHECKED, ESCALATE); 0 when the evidence settled every one."""
    if any(r.get("api_error") for r in rows):
        return 2
    return 1 if any(r["verdict"] in ATTENTION for r in rows) else 0


# --------------------------------------------------------------------------------------------
# Self-test: planted findings whose right verdicts are known.

_EXPORT_EVIDENCE = (
    "$ exporter build --out d\n"
    "wrote d/export.json\n"
    "$ exporter build --out d --resume\n"
    "{'written': 1} ok=True files_written=1\n"
    "$ exporter check d\n"
    "checksum mismatch: export.json"
)

OFFLINE_PLANTED = [
    (
        {
            "id": "planted-quoted",
            "claim": "The resumed build reports success although the check run after it fails.",
            "evidence": _EXPORT_EVIDENCE,
            "subclaims": [
                {"text": "The resumed build prints ok=True.", "quote": "ok=True"},
                {"text": "The check reports a checksum mismatch.", "quote": "checksum mismatch"},
            ],
        },
        QUOTED,
    ),
    (
        {
            "id": "planted-paraphrased-quote",
            "claim": "The resumed build reports success although the check run after it fails.",
            "evidence": _EXPORT_EVIDENCE,
            "subclaims": [{"text": "The resumed build succeeds.", "quote": "status: success"}],
        },
        NEEDS_EVIDENCE,
    ),
    (
        {
            "id": "planted-unquoted",
            "claim": "The resumed build skips the checksum step.",
            "evidence": _EXPORT_EVIDENCE,
            "subclaims": ["Line 112 of build.py skips the checksum step."],
        },
        NEEDS_EVIDENCE,
    ),
]

ONLINE_PLANTED = [
    (
        {
            "id": "planted-supported",
            "claimed_severity": "P1",
            "claim": (
                "With --resume the exporter reports ok=True and files_written=1 while the check "
                "run right after it reports a checksum mismatch, so the published result "
                "disagrees with the exporter's own check."
            ),
            "evidence": _EXPORT_EVIDENCE,
            "subclaims": [
                {"text": "The resumed build prints ok=True.", "quote": "ok=True"},
                {"text": "The resumed build reports one file written.", "quote": "files_written=1"},
                {
                    "text": "The check run afterwards reports a checksum mismatch for export.json.",
                    "quote": "checksum mismatch: export.json",
                },
            ],
        },
        CONFIRMED,
    ),
    (
        {
            "id": "planted-contradicted",
            "claimed_severity": "P0",
            "claim": (
                "An unreadable output directory is treated as empty, so the resumed build "
                "regenerates every file and overwrites finished work."
            ),
            "evidence": (
                "$ chmod 000 d && exporter build --out d --resume\n"
                'rc=2 {"refusal": "out_dir_unreadable"}\n'
                "no file was written"
            ),
            "subclaims": [
                {
                    "text": "The build runs on the unreadable directory instead of refusing it.",
                    "quote": 'rc=2 {"refusal": "out_dir_unreadable"}',
                },
                {
                    "text": "The build writes files into the directory.",
                    "quote": "no file was written",
                },
            ],
        },
        REFUTED,
    ),
    (
        {
            "id": "planted-silent",
            "claimed_severity": "P2",
            "claim": (
                "The resume flag skips the checksum step, and line 112 of build.py is the line "
                "that skips it."
            ),
            "evidence": (
                "$ exporter build --out d --resume --verbose\n"
                "steps: plan, write\n"
                "$ exporter build --out d --verbose\n"
                "steps: plan, checksum, write"
            ),
            "subclaims": [
                {
                    "text": "With --resume the step list has no checksum step.",
                    "quote": "steps: plan, write",
                },
                {
                    "text": "Without --resume the step list includes a checksum step.",
                    "quote": "steps: plan, checksum, write",
                },
                {
                    "text": "Line 112 of build.py is the line that skips the checksum step.",
                    "quote": "--resume --verbose",
                },
            ],
        },
        NEEDS_EVIDENCE,
    ),
]


def self_test(online: bool = False, model: str = jev.DEFAULT_MODEL) -> int:
    """Offline: the quote check sorts the planted findings right. With ``online``: Jev must
    CONFIRM the supported finding, REFUTE the contradicted one and return the silent one."""
    problems: list[str] = []
    checks = 0
    for finding, expect in OFFLINE_PLANTED:
        checks += 1
        got = check_quotes(finding)["verdict"]
        if got != expect:
            problems.append(f"{finding['id']}: expected {expect}, got {got}")
    checks += 1
    relaxed = check_quotes(OFFLINE_PLANTED[2][0], require_quotes=False)["verdict"]
    if relaxed != UNCHECKED:
        problems.append(f"planted-unquoted, quotes not required: expected UNCHECKED, got {relaxed}")
    if online:
        rows = verify([f for f, _ in ONLINE_PLANTED], judge=jev_judge(model, jev.api_key()))
        errors = [r["api_error"] for r in rows if r.get("api_error")]
        if errors:
            print(f"{TOOL}: self-test: no judgment from the API: {errors[0]}", file=sys.stderr)
            return 2
        for row, (finding, expect) in zip(rows, ONLINE_PLANTED):
            checks += 1
            p = row.get("p_supported")
            print(f"  {row['id']}: {row['verdict']} p_supported={p} {row['why']}")
            if row["verdict"] != expect:
                problems.append(f"{finding['id']}: expected {expect}, got {row['verdict']}")
    print(json.dumps({"checks": checks, "problems": problems}, indent=1))
    return 0 if not problems else 1


def _print_rows(rows: list[dict[str, Any]]) -> None:
    width = max([len(str(r["id"])) for r in rows] + [2])
    print(f"{'id'.ljust(width)}  {'verdict':<14}  {'p_sup':>5}  why")
    for r in rows:
        p = r.get("p_supported")
        shown = f"{p:.2f}" if isinstance(p, float) else "-"
        flags = f"  [{', '.join(r['flags'])}]" if r.get("flags") else ""
        print(f"{str(r['id']).ljust(width)}  {r['verdict']:<14}  {shown:>5}  {r['why']}{flags}")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("\n" + ", ".join(f"{n} {v}" for v, n in sorted(counts.items())))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bapu-findings",
        description="Check that review findings quote their evidence verbatim.",
        epilog=(
            "Offline by default. --online needs TYPESAFE_API_KEY. Exit codes: 0 every finding "
            "settled, 1 NEEDS-EVIDENCE, UNCHECKED or ESCALATE, 2 usage or input error or no API "
            "judgment."
        ),
    )
    parser.add_argument("findings", nargs="?", type=Path, help="findings JSON file")
    parser.add_argument("--online", action="store_true", help="also score support with Jev")
    parser.add_argument("--model", default=jev.DEFAULT_MODEL, help="exact Jev model id")
    parser.add_argument(
        "--allow-unquoted",
        action="store_true",
        help="accept sub-claims without a quote (online judges them; offline cannot)",
    )
    parser.add_argument("--out", type=Path, help="also write the verdicts JSON here")
    parser.add_argument("--self-test", action="store_true", help="run the planted checks")
    parser.add_argument("--json", action="store_true", help="print the verdicts as JSON")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.online and not jev.api_key_is_set():
        print(f"{TOOL}: {jev.ENV_KEY} is not set; --online needs it", file=sys.stderr)
        return 2
    if args.self_test:
        if args.findings is not None:
            parser.error("--self-test takes no FILE")
        return self_test(online=args.online, model=args.model)
    if args.findings is None:
        parser.error("FILE is required (a findings JSON file)")
    try:
        findings = load_findings(args.findings)
    except InputError as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2
    judge = jev_judge(args.model, jev.api_key()) if args.online else None
    rows = verify(findings, require_quotes=not args.allow_unquoted, judge=judge)
    document = {
        "tool": TOOL,
        "tool_version": __version__,
        "mode": "online" if args.online else "offline",
        "model": args.model if args.online else None,
        "verdicts": rows,
    }
    text = json.dumps(document, ensure_ascii=False, indent=1)
    if args.out is not None:
        try:
            args.out.write_text(text + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"{TOOL}: cannot write {args.out}: {exc}", file=sys.stderr)
            return 2
    if args.json:
        print(text)
    else:
        _print_rows(rows)
    errors = [r["api_error"] for r in rows if r.get("api_error")]
    if errors:
        print(
            f"{TOOL}: no judgment from the API for {len(errors)} finding(s): {errors[0]}",
            file=sys.stderr,
        )
    return exit_code(rows)


if __name__ == "__main__":
    raise SystemExit(main())
