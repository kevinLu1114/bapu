# bapu-gate: the clause gate

`bapu-gate` checks OpenSpec delta specs clause by clause, before any code is written.

```
bapu-gate PATH [--specs-dir DIR] [--json]
bapu-gate PATH --online [--model ID] [--receipt FILE | --no-receipt] [--json]
bapu-gate PATH --check-receipt [--receipt FILE] [--model ID]
bapu-gate --self-test [--online]
```

`PATH` is an OpenSpec change directory, whose delta specs are `specs/**/spec.md`, or a single
spec file. A canonical spec (`openspec/specs/<capability>/spec.md`) can be checked the same way.

## Offline: structure

Offline is the default. It needs no key and makes no network call.

| Rule | Held when |
|---|---|
| Scenario steps | a non-blank line inside a `#### Scenario:` block is not a `- **GIVEN**`, `- **WHEN**`, `- **THEN**` or `- **AND**` step, or a step is empty |
| Scenarios exist | a requirement (other than a REMOVED one) has no scenario |
| WHEN and THEN | a scenario has no WHEN step or no THEN step (`AND` continues the step kind before it) |
| Purpose | a delta ADDs requirements to a capability that has no canonical spec yet, and has no `## Purpose` section |
| Exact headings | a heading names a Requirement or Scenario without the exact form `### Requirement: <name>` / `#### Scenario: <name>` (ASCII colon, three and four hashes, a name), or an operation heading is not exactly `## ADDED Requirements`, `## MODIFIED Requirements`, `## REMOVED Requirements` or `## RENAMED Requirements` |
| Placement | a scenario appears outside any requirement |
| Something to check | the change has no delta spec, or a delta spec holds no requirement |

Delta specs are found under `specs/`, following symlinked directories. A capability is new when
`<specs-dir>/<capability>/spec.md` does not exist. The specs directory
is `--specs-dir`, or else `specs/` beside the nearest ancestor directory named `openspec`.
Without `--specs-dir` and outside any `openspec` directory, every capability counts as new,
and the hold message suggests `--specs-dir`.

Verdicts: **STRUCTURE-OK** (exit 0) or **HOLD** (exit 1), with one hold line per problem.

Example, on a deliberately flawed draft:

```
$ bapu-gate examples/openspec/changes/draft-audit-log
POPULATION target=draft-audit-log deltas=1 requirements=2 scenarios=1 model=offline files_sha256=253cd7a395eb
  hold: structure: specs/audit-log/spec.md: line 9: prose inside scenario 'Exports are audited': ...
  hold: structure: specs/audit-log/spec.md: line 11: scenario heading has three hashes; ...
  hold: structure: specs/audit-log/spec.md: scenario 'Exports are audited' has no THEN step
  hold: structure: specs/audit-log/spec.md: requirement 'Audit entries are readable' has no scenario
  hold: structure: specs/audit-log/spec.md: new capability 'audit-log' has no '## Purpose' section
verdict: HOLD
```

## Online: clause scores

`--online` needs the `TYPESAFE_API_KEY` environment variable; without it the gate exits 2 and
sends nothing. Scoring runs only on a change whose structure is sound: a structural HOLD is
already the verdict, so nothing is sent.

For each requirement the gate asks TypeSafe's System One model (Jev) one yes-or-no question
per property, over a state holding only the requirement's text and its scenarios:

| Question | Asked of | True when |
|---|---|---|
| `single_behavior` | the requirement | it states exactly one observable behaviour under one SHALL or MUST |
| `observable` | the requirement | a tester who never saw the code could decide from outside whether it holds |
| `no_impl_detail` | the requirement | it names no internal function or class, library choice or algorithm (interface paths, commands, flags, refusal codes and numbers are part of the contract) |
| `exercises` | each scenario | it describes a concrete situation with a concrete outcome, not the requirement restated |
| `testable` | each scenario | a test could set up its WHEN and observe its THEN |

Every requirement is asked twice: once in the original wording and once in a paraphrase of the
same questions with the same criteria. A score that crosses the threshold when the question is
merely reworded is not a stable pass, so:

- the **stored score** of each question is the **minimum** of the original and paraphrase asks;
- a question **holds** when either ask is below the **threshold, 0.5**, or inside the **hold
  band, 0.45 to 0.55, both ends included**.

Verdicts: **PASS** (exit 0) when every question of every judged requirement clears both rules;
**HOLD** (exit 1) otherwise; **PASS-UNJUDGED** (exit 1) when nothing was judged, for example a
delta that only REMOVEs requirements, so that "no judge ran" can never read as "the judge agreed".
A failed request, a malformed answer or an answer from a model other than the one requested
exits 2 and writes no receipt; a missing answer is never read as 0.0.

The threshold and band are hand-set defaults. Before relying on them, run `--self-test --online`
(it plants a clause joining four behaviours and a scenario that restates it, and requires the
judge to hold them and pass a well-formed pair), and check the scores on clauses from your own
project whose right answer you already know.

## Receipts

An online run writes a receipt, `<change>/.bapu-gate.json` by default (`--receipt FILE` to
choose, `--no-receipt` to skip). It records every ask, the model that answered, the threshold,
the band and a SHA-256 digest over the path and bytes of every delta spec, taken from the bytes
that were judged, so an edit made while the run was in flight leaves the receipt stale.

`--check-receipt` is offline. It answers "is there a current PASS for these exact files?" by
re-deriving everything instead of trusting the receipt's verdict line: the digest, the
structure, one judged row per requirement and scenario in order, the answering model of both
asks, and every stored score against the threshold and band. Exit 0 means current; exit 1 names
why not. A continuous-integration job can run it without a key. What it cannot catch is a
receipt whose scores were fabricated and whose digest was recomputed to match.

## What the gate does not do

It judges the wording of a clause, not whether the clause is the right requirement, and not
whether any code implements it. Pair it with tests proven by `bapu-seedred`.
