from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from bapu import seedred
from bapu.seedred import FAILED, NO_RESULT, NOT_RUN, PASSED, Row
from conftest import FIXTURES

GUARDED = FIXTURES / "seedred" / "guarded.json"
UNGUARDED = FIXTURES / "seedred" / "unguarded.json"
PRICING = "pricing.py"
CAPPED = "tests/test_pricing.py::test_discount_is_capped_at_fifty_percent"


def _row(**changes) -> Row:
    fields = dict(
        id="cap",
        file=PRICING,
        anchor="    if percent > 50:",
        replacement="    if False:",
        test=CAPPED,
    )
    fields.update(changes)
    return Row(**fields)


def _write_table(path: Path, rows: list) -> Path:
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    return path


# ---- anchors -------------------------------------------------------------------------------


def test_an_anchor_counts_only_at_the_start_of_a_line():
    text = "def f():\n    if x:\n        if x:\n            pass\n"
    assert seedred.count_anchor(text, "    if x:") == 1  # not the one indented to eight
    assert seedred.count_anchor(text, "        if x:") == 1
    assert seedred.count_anchor(text, "if x:") == 0
    assert seedred.count_anchor(text, "") == 0


def test_replace_anchor_mutates_what_count_anchor_counted():
    text = "a = 1\n    a = 1\n"
    assert seedred.replace_anchor(text, "    a = 1", "    a = 2") == "a = 1\n    a = 2\n"
    assert seedred.replace_anchor(text, "missing", "x") == text


def test_an_anchor_may_stop_mid_line_or_carry_its_newline():
    text = "total = price * (100 - percent)\nreturn total\n"
    assert seedred.count_anchor(text, "total = price * (100 -") == 1
    assert seedred.replace_anchor(text, "return total\n", "") == "total = price * (100 - percent)\n"


# ---- pytest's count line -------------------------------------------------------------------


@pytest.mark.parametrize(
    "output, outcome",
    [
        ("1 failed in 0.05s", FAILED),
        ("1 passed in 0.01s", PASSED),
        ("==== 1 failed, 2 passed in 0.12s ====", FAILED),
        ("=== 3 passed, 1 warning in 1.00s ===", PASSED),
        ("4 passed in 67.09s (0:01:07)", PASSED),
        ("no tests ran in 0.01s", NO_RESULT),
        ("1 error in 0.10s", NO_RESULT),
        ("1 skipped in 0.10s", NO_RESULT),
        ("1 xfailed in 0.10s", NO_RESULT),
        ("", NO_RESULT),
        ("log: 2 failed in 0.3s from a nested run\n1 passed in 0.50s", PASSED),
        ("2 failed in 0.30s\n1 passed in 0.50s", PASSED),
        ("Traceback ... AssertionError: 1 failed\n1 passed in 0.01s", PASSED),
    ],
    ids=[
        "failed",
        "passed",
        "ruled",
        "warnings",
        "wall-clock",
        "no-tests-ran",
        "error-only",
        "skipped-only",
        "xfailed-only",
        "empty",
        "prose-then-count",
        "last-count-wins",
        "traceback-then-count",
    ],
)
def test_the_outcome_comes_from_the_last_count_line(output, outcome):
    assert seedred.outcome_of(output) == outcome


# ---- table loading and static checks ------------------------------------------------------


def test_lists_of_lines_are_joined_and_a_bare_list_is_accepted(tmp_path):
    rows = [
        {"id": 1, "file": "a.py", "anchor": ["x", "y", ""], "replacement": ["z"], "test": "t.py::t"}
    ]
    (row,) = seedred.load_table(_write_table(tmp_path / "t.json", rows))
    assert (row.id, row.anchor, row.replacement) == ("1", "x\ny\n", "z")
    path = tmp_path / "bare.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    assert seedred.load_table(path)[0].anchor == "x\ny\n"


@pytest.mark.parametrize(
    "row, message",
    [
        ({"id": "a", "file": "f", "anchor": "x", "replacement": "y"}, "missing key(s) ['test']"),
        (
            {
                "id": "a",
                "file": "f",
                "anchor": "x",
                "replacement": "y",
                "test": "t::t",
                "replacment": "z",
            },
            "unknown key(s) ['replacment']",
        ),
        ({"id": True, "file": "f", "anchor": "x", "replacement": "y", "test": "t::t"}, "'id'"),
        ({"id": "a", "file": "f", "anchor": 3, "replacement": "y", "test": "t::t"}, "'anchor'"),
    ],
    ids=["missing-key", "unknown-key", "bool-id", "non-string-anchor"],
)
def test_malformed_rows_are_refused_by_name(tmp_path, row, message):
    with pytest.raises(seedred.TableError, match=re.escape(message)):
        seedred.load_table(_write_table(tmp_path / "t.json", [row]))


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"anchor": "if percent > 50:"}, "anchor matches 0 times"),
        ({"anchor": "    if percent"}, "anchor matches 2 times"),
        ({"replacement": "    if percent > 50:"}, "nothing is mutated"),
        ({"replacement": "    if percent >"}, "does not compile"),
        ({"anchor": ""}, "the anchor is empty"),
        ({"file": "missing.py"}, "does not exist"),
        ({"file": "../outside.py"}, "not a relative path inside the root"),
        ({"file": "/etc/hosts"}, "not a relative path inside the root"),
        ({"test": "tests/test_missing.py::test_x"}, "test file tests/test_missing.py"),
        ({"test": "tests/test_pricing.py"}, "not a pytest node id"),
    ],
    ids=[
        "anchor-unaligned",
        "anchor-twice",
        "no-op",
        "does-not-compile",
        "empty-anchor",
        "missing-file",
        "outside-root",
        "absolute-path",
        "missing-test-file",
        "not-a-node-id",
    ],
)
def test_each_static_check_names_its_problem(project, changes, message):
    problems = seedred.table_problems([_row(**changes)], project)
    assert any(message in p for p in problems), problems


def test_a_typo_in_the_replacement_is_refused_before_anything_runs(project):
    typo = seedred.table_problems([_row(replacement="    if percent > fifty:")], project)
    assert any("uses ['fifty']" in p for p in typo), typo
    # names the mutated file binds itself, or builtins, are fine
    rebinding = "    limit = 60\n    if percent > limit:"
    assert seedred.table_problems([_row(replacement=rebinding)], project) == []
    assert seedred.table_problems([_row(replacement="    if percent > int(50):")], project) == []


def test_duplicate_ids_rows_and_an_empty_table_are_problems(project):
    assert "no rows" in seedred.table_problems([], project)[0]
    twice = seedred.table_problems([_row(), _row()], project)
    assert any("ids used by more than one row" in p for p in twice)
    assert any("same experiment written twice" in p for p in twice)
    same_seed_other_test = [
        _row(),
        _row(id="b", test="tests/test_pricing.py::test_discount_is_applied"),
    ]
    assert seedred.table_problems(same_seed_other_test, project) == []


# ---- the row loop, with a fake runner -------------------------------------------------------


def _runner(project: Path, outcome_when_mutated: str = FAILED, before: str = PASSED):
    """Answers like pytest would, by looking at the file: mutated or not."""
    calls = []

    def run(row: Row):
        mutated = row.replacement in (project / row.file).read_text(encoding="utf-8")
        calls.append("after" if mutated else "clean")
        if not mutated:
            return (before if len(calls) == 1 else PASSED), ""
        return outcome_when_mutated, "E   assert 200.0 == 100.0\n1 failed in 0.01s"

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_a_caught_mutation_is_red_and_the_file_comes_back(project):
    before = (project / PRICING).read_bytes()
    runner = _runner(project)
    result = seedred.run_row(_row(), project, runner)
    assert (result["before"], result["after"], result["restored"]) == (PASSED, FAILED, PASSED)
    assert result["verdict"] == seedred.RED
    assert runner.calls == ["clean", "after", "clean"]
    assert (project / PRICING).read_bytes() == before


def test_a_surviving_mutation_is_not_red(project):
    result = seedred.run_row(_row(), project, _runner(project, outcome_when_mutated=PASSED))
    assert result["verdict"] == seedred.NOT_RED
    assert "the mutation survived" in result["reason"]


def test_a_test_that_already_fails_is_not_red_and_nothing_is_mutated(project):
    runner = _runner(project, before=FAILED)
    stat = (project / PRICING).stat()
    result = seedred.run_row(_row(), project, runner)
    assert result["verdict"] == seedred.NOT_RED
    assert (result["after"], result["restored"]) == (NOT_RUN, NOT_RUN)
    assert runner.calls == ["clean"]
    assert (project / PRICING).stat().st_mtime_ns == stat.st_mtime_ns


@pytest.mark.parametrize(
    "output, failure",
    [
        ("FAILED tests/t.py::test_a - assert 1 == 2\n1 failed in 0.01s", "AssertionError"),
        ("FAILED t.py::test_b - NameError: name 'cpa' is not defined", "NameError"),
        ("FAILED t.py::test_c - Failed: DID NOT RAISE <class 'ValueError'>", "Failed"),
        ("FAILED t.py::test_d - pkg.errors.QuotaError: over", "QuotaError"),
        ("1 failed in 0.01s", ""),
    ],
    ids=["assert", "name-error", "pytest-fail", "qualified", "no-summary"],
)
def test_the_failure_comes_from_the_short_summary(output, failure):
    assert seedred.failure_of(output) == failure


def test_a_long_node_id_still_names_its_failure_end_to_end(project, tmp_path, monkeypatch):
    # pytest cuts its short summary to the terminal width; the runner widens it, so the
    # exception survives even behind a long test name, including a narrow caller terminal.
    monkeypatch.setenv("COLUMNS", "40")
    # CI mode disables pytest's summary truncation regardless of terminal width.
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("BUILD_NUMBER", raising=False)
    long_name = "test_" + "that_the_discount_is_capped_at_fifty_percent_" * 3 + "end"
    (project / "tests" / "test_long.py").write_text(
        f"from pricing import discounted\n\ndef {long_name}():\n"
        "    assert discounted(200.0, 80) == 100.0\n",
        encoding="utf-8",
    )
    table = _write_table(
        tmp_path / "t.json",
        [
            {
                "id": "long",
                "file": PRICING,
                "anchor": "    if percent > 50:",
                "replacement": "    if percent > 50 and undefined_name:",
                "test": f"tests/test_long.py::{long_name}",
            }
        ],
    )
    # the typo check would refuse this row statically; the run-time guard is what is tested here
    rows = seedred.load_table(table)
    runner = seedred.pytest_runner(project, sys.executable, 60.0)
    result = seedred.run_row(rows[0], project, runner)
    assert result["failure"] == "NameError"
    assert result["verdict"] == seedred.NOT_RED
    assert "=====" not in result["detail"] and "   " not in result["detail"]


def test_a_mutation_that_breaks_the_module_is_not_red(project):
    def runner(row):
        if b"if False:" in (project / PRICING).read_bytes():
            return FAILED, "FAILED tests/t.py::test_x - NameError: name 'x' is not defined"
        return PASSED, "1 passed in 0.01s"

    result = seedred.run_row(_row(), project, runner)
    assert (result["before"], result["after"], result["restored"]) == (PASSED, FAILED, PASSED)
    assert (result["verdict"], result["failure"]) == (seedred.NOT_RED, "NameError")
    assert "broke the module" in result["reason"]


def test_a_file_changed_after_the_check_is_refused_at_run_time(project):
    calls = []
    with pytest.raises(seedred.TableError, match="changed after the table was checked"):
        seedred.run_row(_row(anchor="    if percent"), project, lambda row: calls.append(row))
    assert calls == []


def test_a_test_that_fails_after_the_restore_is_not_red(project):
    calls = []

    def runner(row):
        calls.append(1)
        return (PASSED if len(calls) == 1 else FAILED), ""

    result = seedred.run_row(_row(), project, runner)
    assert (result["before"], result["after"], result["restored"]) == (PASSED, FAILED, FAILED)
    assert result["verdict"] == seedred.NOT_RED
    assert "fails after the file was restored" in result["reason"]


def test_no_result_stops_the_table_unless_keep_going(project):
    rows = [
        _row(),
        _row(id="b", anchor="    if percent < 0:"),
        _row(id="c", anchor="    if percent < 0:", replacement="    if True:"),
    ]

    def no_result(row):
        return NO_RESULT, "ERROR: not found"

    summary = seedred.run_table(rows, project, no_result)
    assert [r["verdict"] for r in summary["rows"]] == ["NO-RESULT", "SKIPPED", "SKIPPED"]
    assert seedred.exit_code(summary) == 2
    summary = seedred.run_table(rows, project, no_result, keep_going=True)
    assert [r["verdict"] for r in summary["rows"]] == ["NO-RESULT"] * 3


def test_the_file_is_restored_byte_for_byte_with_its_timestamps(project):
    target = project / PRICING
    original = target.read_bytes().replace(b"\n", b"\r\n") + b"# \xff\xfe not utf-8\r\n"
    target.write_bytes(original)
    os.utime(target, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    seen = []

    def runner(row):
        seen.append(target.read_bytes())
        return (FAILED if b"if False:" in seen[-1] else PASSED), ""

    result = seedred.run_row(_row(), project, runner)
    assert result["verdict"] == seedred.RED
    assert b"    if False:\r\n" in seen[1]  # CRLF kept around the mutation
    assert b"\xff\xfe" in seen[1]  # undecodable bytes survive the round trip
    assert target.read_bytes() == original
    assert target.stat().st_mtime_ns == 1_600_000_000_000_000_000


def test_the_mutated_file_never_shares_the_original_mtime(project):
    target = project / PRICING
    stamps = []

    def runner(row):
        stamps.append(target.stat().st_mtime_ns)
        return (FAILED if len(stamps) == 2 else PASSED), ""

    seedred.run_row(_row(), project, runner)
    assert stamps[1] - stamps[0] >= 1_000_000_000
    assert stamps[2] == stamps[0]


def test_an_interrupt_mid_mutation_still_restores_the_file(project):
    target = project / PRICING
    original = target.read_bytes()

    def runner(row):
        if b"if False:" in target.read_bytes():
            raise KeyboardInterrupt
        return PASSED, "1 passed in 0.01s"

    with pytest.raises(KeyboardInterrupt):
        seedred.run_row(_row(), project, runner)
    assert target.read_bytes() == original


def test_a_signal_during_the_restore_waits_until_the_file_is_back(project, monkeypatch):
    target = project / PRICING
    original = target.read_bytes()
    stat = target.stat()
    target.write_bytes(original.replace(b"if percent > 50:", b"if False:"))
    real_utime = os.utime
    delivered = []

    def utime_with_a_signal(*args, **kwargs):
        # what the kernel would do if SIGTERM arrived mid-restore: run the installed handler
        delivered.append(signal.getsignal(signal.SIGTERM))
        delivered[-1](signal.SIGTERM, None)
        return real_utime(*args, **kwargs)

    monkeypatch.setattr(os, "utime", utime_with_a_signal)
    with seedred._signals_raise():
        with pytest.raises(KeyboardInterrupt):
            seedred.restore(target, original, stat)
    assert delivered == [seedred._INTERRUPTS.handler]
    assert target.read_bytes() == original
    assert target.stat().st_mtime_ns == stat.st_mtime_ns  # the restore ran to its end
    assert signal.getsignal(signal.SIGTERM) != seedred._INTERRUPTS.handler


def test_a_signal_outside_a_restore_interrupts_at_once():
    with seedred._signals_raise():
        for sig in (signal.SIGINT, signal.SIGTERM):
            assert signal.getsignal(sig) == seedred._INTERRUPTS.handler  # bound: compare, not `is`
        with pytest.raises(KeyboardInterrupt):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
    assert signal.getsignal(signal.SIGINT) != seedred._INTERRUPTS.handler


def test_a_failed_restore_is_loud_and_keeps_a_backup(project, monkeypatch):
    target = project / PRICING
    original = target.read_bytes()
    real_read_bytes = Path.read_bytes

    def lying_read_bytes(self):
        data = real_read_bytes(self)
        return data + b"#" if self == target and b"if False" not in data else data

    def runner(row):
        monkeypatch.setattr(Path, "read_bytes", lying_read_bytes)  # from the restore on
        return (FAILED if b"if False:" in real_read_bytes(target) else PASSED), ""

    with pytest.raises(seedred.RestoreError, match="saved at") as caught:
        seedred.run_row(_row(), project, runner)
    backup = Path(str(caught.value).rsplit("saved at ", 1)[1])
    try:
        assert real_read_bytes(backup) == original
    finally:
        backup.unlink()


# ---- end to end, with real pytest runs ------------------------------------------------------


def _main(project: Path, *args: str) -> int:
    return seedred.main([*args, "--root", str(project), "--python", sys.executable])


def test_known_negative_every_guarded_row_goes_red(project, capsys):
    before = (project / PRICING).read_bytes()
    assert _main(project, str(GUARDED)) == 0
    out = capsys.readouterr().out
    assert "3/3 mutations went red" in out
    red = [line for line in out.splitlines() if line.split()[1:2] == ["RED"]]
    assert len(red) == 3
    assert all("before=passed after=failed restored=passed" in line for line in red)
    assert (project / PRICING).read_bytes() == before


def test_known_positive_a_test_that_cannot_see_the_line_is_flagged(project, capsys):
    assert _main(project, str(UNGUARDED)) == 1
    captured = capsys.readouterr()
    assert "NOT-RED" in captured.out and "the mutation survived" in captured.out
    assert "0/1 mutations went red" in captured.out


def test_an_anchor_that_does_not_match_exactly_once_mutates_nothing(project, tmp_path, capsys):
    before = (project / PRICING).read_bytes()
    table = _write_table(
        tmp_path / "t.json",
        [
            {
                "id": "twice",
                "file": PRICING,
                "anchor": "    if percent",
                "replacement": "    if 0",
                "test": CAPPED,
            },
        ],
    )
    assert _main(project, str(table)) == 2
    err = capsys.readouterr().err
    assert "anchor matches 2 times" in err and "nothing was mutated" in err
    assert (project / PRICING).read_bytes() == before


def test_a_named_test_that_does_not_exist_gives_no_result(project, tmp_path, capsys):
    table = _write_table(
        tmp_path / "t.json",
        [
            {
                "id": "ghost",
                "file": PRICING,
                "anchor": "    if percent > 50:",
                "replacement": "    if False:",
                "test": "tests/test_pricing.py::test_does_not_exist",
            },
        ],
    )
    assert _main(project, str(table), "--json") == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["rows"][0]["verdict"] == "NO-RESULT"
    assert summary["rows"][0]["before"] == NO_RESULT
    assert "test_does_not_exist" in summary["rows"][0]["detail"]  # pytest's own complaint


def test_a_hanging_test_times_out_as_no_result(project, tmp_path, capsys):
    (project / "tests" / "test_slow.py").write_text(
        "import time\n\ndef test_slow():\n    time.sleep(30)\n", encoding="utf-8"
    )
    table = _write_table(
        tmp_path / "t.json",
        [
            {
                "id": "slow",
                "file": PRICING,
                "anchor": "    if percent > 50:",
                "replacement": "    if False:",
                "test": "tests/test_slow.py::test_slow",
            },
        ],
    )
    assert _main(project, str(table), "--timeout", "2", "--json") == 2
    row = json.loads(capsys.readouterr().out)["rows"][0]
    assert (row["before"], row["verdict"]) == ("timeout", "NO-RESULT")


def test_check_mode_collects_the_named_tests_and_mutates_nothing(project, tmp_path, capsys):
    before = (project / PRICING).read_bytes()
    assert _main(project, str(GUARDED), "--check") == 0
    assert "3 rows checked, 0 problems" in capsys.readouterr().out
    table = _write_table(
        tmp_path / "t.json",
        [
            {
                "id": "renamed",
                "file": PRICING,
                "anchor": "    if percent > 50:",
                "replacement": "    if False:",
                "test": "tests/test_pricing.py::test_renamed_away",
            },
        ],
    )
    assert _main(project, str(table), "--check") == 2
    assert "pytest collects nothing" in capsys.readouterr().out
    assert (project / PRICING).read_bytes() == before


def test_only_selects_rows_and_refuses_unknown_ids(project, capsys):
    assert _main(project, str(GUARDED), "--only", "cap") == 0
    assert "1/1 mutations went red" in capsys.readouterr().out
    assert _main(project, str(GUARDED), "--only", "nope") == 2
    assert "not in the table" in capsys.readouterr().err


def _git(project: Path, *args: str) -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True, env=env)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_uncommitted_targets_under_git_are_refused_unless_allowed(project, capsys):
    _git(project, "init", "-q")
    assert _main(project, str(GUARDED), "--only", "cap") == 2  # pricing.py is untracked
    assert "git could not restore" in capsys.readouterr().err
    assert _main(project, str(GUARDED), "--only", "cap", "--allow-dirty") == 0
    _git(project, "add", "-A")
    _git(project, "-c", "user.name=bapu", "-c", "user.email=bapu", "commit", "-q", "-m", "fixture")
    assert _main(project, str(GUARDED), "--only", "cap") == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_an_ignored_target_is_refused_because_git_cannot_restore_it(project, tmp_path, capsys):
    _git(project, "init", "-q")
    (project / ".gitignore").write_text("pricing.py\n", encoding="utf-8")
    _git(project, "add", ".gitignore", "tests", "pytest.ini")
    _git(project, "-c", "user.name=bapu", "-c", "user.email=bapu", "commit", "-q", "-m", "fixture")
    assert _main(project, str(GUARDED), "--only", "cap") == 2
    assert "!! pricing.py" in capsys.readouterr().err


def test_a_git_failure_other_than_no_repository_is_an_error(project, monkeypatch):
    class Result:
        returncode, stdout = 128, ""
        stderr = "fatal: detected dubious ownership in repository"

    monkeypatch.setattr(seedred.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(seedred.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(seedred.TableError, match="dubious ownership"):
        seedred.dirty_targets(project, [PRICING])
    Result.stderr = "fatal: not a git repository (or any of the parent directories): .git"
    assert seedred.dirty_targets(project, [PRICING]) is None
