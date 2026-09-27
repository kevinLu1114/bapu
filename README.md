# Bapu

**以既有上游為基礎，整合 Mac 上從 agent 到推論的開發環境。**

*If it can't fail, it didn't pass.*

[![tests](https://github.com/kevinLu1114/bapu/actions/workflows/tests.yml/badge.svg)](https://github.com/kevinLu1114/bapu/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python: 3.9 to 3.13](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)

Bapu 的長期方向是減少 Mac 開發環境中 agent、工具與推論服務的手動整合工作，而不是重做上游產品。
預設以 OMP 承接日常流程，整合契約保持 harness-neutral；版本管理須記錄精確上游版本、本地修補與實際驗證過的組合。
這些是產品方向，不是目前已交付的完整平台：跨 harness adapters、推論服務部署與自動升級尚未實作。

目前的 `0.1.0` 提供下列三個可獨立使用的驗證 CLI：

| Tool | What it checks |
|---|---|
| `bapu-gate` | OpenSpec delta specs, clause by clause, before any code is written |
| `bapu-seedred` | every test, by planting the defect it guards and requiring it to fail |
| `bapu-findings` | every review finding, by requiring its claims to quote the evidence verbatim |

All three run offline, on Python 3.9 or newer, with no dependencies. `bapu-gate` and
`bapu-findings` also have an optional online mode that asks a judgment model for scores.

## Why

AI agents write code, specs and review comments faster than people can check them, so the
bottleneck has moved: it is no longer producing a change, it is verifying the claims that come
with it. Bapu targets three failure shapes that pass a quick look:

- **a green test that cannot fail**: the defect it is supposed to guard can be planted and the
  test stays green;
- **a spec clause that bundles several behaviours**, so no single test, and no reviewer, can
  check it as written;
- **a review finding whose claim its own evidence does not support**: the quoted output was
  never pasted, or says something else.

Each tool turns one of these into a mechanical check with a known positive and a known negative,
so "it passed" means something.

For open-source maintainers the same idea applies from the other side: an AI-assisted issue or
pull request should carry its own reproducible evidence, so that a maintainer can verify it
instead of trusting it. [docs/case-study-splash-122.md](docs/case-study-splash-122.md) walks
through a public example.

## Install


```
git clone https://github.com/kevinLu1114/bapu
cd bapu
pip install -e ".[dev]"
```

`bapu-seedred` runs your tests with pytest, so pytest must be installed in the interpreter it
uses (`--python`, by default the one running Bapu).

## Quickstart (offline)

The commands below use the files in [`examples/`](examples/) and need no key and no network.

**Check a spec before writing code.**

```
$ bapu-gate examples/openspec/changes/add-overwrite-guard
POPULATION target=add-overwrite-guard deltas=1 requirements=2 scenarios=2 model=offline files_sha256=8e9514bae04f
verdict: STRUCTURE-OK

$ bapu-gate examples/openspec/changes/draft-audit-log
...
  hold: structure: specs/audit-log/spec.md: scenario 'Exports are audited' has no THEN step
  hold: structure: specs/audit-log/spec.md: requirement 'Audit entries are readable' has no scenario
  hold: structure: specs/audit-log/spec.md: new capability 'audit-log' has no '## Purpose' section
verdict: HOLD
```

**Prove that each test can fail.**

```
$ bapu-seedred examples/seedred/table.json --root examples/seedred
[cap] RED       before=passed after=failed restored=passed  tests/test_retry.py::test_delays_never_exceed_the_cap
[doubling] RED       before=passed after=failed restored=passed  tests/test_retry.py::test_delays_double_each_attempt
[negative] RED       before=passed after=failed restored=passed  tests/test_retry.py::test_negative_attempts_are_refused

3/3 mutations went red

$ bapu-seedred examples/seedred/table-weak.json --root examples/seedred
[cap-with-the-wrong-test] NOT-RED   before=passed after=passed restored=passed  tests/test_retry.py::test_delays_double_each_attempt
      the mutation survived: the test still passes with the defect planted
...
0/1 mutations went red
```

Every mutated file is restored byte for byte, timestamps included.

**Check that review findings quote their evidence.**

```
$ bapu-findings examples/findings.json
id  verdict         p_sup  why
F1  QUOTED              -  every sub-claim quotes the evidence verbatim
F2  NEEDS-EVIDENCE      -  quote not found verbatim in the evidence: sub-claim(s) [0]
F3  NEEDS-EVIDENCE      -  sub-claim(s) [0] quote nothing from the evidence

2 NEEDS-EVIDENCE, 1 QUOTED
```

Each tool exits 0 when everything checked out, 1 when something needs attention, and 2 when it
could not check (a usage or input error, or a run that produced no result). Every tool has
`--json`; `bapu-gate` and `bapu-findings` have `--self-test`, and `bapu-seedred` has `--check`,
which validates a table without running it. Without the console scripts, run
`python -m bapu gate|seedred|findings`.

## Optional online mode

`bapu-gate --online` and `bapu-findings --online` ask TypeSafe's System One model, Jev, for
bounded judgments: whether a clause states one observable behaviour, whether a scenario is
testable, whether the evidence shows each sub-claim. Online mode is used only when you pass
`--online` **and** the `TYPESAFE_API_KEY` environment variable is set; otherwise nothing is sent.

```
export TYPESAFE_API_KEY=...        # your own key
bapu-gate --self-test --online     # known-good and known-bad clauses, judged live
bapu-gate openspec/changes/my-change --online
bapu-gate openspec/changes/my-change --check-receipt   # offline, for CI
```

Scores rank what a person should look at first. They never authorise anything on their own.
See [docs/online-mode.md](docs/online-mode.md) for what is sent and how answers are used.

## How the pieces fit

```
spec --> bapu-gate --> implement --> bapu-seedred --> independent review --> bapu-findings --> land
          HOLD:                       NOT-RED:                                NEEDS-EVIDENCE:
          fix the clause              fix the test                            back to the reviewer
```

This repository applies the tools to itself: [`seedred.json`](seedred.json) plants defects in
`src/bapu/`, each paired with the test that must catch it, and continuous integration requires
every one of them to turn its test red.

## Documentation

- [docs/workflow.md](docs/workflow.md): the workflow, step by step
- [docs/gate.md](docs/gate.md): `bapu-gate` rules, questions, thresholds and receipts
- [docs/seedred.md](docs/seedred.md): `bapu-seedred` tables, verdicts and safety
- [docs/evidence.md](docs/evidence.md): `bapu-findings` input, verdicts and limits
- [docs/online-mode.md](docs/online-mode.md): the optional online mode
- [docs/case-study-splash-122.md](docs/case-study-splash-122.md): a public, evidence-first issue

## Contributing

Contributions are welcome, and they follow the same evidence rules the tools check. See
[CONTRIBUTING.md](CONTRIBUTING.md). Please report security issues privately, as described in
[SECURITY.md](SECURITY.md). Everyone taking part is expected to follow the
[code of conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE)
