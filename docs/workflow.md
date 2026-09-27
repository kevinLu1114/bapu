# The workflow

AI agents write specifications, code and review comments faster than anyone can check them.
The expensive step is no longer producing a change; it is deciding whether its claims hold.
This workflow puts a mechanical check at each hand-off, so every claim arrives with evidence
that someone else can re-run instead of having to trust.

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

是否採用 OpenSpec 依 [CONTRIBUTING.md](../CONTRIBUTING.md) 的貢獻規則；
本文件第 1、2 步只適用於選用 OpenSpec 的變更。若選用，先寫 delta 再寫程式碼。
每個 `### Requirement:` 描述一個 SHALL 或 MUST 行為；每個 `#### Scenario:`
描述測試可以建立的 WHEN 與觀察到的 THEN。未採用 OpenSpec 不代表免除行為與驗收說明。

The unit of review is the clause. A requirement that bundles three behaviours cannot be checked
as a whole: a test passes for one of them and the other two ride along unverified.

## 2. Clause gate

`bapu-gate openspec/changes/<change>` checks the structure offline: every scenario is made of
`- **GIVEN|WHEN|THEN|AND**` steps and nothing else, every requirement has a scenario, every
scenario has a WHEN and a THEN, and a new capability states its purpose. With `--online` and
`TYPESAFE_API_KEY` set, each clause is also scored for being one behaviour, observable from
outside, and free of implementation detail, and each scenario for being a concrete, testable
case. See [gate.md](gate.md).

**本步完成條件**：離線執行回報 STRUCTURE-OK，並保留原始輸出及受檢查內容的
revision 或 digest；離線模式不產生模型評分收據。若使用已授權的線上評分，
則須回報 PASS，並保留對應本次受檢查內容的評分收據。兩者都不代表實作已通過驗收。

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

交件保留適用的 gate 報告、seed-red 結果及 finding verdict，讓 reviewer 能重跑。
純文件修改、沒有測試變更或 review 沒有 finding 時，依各步的適用範圍標記
「不適用」並說明原因；不能製造空輸入來換取 PASS，也不能省略仍受變更影響的驗證。
若此次任務要求執行某一步，必須附該步的實際結果，不能自行改成不適用。

## Principles

- **A check that cannot fail proves nothing.** Every detector here ships with a known positive
  it must catch and a known negative it must pass (`--self-test`, and the tests).
- **Nothing to check is not a pass.** An empty table, a delta with no requirements and a
  findings file with no findings are errors, not green results.
- **Done is decided by an artifact, not by a report of it.** An agent saying the tests pass is
  not evidence; the runner's output is.
- **The judge ranks; it does not authorise.** Online scores decide what a person looks at first.
  They never replace a reproduction.
