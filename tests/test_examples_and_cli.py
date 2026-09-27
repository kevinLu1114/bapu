"""The shipped examples behave as the README says, and ``python -m bapu`` dispatches."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from bapu import __main__ as dispatcher
from bapu import __version__, findings, gate, seedred

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def test_the_good_example_change_is_structure_ok():
    target = EXAMPLES / "openspec" / "changes" / "add-overwrite-guard"
    assert gate.main([str(target)]) == 0


def test_the_draft_example_change_holds(capsys):
    assert gate.main([str(EXAMPLES / "openspec" / "changes" / "draft-audit-log")]) == 1
    out = capsys.readouterr().out
    assert out.count("hold: structure:") == 5


def test_the_canonical_example_spec_is_structure_ok():
    assert gate.main([str(EXAMPLES / "openspec" / "specs" / "export" / "spec.md")]) == 0


def test_the_findings_example_returns_two_findings_to_their_authors(capsys):
    assert findings.main([str(EXAMPLES / "findings.json")]) == 1
    assert "2 NEEDS-EVIDENCE, 1 QUOTED" in capsys.readouterr().out


def test_the_seed_red_examples(tmp_path, capsys):
    project = tmp_path / "seedred"
    shutil.copytree(EXAMPLES / "seedred", project)
    args = ["--root", str(project), "--python", sys.executable]
    assert seedred.main([str(project / "table.json"), *args]) == 0
    assert "3/3 mutations went red" in capsys.readouterr().out
    assert seedred.main([str(project / "table-weak.json"), *args]) == 1
    assert "0/1 mutations went red" in capsys.readouterr().out


def test_python_dash_m_dispatches_to_each_tool(capsys):
    assert dispatcher.main([]) == 2
    assert "usage: python -m bapu" in capsys.readouterr().out
    assert dispatcher.main(["--help"]) == 0
    assert dispatcher.main(["--version"]) == 0
    assert capsys.readouterr().out.strip().endswith(__version__)
    assert dispatcher.main(["nope"]) == 2
    assert "unknown tool" in capsys.readouterr().err
    assert dispatcher.main(["findings", str(EXAMPLES / "findings.json")]) == 1


def test_the_package_runs_as_a_module_in_a_fresh_interpreter():
    env_path = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "bapu", "gate", "--self-test"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": env_path, "PYTHONDONTWRITEBYTECODE": "1", "PATH": ""},
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert '"problems": []' in result.stdout
