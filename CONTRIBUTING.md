# Contributing to Bapu

Thank you for helping. Bapu exists to check that a change carries its own evidence, and changes
to Bapu are held to the same rules. Agents and people work under one contract; whoever submits a
change is accountable for it, whether they typed it or directed a tool to.

[English](CONTRIBUTING.md) | [繁體中文](CONTRIBUTING.zh-TW.md)

Before you start, say in the issue or pull request what the task is, the base revision you work
from, the scope you own, what you are deliberately not doing, and how someone else can reproduce
your acceptance checks. Do not overwrite work another contributor has not submitted yet.

External writes, paid services, publishing and deployment each need their own authorisation; a
pull request does not grant it.

A deliverable states the exact commands, the tool versions, the exit codes and the revision they
ran against. A check you did not run is NOT-RUN, not PASS. Use N/A only when the check is outside
the change's scope, with a reason; an unavailable required check leaves the change blocked.
Re-run affected checks after verified content changes. When blocked, list what you tried,
what is missing, and the next step someone else can run.

Public evidence must not contain keys, personal data, private paths or unrelated environment
information. The commands below are the entry point for verification.

## Two tracks

**Small fix** — a typo, a broken link, a wrong message, a narrow bug whose cause is obvious. No
prior discussion is needed: open the pull request, state the base revision, the change and its
evidence, and keep it to that one change.

**Discussed feature or behaviour change** — a new behaviour, a change to an existing one, a new
check, or a change to the workflow. Open an issue first and agree on the clause before writing
code: one behaviour per requirement (one SHALL or MUST, observable from outside the code), with
at least one scenario whose WHEN a test can set up and whose THEN a test can observe. If you also
write it as an OpenSpec delta, `bapu-gate` must report STRUCTURE-OK on it. If you do not, state
the same requirement and scenario in the issue — the point is that the behaviour is agreed
before the code, not that OpenSpec is used. OpenSpec is optional in this repository.

Both tracks: one owner, one branch, one pull request.

## Development setup

Python 3.9 or newer.

```
git clone https://github.com/kevinLu1114/bapu
cd bapu
python -m venv .venv
. .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Running the checks

```
python -m pytest -q                  # the test suite; offline, no key needed
ruff check . && ruff format --check .
bapu-gate --self-test                # each tool's planted known positives and negatives
bapu-findings --self-test
bapu-seedred seedred.json            # prove this repository's own tests (takes about a minute)
```

Continuous integration runs the same commands: the `pytest` matrix job, `lint` and `seed-red`.
Run them against the revision you are submitting, and quote the exit codes with the output.

Not every step applies to every change. A documentation-only change has no behaviour to state as
a clause and no test to plant a defect in: mark those steps not applicable and say why. Never
fabricate an empty table or a filler test to make a step look green, and never skip a step the
change really does affect.

The test suite never reaches the network: the API key is removed and the one function that
opens a connection is replaced for every test. Tests that need an answer from the API use a fake.

## Commit messages and pull request titles

The project follows [Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/).
A subject is `<type>[optional scope][!]: <description>`, where the type is one of `feat`, `fix`,
`docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `style` or `revert`, and the
description is a concise imperative English phrase; `!` marks a breaking change.

```
docs: define the small-fix and discussed-feature contribution tracks
fix(seedred): keep the restored file's timestamps
feat(gate): score a clause for stating one observable behaviour
refactor(jev): read the pinned model id from one constant
```

For example, that is how this repository writes them; the type and scope you choose must match
what your change actually does.

For squash merges, use the pull request title as the commit subject, so write it as a commit
message and let the `Validate PR title` job accept it before you ask for review. Maintainers must
configure the squash-message default and required status check separately; the workflow alone
does not enforce either repository setting. Keep the pull request to one change. Do not rewrite
published history: correct a wrong subject by editing the pull request title, not by
force-pushing `main` or someone else's branch.

## Evidence rules for contributions

1. **Open an issue first** for anything beyond a small fix, and describe the behaviour you want
   to change or add as a clause: one behaviour per requirement, with at least one scenario whose
   WHEN a test can set up and whose THEN a test can observe. If you write it as an OpenSpec
   delta, `bapu-gate` must report STRUCTURE-OK on it.
2. **Every new or changed test is proven by a planted defect.** Add a row to
   [`seedred.json`](seedred.json) that removes the behaviour the test guards, and show that
   `bapu-seedred seedred.json --only <id>` reports RED. If a row stays green, the test does not
   guard what it claims; fix the test, not the row.
3. **Findings quote their evidence.** A review comment that claims a defect includes the command
   that was run and its output, verbatim, and each claim quotes the part of the output it rests
   on. `bapu-findings` checks exactly this, and a finding it returns as NEEDS-EVIDENCE goes back
   to its author.
4. **State coverage and its gaps separately.** In the pull request, list the failure classes
   your tests cover (absent, empty, malformed, boundary, stale, partial failure, ...) and the
   ones you deliberately left out, with the reason.
5. **Disclose AI assistance** in the pull request, as described under
   [AI assistance and accountability](#ai-assistance-and-accountability). You remain its author.

## Upstream reuse and upgrades

Bapu is built on other projects instead of reimplementing them, and an upgrade is a change like
any other. When you adopt an upstream — or move to a newer version of one — the pull request
must record:

- the exact upstream version or commit that was reused;
- the local patches or adaptations applied on top of it, and why they exist;
- the verification commands and their output, run against that pinned combination.

Nothing in this repository selects, schedules or upgrades an upstream automatically, and a newer
upstream version is not adopted merely because it exists: the pinned combination is what was
verified, and nothing else is implied. Where a required check cannot run without network access
or a key, mark it NOT-RUN and the change blocked rather than reporting a pass.

## AI assistance and accountability

Bapu allows human and agent contributions. Disclose AI assistance in the pull request and name
the contributor accountable for the result. "The model wrote it" is not an explanation; whoever
submits remains responsible for the change, its evidence and its review.

That is Bapu's policy, not a general rule. Other projects set their own terms, and some restrict
or forbid AI-assisted contributions — [Astral's AI policy](https://github.com/astral-sh/.github/blob/main/AI_POLICY.md)
is one example. When you contribute elsewhere, that project's policy governs, so read it first.

## Language

English is the canonical language of this repository: source code and comments, commit messages,
pull request titles, issues and pull request discussion, and the public normative documents.

The two normative documents that contributors read first — [README.md](README.md) and this file —
have Traditional Chinese counterparts, [README.zh-TW.md](README.zh-TW.md) and
[CONTRIBUTING.zh-TW.md](CONTRIBUTING.zh-TW.md), so that Chinese-speaking contributors can read
them in full. The counterparts are translations, not independent sources: change an English
normative section and translate it in the same pull request, and treat the English text as
resolving any ambiguity. A matching timestamp proves nothing about whether a translation is
current.

## Pull requests

- Keep one change per pull request, and explain why it is needed as well as what it does.
- Fill in the pull request template, including the hand-off line: state `ready_for_review` or
  `blocked`, and for `blocked` list what you tried, what is missing and the next step.
- Update [CHANGELOG.md](CHANGELOG.md) under `[Unreleased]` for user-visible changes.
- The default mode of every tool stays offline; network access only ever happens in online
  mode, with `TYPESAFE_API_KEY` set.

## Reporting bugs

Use the bug report form. A reproduction that runs offline, with its output pasted verbatim, is
the fastest way to a fix. Security issues go through private reporting instead; see
[SECURITY.md](SECURITY.md). Everyone taking part is expected to follow the
[code of conduct](CODE_OF_CONDUCT.md).
