from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from bapu import gate, jev
from conftest import FIXTURES
from helpers import noul

CHANGES = FIXTURES / "gate" / "openspec" / "changes"
NOTIFICATIONS = CHANGES / "known-good" / "specs" / "notifications" / "spec.md"


def _hold_text(report: dict) -> str:
    return "\n".join(report["holds"])


# ---- offline structure: the known negative and the known positive -------------------------


def test_known_good_change_is_structure_ok(capsys):
    assert gate.main([str(CHANGES / "known-good")]) == 0
    out = capsys.readouterr().out
    assert "verdict: STRUCTURE-OK" in out
    assert "requirements=4 scenarios=3" in out


def test_known_bad_change_holds_and_names_every_planted_defect(capsys):
    report = gate.run_gate(gate.load(CHANGES / "known-bad"))
    assert report["verdict"] == gate.HOLD
    holds = _hold_text(report)
    for expected in (
        "line 10: prose inside scenario 'Notification is sent'",
        "line 13: scenario heading has three hashes",
        "line 18: empty WHEN step in 'Empty step'",
        "line 21: malformed heading",
        "scenario 'Orphaned by the malformed heading above' is outside any requirement",
        "scenario 'Notification is sent' has no WHEN step",
        "scenario 'Empty step' has no WHEN step",
        "requirement 'No scenario at all' has no scenario",
        "new capability 'notifications' has no '## Purpose' section",
    ):
        assert expected in holds
    assert len(report["holds"]) == 9
    assert gate.main([str(CHANGES / "known-bad")]) == 1


GOOD = """## Purpose

A capability used by the gate's tests.

## ADDED Requirements

### Requirement: Refuse a second invoice
The `invoice` command SHALL exit 4 when the order already has an invoice.

#### Scenario: Second invoice
- **GIVEN** order 17 already has an invoice
- **WHEN** `invoice 17` runs
- **THEN** the command exits 4
"""

#: (id, change to the known-good text, text the hold must contain). Each row plants one
#: structural defect into a copy of GOOD, so every check is shown to catch its own defect.
PLANTED = [
    ("three-hash", ("#### Scenario:", "### Scenario:"), "three hashes"),
    ("full-width-colon", ("### Requirement:", "### Requirement\uff1a"), "malformed heading"),
    ("no-name", ("### Requirement: Refuse a second invoice", "### Requirement: "), "malformed"),
    (
        "prose",
        ("- **THEN** the command exits 4", "- **THEN** the command exits 4\nIt works."),
        "prose inside scenario",
    ),
    ("code-fence", ("- **WHEN** `invoice 17` runs", "```\ninvoice 17\n```"), "prose inside"),
    ("no-when", ("- **WHEN** `invoice 17` runs\n", ""), "has no WHEN step"),
    ("no-then", ("- **THEN**", "- **AND**"), "has no THEN step"),
    ("empty-then", ("- **THEN** the command exits 4", "- **THEN**"), "empty THEN step"),
    ("lowercase-step", ("- **WHEN**", "- **When**"), "prose inside scenario"),
    ("no-scenario", ("#### Scenario: Second invoice", "Second invoice"), "has no scenario"),
    ("no-purpose", ("## Purpose", "## Background"), "has no '## Purpose' section"),
    ("orphan-scenario", ("### Requirement: Refuse a second invoice\n", ""), "outside any"),
    ("op-typo", ("## ADDED Requirements", "## Added Requirements"), "unknown operation heading"),
    ("op-lowercase", ("## ADDED Requirements", "## ADDED requirements"), "unknown operation"),
    ("op-colon", ("## ADDED Requirements", "## ADDED Requirements:"), "unknown operation"),
    ("op-three-hash", ("## ADDED Requirements", "### ADDED Requirements"), "unknown operation"),
]


def _write_change(root: Path, text: str, capability: str = "invoices") -> Path:
    directory = root / "openspec" / "changes" / "change"
    (directory / "specs" / capability).mkdir(parents=True)
    (directory / "specs" / capability / "spec.md").write_text(text, encoding="utf-8")
    return directory


def test_the_unplanted_text_is_structure_ok(tmp_path):
    assert gate.run_gate(gate.load(_write_change(tmp_path, GOOD)))["verdict"] == gate.STRUCTURE_OK


@pytest.mark.parametrize("name, change, expected", PLANTED, ids=[p[0] for p in PLANTED])
def test_each_planted_structural_defect_holds(tmp_path, name, change, expected):
    old, new = change
    assert GOOD.count(old) == 1
    report = gate.run_gate(gate.load(_write_change(tmp_path, GOOD.replace(old, new))))
    assert report["verdict"] == gate.HOLD
    assert expected in _hold_text(report)


def test_an_existing_capability_needs_no_purpose(tmp_path):
    directory = _write_change(tmp_path, GOOD.replace("## Purpose", "## Background"))
    canon = tmp_path / "openspec" / "specs" / "invoices"
    canon.mkdir(parents=True)
    (canon / "spec.md").write_text(GOOD, encoding="utf-8")
    assert gate.run_gate(gate.load(directory))["verdict"] == gate.STRUCTURE_OK


def test_specs_dir_names_the_canonical_specs_outside_the_standard_layout(tmp_path):
    change = tmp_path / "change"
    (change / "specs" / "invoices").mkdir(parents=True)
    (change / "specs" / "invoices" / "spec.md").write_text(
        GOOD.replace("## Purpose", "## Background"), encoding="utf-8"
    )
    report = gate.run_gate(gate.load(change))
    assert "pass --specs-dir" in _hold_text(report)
    canon = tmp_path / "canon" / "invoices"
    canon.mkdir(parents=True)
    (canon / "spec.md").write_text(GOOD, encoding="utf-8")
    assert gate.main([str(change), "--specs-dir", str(tmp_path / "canon")]) == 0


def test_a_change_without_delta_specs_holds(tmp_path):
    (tmp_path / "empty-change").mkdir()
    report = gate.run_gate(gate.load(tmp_path / "empty-change"))
    assert report["verdict"] == gate.HOLD
    assert "no delta spec" in _hold_text(report)


def test_a_delta_without_requirements_holds(tmp_path):
    report = gate.run_gate(
        gate.load(_write_change(tmp_path, "## ADDED Requirements\n\nNothing.\n"))
    )
    assert "specs/invoices/spec.md: holds no '### Requirement:' block" in _hold_text(report)


def test_every_delta_file_must_hold_a_requirement(tmp_path):
    directory = _write_change(tmp_path, GOOD)
    (directory / "specs" / "empty").mkdir()
    (directory / "specs" / "empty" / "spec.md").write_text("## ADDED Requirements\n", "utf-8")
    report = gate.run_gate(gate.load(directory))
    assert report["verdict"] == gate.HOLD
    assert "specs/empty/spec.md: holds no '### Requirement:' block" in _hold_text(report)


def test_a_missing_path_exits_2(tmp_path, capsys):
    assert gate.main([str(tmp_path / "nowhere")]) == 2
    assert "no such change directory" in capsys.readouterr().err


def test_a_single_spec_file_is_checked_on_its_own(capsys):
    target = CHANGES / "known-good" / "specs" / "notifications" / "spec.md"
    assert gate.main([str(target)]) == 0
    assert "deltas=1 requirements=1" in capsys.readouterr().out


def test_and_continues_the_step_kind_before_it():
    text = (
        "### Requirement: R\nThe tool SHALL do one thing.\n\n#### Scenario: S\n"
        "- **GIVEN** a\n- **AND** b\n- **WHEN** c\n- **AND** d\n- **THEN** e\n- **AND** f\n"
    )
    (req,), problems = gate.parse_spec(text)
    assert problems == []
    (scn,) = req.scenarios
    assert (scn.given, scn.when, scn.then) == (["a", "b"], ["c", "d"], ["e", "f"])
    assert req.text == "The tool SHALL do one thing."


def test_the_receipt_digest_covers_the_bytes_that_were_judged(tmp_path):
    directory = _write_change(tmp_path, GOOD)
    change = gate.load(directory)
    judged = gate.files_sha256(change)
    spec = directory / "specs" / "invoices" / "spec.md"
    spec.write_text(GOOD.replace("exits 4", "exits 5"), encoding="utf-8")  # edited mid-run
    assert gate.files_sha256(change) == judged
    assert gate.files_sha256(gate.load(directory)) != judged


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks on this platform")
def test_a_symlinked_delta_directory_is_checked(tmp_path):
    directory = _write_change(tmp_path, GOOD)
    elsewhere = tmp_path / "elsewhere" / "notes"
    elsewhere.mkdir(parents=True)
    (elsewhere / "spec.md").write_text(GOOD.replace("- **THEN**", "- **AND**"), "utf-8")
    try:
        os.symlink(elsewhere, directory / "specs" / "notes", target_is_directory=True)
    except OSError as exc:  # e.g. no symlink privilege
        pytest.skip(f"cannot create a symlink here: {exc}")
    report = gate.run_gate(gate.load(directory))
    assert "deltas=2" in report["population"]
    assert "specs/notes/spec.md: scenario 'Second invoice' has no THEN step" in _hold_text(report)


def test_crlf_line_endings_parse_like_lf(tmp_path):
    crlf = GOOD.replace("\n", "\r\n")
    report = gate.run_gate(gate.load(_write_change(tmp_path, crlf)))
    assert report["verdict"] == gate.STRUCTURE_OK


# ---- online scoring, with a fake API -------------------------------------------------------


def _constant(p: float):
    return lambda qid, question, state: noul(p)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A private copy of the fixture ``openspec`` tree (canonical specs and changes)."""
    shutil.copytree(FIXTURES / "gate" / "openspec", tmp_path / "openspec")
    return tmp_path / "openspec"


def test_online_pass_writes_a_receipt_that_is_current(fake_api, tree, capsys):
    change = tree / "changes" / "known-good"
    api = fake_api(_constant(0.92))
    assert gate.main([str(change), "--online"]) == 0
    assert "verdict: PASS" in capsys.readouterr().out
    # two asks (original + paraphrase) per judged requirement; REMOVED is never judged
    assert len(api.requests) == 2 * 3
    receipt = json.loads((change / gate.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert receipt["verdict"] == gate.PASS and receipt["model_answered"] == jev.DEFAULT_MODEL
    assert gate.main([str(change), "--check-receipt"]) == 0


def test_every_question_below_the_threshold_holds(fake_api):
    fake_api(_constant(0.08))
    report = gate.run_gate(gate.load(NOTIFICATIONS), gate.jev_asker(), jev.DEFAULT_MODEL)
    assert report["verdict"] == gate.HOLD
    assert len(report["holds"]) == 5  # three requirement questions, two scenario questions


@pytest.mark.parametrize(
    "p, verdict",
    [
        (0.44, gate.HOLD),
        (0.45, gate.HOLD),
        (0.5, gate.HOLD),
        (0.55, gate.HOLD),
        (0.5501, gate.PASS),
        (0.92, gate.PASS),
    ],
)
def test_the_hold_band_includes_both_ends(fake_api, p, verdict):
    fake_api(_constant(p))
    report = gate.run_gate(gate.load(NOTIFICATIONS), gate.jev_asker(), jev.DEFAULT_MODEL)
    assert report["verdict"] == verdict


def test_the_stored_score_is_the_lower_of_original_and_paraphrase(fake_api):
    def answer(qid, question, state):
        paraphrase = question["instructions"].startswith("Count the separate behaviours")
        return noul(0.4 if paraphrase else 0.9)

    fake_api(answer)
    report = gate.run_gate(gate.load(NOTIFICATIONS), gate.jev_asker(), jev.DEFAULT_MODEL)
    row = report["requirements"][0]
    assert row["raw"]["single_behavior"] == {"original": 0.9, "paraphrase": 0.4}
    assert row["single_behavior"] == 0.4
    assert report["verdict"] == gate.HOLD


def test_a_structural_hold_is_never_sent_to_the_api(fake_api):
    api = fake_api(_constant(0.92))
    report = gate.run_gate(gate.load(CHANGES / "known-bad"), gate.jev_asker(), jev.DEFAULT_MODEL)
    assert report["verdict"] == gate.HOLD
    assert "online scoring skipped" in _hold_text(report)
    assert api.requests == []


def test_a_removed_only_delta_is_pass_unjudged(fake_api, capsys):
    api = fake_api(_constant(0.92))
    assert gate.main([str(CHANGES / "removed-only"), "--online", "--no-receipt"]) == 1
    assert "verdict: PASS-UNJUDGED" in capsys.readouterr().out
    assert api.requests == []


def test_online_without_a_key_exits_2(capsys):
    assert gate.main([str(CHANGES / "known-good"), "--online"]) == 2
    assert jev.ENV_KEY in capsys.readouterr().err


def test_an_api_failure_exits_2_and_writes_no_receipt(fake_api, tree, capsys):
    change = tree / "changes" / "known-good"

    def answer(qid, question, state):
        return {"type": "noul"}  # no value: a broken answer, never a 0.0

    fake_api(answer)
    assert gate.main([str(change), "--online"]) == 2
    assert "no judgment from the API" in capsys.readouterr().err
    assert not (change / gate.RECEIPT_NAME).exists()


def test_an_answer_from_another_model_is_refused(fake_api):
    fake_api(_constant(0.92), model="jev-other")
    with pytest.raises(jev.JevError, match="model mismatch"):
        gate.run_gate(gate.load(CHANGES / "known-good"), gate.jev_asker(), jev.DEFAULT_MODEL)


# ---- receipts --------------------------------------------------------------------------------


@pytest.fixture
def passed(fake_api, tree):
    """The copied known-good change with a fresh online PASS receipt."""
    change = tree / "changes" / "known-good"
    fake_api(_constant(0.92))
    assert gate.main([str(change), "--online"]) == 0
    return change


def _check(change: Path) -> tuple:
    return gate.check_receipt(gate.load(change), change / gate.RECEIPT_NAME)


def test_a_fresh_receipt_is_current(passed):
    assert _check(passed) == (True, "current PASS")


def test_editing_the_spec_stales_the_receipt(passed):
    spec = passed / "specs" / "notifications" / "spec.md"
    spec.write_text(spec.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    ok, why = _check(passed)
    assert not ok and why.startswith("stale")


def test_a_tampered_score_is_caught_even_with_a_pass_verdict(passed):
    path = passed / gate.RECEIPT_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    row = data["requirements"][0]
    row["raw"]["observable"]["paraphrase"] = row["observable"] = 0.52
    path.write_text(json.dumps(data), encoding="utf-8")
    ok, why = _check(passed)
    assert not ok and "hold band" in why


def test_a_stored_score_above_its_asks_is_caught(passed):
    path = passed / gate.RECEIPT_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    data["requirements"][0]["raw"]["observable"]["paraphrase"] = 0.3
    path.write_text(json.dumps(data), encoding="utf-8")
    ok, why = _check(passed)
    assert not ok and "not the lower of its two asks" in why


def test_a_receipt_missing_a_requirement_row_is_not_current(passed):
    path = passed / gate.RECEIPT_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    data["requirements"].pop()
    path.write_text(json.dumps(data), encoding="utf-8")
    ok, why = _check(passed)
    assert not ok and "receipt rows for" in why


def test_a_receipt_from_another_model_is_not_current(passed):
    ok, why = gate.check_receipt(gate.load(passed), passed / gate.RECEIPT_NAME, "jev-other")
    assert not ok and "not answered by jev-other" in why


@pytest.mark.parametrize(
    "content",
    ["", "not json", "[]", '{"tool": "bapu-gate"}'],
    ids=["empty", "not-json", "list", "foreign"],
)
def test_unreadable_or_foreign_receipts_are_not_current(passed, content):
    (passed / gate.RECEIPT_NAME).write_text(content, encoding="utf-8")
    ok, _ = _check(passed)
    assert not ok


def test_a_missing_receipt_exits_1(tree, capsys):
    change = tree / "changes" / "known-good"
    assert gate.main([str(change), "--check-receipt"]) == 1
    assert "no receipt" in capsys.readouterr().out


def _tamper(change: Path, edit) -> tuple:
    path = change / gate.RECEIPT_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    return _check(change)


def test_a_receipt_row_for_another_requirement_is_not_current(passed):
    ok, why = _tamper(passed, lambda d: d["requirements"][0].update(name="Something else"))
    assert not ok and "is not requirement 'One invoice per order'" in why


def test_an_unjudged_receipt_row_is_not_current(passed):
    ok, why = _tamper(passed, lambda d: d["requirements"][0].update(judged=False))
    assert not ok and "was not judged" in why


def test_receipt_scenarios_must_match_the_change(passed):
    def rename(data):
        data["requirements"][0]["scenarios"][0]["name"] = "Renamed"

    ok, why = _tamper(passed, rename)
    assert not ok and "do not match the change" in why


@pytest.mark.parametrize("value", ["0.92", True], ids=["string", "boolean"])
def test_a_malformed_receipt_score_is_not_current(passed, value):
    def corrupt(data):
        data["requirements"][0]["raw"]["observable"]["original"] = value

    ok, why = _tamper(passed, corrupt)
    assert not ok and "holds a malformed score" in why


def test_a_receipt_with_nothing_judged_is_not_current(tree):
    change = tree / "changes" / "removed-only"
    report = gate.run_gate(gate.load(change))
    report["verdict"] = gate.PASS  # forged: nothing was judged
    (change / gate.RECEIPT_NAME).write_text(json.dumps(report), encoding="utf-8")
    ok, why = _check(change)
    assert not ok and "no requirement was judged" in why


def test_the_offline_self_test_passes(capsys):
    assert gate.main(["--self-test"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {"checks": len(gate._STRUCTURAL_POSITIVES) + 7, "problems": []}


def test_the_self_test_catches_a_broken_gate(monkeypatch, capsys):
    monkeypatch.setattr(gate, "structure_problems", lambda change: [])
    assert gate.self_test() == 1
    assert "three-hash: expected HOLD" in capsys.readouterr().out


def test_an_online_self_test_without_answers_exits_2(fake_api, capsys):
    fake_api(lambda qid, question, state: {"type": "noul"})
    assert gate.main(["--self-test", "--online"]) == 2
    assert "no judgment from the API" in capsys.readouterr().err
