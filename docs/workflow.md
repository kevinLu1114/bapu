# The workflow

AI agents write specifications, code and review comments faster than anyone can check them.
The expensive step is no longer producing a change; it is deciding whether its claims hold.
This workflow puts a mechanical check at each hand-off, so every claim arrives with evidence
that someone else can re-run instead of having to trust. The contribution contract that
surrounds it — who owns a change, how big it may be, how it is titled, and how it is handed
over — lives in [CONTRIBUTING.md](../CONTRIBUTING.md); the steps below are the verification entry
points those rules point at.

```
 +-------------------+
 | 1. spec           |  an OpenSpec change: one requirement per behaviour,
 |                   |  one scenario per testable case
 +---------+---------+
           |
           v
 +-------------------+   HOLD
 | 2. clause gate    | ---------> fix the clause, not the code
 |    bapu-gate      |
 +---------+---------+
           | STRUCTURE-OK (offline) or PASS (online)
           v
 +-------------------+
 | 3. implement      |  code, plus one test per scenario
 +---------+---------+
           |
           v
 +-------------------+   NOT-RED
 | 4. mutation-      | ---------> the test cannot fail: fix the test
 |    proven tests   |
 |    bapu-seedred   |
 +---------+---------+
           | every row RED
           v
 +-------------------+
 | 5. independent    |  a reviewer who did not write the change; each finding
 |    review         |  quotes the output it rests on, verbatim
 +---------+---------+
           |
           v
 +-------------------+   NEEDS-EVIDENCE --> back to the reviewer
 | 6. verify         |   REFUTED --------> drop the finding
 |    findings       |   ESCALATE -------> a stronger reviewer decides
 |    bapu-findings  |
 +---------+---------+
           | QUOTED / CONFIRMED: reproduce it, fix it, add a seed-red row for the fix
           v
 +-------------------+
 | 7. land           |  the gate report, the seed-red table and the verdicts
 |                   |  are the record of what was checked
 +-------------------+
```

## 1. Spec

Whether to use OpenSpec follows the contribution rules in [CONTRIBUTING.md](../CONTRIBUTING.md);
steps 1 and 2 here apply only to changes that opt into it. If you do, write the delta before the
code. Each `### Requirement:` states one SHALL or MUST behaviour, and each `#### Scenario:` a
WHEN a test can set up and a THEN it can observe. Not using OpenSpec does not excuse you from
stating the behaviour and its acceptance criteria.

The unit of review is the clause. A requirement that bundles three behaviours cannot be checked
as a whole: a test passes for one of them and the other two ride along unverified.

## 2. Clause gate

`bapu-gate openspec/changes/<change>` checks the structure offline: every scenario is made of
`- **GIVEN|WHEN|THEN|AND**` steps and nothing else, every requirement has a scenario, every
scenario has a WHEN and a THEN, and a new capability states its purpose. With `--online` and
`TYPESAFE_API_KEY` set, each clause is also scored for being one behaviour, observable from
outside, and free of implementation detail, and each scenario for being a concrete, testable
case. See [gate.md](gate.md).

**Done when** the offline run reports STRUCTURE-OK, and you keep its raw output together with
the revision or digest of the content that was checked; offline mode produces no model-score
receipt. If you use authorised online scoring, it must report PASS, and you keep the receipt
that matches the content you checked. Neither verdict means the implementation has passed
acceptance.

## 3. Implement

Write the code and one test per scenario. Each test asserts the observable outcome the
scenario names (an exit code, a message, a file's content), never merely "no exception".

## 4. Mutation-proven tests

For every test, write a seed-red row: the smallest change to the code that removes the
behaviour the test claims to guard, and the test that must catch it.
`bapu-seedred table.json` runs each test before the mutation (it must pass), with the mutation
(it must fail) and after the file is restored byte for byte (it must pass again). See
[seedred.md](seedred.md).

A mutation that stays green is a finding about the test, not about the code. Suspect the test
first: a guard that has never been seen to fail has not been shown to guard anything.

**Done means** every row is RED.

## 5. Independent review

The reviewer did not write the change. Each finding carries its claim, the commands the
reviewer ran and their output pasted verbatim, and the claim split into sub-claims: single
observations, each quoting the part of the evidence it rests on.

## 6. Verify the findings

`bapu-findings findings.json` checks offline that every quote appears verbatim in the evidence.
A finding that cites output it did not paste goes back to its author before anyone acts on it.
With `--online`, each sub-claim is also scored for whether the evidence shows it, and for
whether the evidence shows its opposite. See [evidence.md](evidence.md).

A CONFIRMED finding means the evidence says what the finding says. It does not mean the finding
is right: reproduce it before fixing, then add a seed-red row that proves the fix.

## 7. Land

A deliverable keeps the applicable gate report, seed-red results and finding verdicts, so a
reviewer can re-run them. For a documentation-only change, a change with no test change, or a
review that raised no finding, mark the inapplicable steps "not applicable" and give the reason;
never manufacture an empty input to buy a PASS, and never skip verification the change still
affects. If the task itself requires a step to be run, attach that step's actual result — you
cannot declare it not applicable. Hand the pull request over as `ready_for_review` or `blocked`,
as [CONTRIBUTING.md](../CONTRIBUTING.md) describes.

## Principles

- **A check that cannot fail proves nothing.** Every detector here ships with a known positive
  it must catch and a known negative it must pass (`--self-test`, and the tests).
- **Nothing to check is not a pass.** An empty table, a delta with no requirements and a
  findings file with no findings are errors, not green results.
- **Done is decided by an artifact, not by a report of it.** An agent saying the tests pass is
  not evidence; the runner's output is.
- **The judge ranks; it does not authorise.** Online scores decide what a person looks at first.
  They never replace a reproduction.
