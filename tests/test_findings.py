from __future__ import annotations

import json
from pathlib import Path

import pytest

from bapu import findings, jev
from conftest import FIXTURES
from helpers import noul

FILE = FIXTURES / "findings" / "findings.json"


def _by_id(rows: list) -> dict:
    return {row["id"]: row for row in rows}


def _load(fid: str) -> dict:
    return next(f for f in findings.load_findings(FILE) if f["id"] == fid)


# ---- offline quote checks ------------------------------------------------------------------


def test_offline_verdicts_on_the_fixture(capsys):
    rows = _by_id(findings.verify(findings.load_findings(FILE)))
    assert rows["known-good"]["verdict"] == findings.QUOTED
    assert rows["paraphrased-quote"]["verdict"] == findings.NEEDS_EVIDENCE
    assert "sub-claim(s) [1]" in rows["paraphrased-quote"]["why"]
    assert rows["unquoted"]["verdict"] == findings.NEEDS_EVIDENCE
    assert "[1] quote nothing" in rows["unquoted"]["why"]
    assert rows["no-subclaims"]["verdict"] == findings.NEEDS_EVIDENCE
    assert findings.main([str(FILE)]) == 1


def test_a_file_whose_every_finding_quotes_its_evidence_exits_0(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"findings": [_load("known-good")]}), encoding="utf-8")
    assert findings.main([str(good)]) == 0
    assert "QUOTED" in capsys.readouterr().out


@pytest.mark.parametrize(
    "quote",
    [
        "ok=True ",
        "OK=True",
        "ok = True",
        "checksum  mismatch",
        "ok=True\n$ check\nchecksum mismatch!",
    ],
    ids=["trailing-space", "case", "spacing", "double-space", "wrong-end"],
)
def test_a_quote_must_match_verbatim(quote):
    finding = dict(_load("known-good"), subclaims=[{"text": "t", "quote": quote}])
    assert findings.check_quotes(finding)["verdict"] == findings.NEEDS_EVIDENCE


def test_a_multi_line_verbatim_quote_is_accepted():
    finding = dict(_load("known-good"), subclaims=[{"text": "t", "quote": "ok=True\n$ check"}])
    assert findings.check_quotes(finding)["verdict"] == findings.QUOTED


def test_allow_unquoted_turns_a_missing_quote_into_unchecked(capsys):
    row = findings.check_quotes(_load("unquoted"), require_quotes=False)
    assert row["verdict"] == findings.UNCHECKED
    # a quote that is present but not verbatim is refused either way
    wrong = findings.check_quotes(_load("paraphrased-quote"), require_quotes=False)
    assert wrong["verdict"] == findings.NEEDS_EVIDENCE


@pytest.mark.parametrize(
    "content, message",
    [
        ("not json", "cannot read"),
        ("{}", "expected"),
        ('{"findings": []}', "nothing to check is not a pass"),
        ('{"findings": [{"id": "a", "claim": "c"}]}', "'evidence' must be a non-empty string"),
        ('{"findings": [{"id": true, "claim": "c", "evidence": "e"}]}', "'id' must be"),
        (
            '{"findings": [{"id": "a", "claim": "c", "evidence": "e"},'
            ' {"id": "a", "claim": "c", "evidence": "e"}]}',
            "used twice",
        ),
        (
            '{"findings": [{"id": "a", "claim": "c", "evidence": "e",'
            ' "subclaims": [{"text": "t", "quote": ""}]}]}',
            "empty or non-string quote",
        ),
    ],
    ids=[
        "not-json",
        "no-findings-key",
        "empty-list",
        "missing-evidence",
        "bool-id",
        "duplicate-id",
        "empty-quote",
    ],
)
def test_malformed_input_exits_2_with_the_reason(tmp_path, capsys, content, message):
    path = tmp_path / "f.json"
    path.write_text(content, encoding="utf-8")
    assert findings.main([str(path)]) == 2
    assert message in capsys.readouterr().err


def test_json_output_and_out_file(tmp_path, capsys):
    out = tmp_path / "verdicts.json"
    assert findings.main([str(FILE), "--json", "--out", str(out)]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads(out.read_text(encoding="utf-8"))
    assert printed["mode"] == "offline" and len(printed["verdicts"]) == 4


# ---- online support scoring, with a fake API ---------------------------------------------


def _answers(
    shown: dict,
    false: dict | None = None,
    reach: float = 0.9,
    severity: str = "P1",
    whole: float = 0.8,
):
    """An ``answer`` function: ``shown`` maps sub-claim index to P(shown), ``false`` to P(false)."""
    levels = [lvl["level"] for lvl in findings.SEVERITY_LEVELS]

    def answer(qid, question, state):
        if qid.startswith("shown_"):
            return noul(shown[int(qid.split("_")[1])])
        if qid.startswith("false_"):
            return noul((false or {})[int(qid.split("_")[1])])
        if qid == "supported":
            return noul(whole)
        if qid == "reachable":
            return noul(reach)
        if qid == "severity":
            probabilities = {
                str(i): (0.9 if lvl == severity else 0.05) for i, lvl in enumerate(levels)
            }
            legend = {str(i): lvl for i, lvl in enumerate(findings.SEVERITY_LEVELS)}
            return {"type": "score", "probabilities": probabilities, "legend": legend}
        raise AssertionError(qid)

    return answer


def _online(finding: dict) -> dict:
    (row,) = findings.verify([finding], judge=findings.jev_judge())
    return row


def test_every_subclaim_shown_is_confirmed_with_one_request(fake_api):
    api = fake_api(_answers({0: 0.93, 1: 0.88}, whole=0.99))
    row = _online(_load("known-good"))
    assert row["verdict"] == findings.CONFIRMED
    assert row["p_supported"] == 0.88
    assert row["subclaim_status"] == [findings.SHOWN, findings.SHOWN]
    assert len(api.requests) == 1  # no second pass without a low tail
    assert row["flags"] == []


def test_a_contradicted_subclaim_refutes_the_finding(fake_api):
    api = fake_api(_answers({0: 0.9, 1: 0.1}, false={1: 0.9}))
    row = _online(_load("known-good"))
    assert row["verdict"] == findings.REFUTED
    assert row["subclaim_status"] == [findings.SHOWN, findings.CONTRADICTED]
    assert len(api.requests) == 2
    assert set(api.requests[1]["body"]["questions"]) == {"false_1"}


def test_a_subclaim_the_evidence_is_silent_on_returns_the_finding(fake_api):
    fake_api(_answers({0: 0.9, 1: 0.1}, false={1: 0.2}, whole=0.99))
    row = _online(_load("known-good"))
    assert row["verdict"] == findings.NEEDS_EVIDENCE
    assert row["subclaim_status"] == [findings.SHOWN, findings.ABSENT]
    # silence does not drag the minimum down: p_supported comes from the shown sub-claims
    assert row["p_supported"] == 0.9


@pytest.mark.parametrize(
    "p, verdict",
    [
        (0.3, findings.ESCALATE),
        (0.5, findings.ESCALATE),
        (0.75, findings.ESCALATE),
        (0.7501, findings.CONFIRMED),
    ],
)
def test_the_grey_band_escalates(fake_api, p, verdict):
    fake_api(_answers({0: 0.95, 1: p}))
    assert _online(_load("known-good"))["verdict"] == verdict


def test_classify_bounds():
    assert findings.classify(0.2999) == findings.REFUTED
    assert findings.classify(0.3) == findings.ESCALATE
    assert findings.classify(0.75) == findings.ESCALATE
    assert findings.classify(0.7501) == findings.CONFIRMED


def test_severity_and_reachability_are_flags_not_verdicts(fake_api):
    fake_api(_answers({0: 0.95, 1: 0.95}, reach=0.4, severity="P0"))
    row = _online(_load("known-good"))  # claimed P1
    assert row["verdict"] == findings.CONFIRMED
    assert row["severity"] == "P0"
    assert row["flags"] == ["reachability_unclear", "severity_disputed"]


def test_a_finding_that_fails_the_quote_check_never_reaches_the_api(fake_api):
    api = fake_api(_answers({0: 0.95, 1: 0.95}))
    row = _online(_load("paraphrased-quote"))
    assert row["verdict"] == findings.NEEDS_EVIDENCE
    assert api.requests == []


def test_no_subclaims_falls_back_to_the_whole_claim_when_quotes_are_optional(fake_api):
    fake_api(_answers({}))
    (row,) = findings.verify(
        [_load("no-subclaims")], require_quotes=False, judge=findings.jev_judge()
    )
    assert row["verdict"] == findings.CONFIRMED  # supported = 0.8
    assert row["why"] == "whole claim only"


def test_an_api_failure_escalates_and_exits_2(fake_api, tmp_path, capsys):
    fake_api(lambda qid, question, state: {"type": "noul"})  # an answer with no value
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"findings": [_load("known-good")]}), encoding="utf-8")
    assert findings.main([str(good), "--online"]) == 2
    captured = capsys.readouterr()
    assert "ESCALATE" in captured.out
    assert "no judgment from the API" in captured.err


def test_online_without_a_key_exits_2(capsys):
    assert findings.main([str(FILE), "--online"]) == 2
    assert jev.ENV_KEY in capsys.readouterr().err


def test_a_claim_that_says_more_than_its_subclaims_goes_back(fake_api):
    fake_api(_answers({0: 0.95, 1: 0.95}, whole=0.05))
    row = _online(_load("known-good"))
    assert row["verdict"] == findings.NEEDS_EVIDENCE
    assert "the claim as a whole is not" in row["why"]


def test_the_whole_claim_takes_part_in_the_minimum(fake_api):
    fake_api(_answers({0: 0.95, 1: 0.95}, whole=0.5))
    row = _online(_load("known-good"))
    assert (row["verdict"], row["p_supported"]) == (findings.ESCALATE, 0.5)


def test_unchecked_findings_exit_1(tmp_path, capsys):
    path = tmp_path / "unquoted.json"
    path.write_text(json.dumps({"findings": [_load("unquoted")]}), encoding="utf-8")
    assert findings.main([str(path), "--allow-unquoted"]) == 1
    assert "UNCHECKED" in capsys.readouterr().out


def test_an_escalated_finding_exits_1(fake_api, tmp_path, capsys):
    fake_api(_answers({0: 0.95, 1: 0.5}))
    path = tmp_path / "good.json"
    path.write_text(json.dumps({"findings": [_load("known-good")]}), encoding="utf-8")
    assert findings.main([str(path), "--online"]) == 1
    assert "ESCALATE" in capsys.readouterr().out


def test_a_confirmed_finding_exits_0(fake_api, tmp_path):
    fake_api(_answers({0: 0.95, 1: 0.95}))
    path = tmp_path / "good.json"
    path.write_text(json.dumps({"findings": [_load("known-good")]}), encoding="utf-8")
    assert findings.main([str(path), "--online"]) == 0


def test_the_offline_self_test_passes(capsys):
    assert findings.main(["--self-test"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {"checks": len(findings.OFFLINE_PLANTED) + 1, "problems": []}


def test_the_self_test_catches_a_broken_quote_check(monkeypatch, capsys):
    monkeypatch.setattr(findings, "missing_quotes", lambda evidence, subclaims: [])
    assert findings.self_test() == 1
    assert "planted-paraphrased-quote" in capsys.readouterr().out


def test_an_online_self_test_without_answers_exits_2(fake_api, capsys):
    fake_api(lambda qid, question, state: {"type": "noul"})
    assert findings.main(["--self-test", "--online"]) == 2
    assert "no judgment from the API" in capsys.readouterr().err


def test_planted_self_test_findings_are_well_formed(tmp_path):
    planted = [f for f, _ in findings.OFFLINE_PLANTED + findings.ONLINE_PLANTED]
    path = Path(tmp_path / "planted.json")
    path.write_text(json.dumps({"findings": planted}), encoding="utf-8")
    assert len(findings.load_findings(path)) == len(planted)
    for finding, _ in findings.ONLINE_PLANTED:
        assert findings.check_quotes(finding)["verdict"] == findings.QUOTED
