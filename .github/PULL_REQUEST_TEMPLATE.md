<!--
  One change per pull request. Small and docs-only changes stay light: fill the sections that
  apply and mark the rest N/A with a short reason. Keep the headings so reviewers can find each
  answer.

  The pull request title becomes the squash commit subject once merged, so it follows
  Conventional Commits — `type(scope)!: imperative description`, with an optional scope and `!`
  for a breaking change. The `Validate PR title` check enforces the type, the optional scope and
  the `!`; nothing about the correctness of the change. The full contract is in CONTRIBUTING.md.

  Never put secrets, tokens, personal data, private paths, or unrelated environment details in
  this description or in the linked evidence.
-->

## What and why

<!-- Link the issue this resolves: "Fixes #123". Explain why the change
is needed, not only what it does. -->

## Task and authorization

<!-- The task or issue, the base revision, the working branch, the intended recipient, the scope
you own, and the non-goals — what this pull request deliberately does not do. If the change needs
an external write, a paid service, a release, or a deployment, list the separate authorization it
requires; this pull request does not grant it. -->

## Reproducible evidence

<!-- The verified revision; the exact commands, working directory, relevant tool versions, and
exit codes; where the raw log or artifact lives, with its revision or digest. A check you did not
run is stated explicitly, never as PASS. Re-run the affected checks after the verified content
changes. Rules: CONTRIBUTING.md. -->

## Evidence checklist

<!-- Mark an item N/A with a reason when it does not apply — a docs-only change has no test rows,
for example. -->

- [ ] Behaviour changes are stated as clauses: one behaviour per requirement, each with a
      scenario (WHEN / THEN); an OpenSpec delta, if any, passes `bapu-gate`.
- [ ] Every new or changed test has a row in `seedred.json`, and
      `bapu-seedred seedred.json --only <id>` reports RED for it.
- [ ] Review findings I am responding to, or raising, quote their evidence verbatim.
- [ ] `python -m pytest -q` passes, and `ruff check .` and `ruff format --check .` are clean.
- [ ] `CHANGELOG.md` is updated under `[Unreleased]` for user-visible changes.
- [ ] No secret, token, personal datum, private path, or unrelated environment detail appears in
      this description or in the linked evidence.

## Coverage

<!-- The failure classes the tests cover (absent, empty, malformed, boundary, stale, partial
failure, ...) and the classes deliberately left out, each with the reason for the gap. -->

## Author, AI assistance, and review

- **Author** (accountable for this change): <!-- A human or agent name or handle. This is who
  answers for the evidence above, and the author stays accountable whether or not AI wrote it. -->
- **AI assistance**: <!-- None, or which tool was used and for which part. Disclosed agents are
  welcome; an undisclosed or unattributable change is not. -->
- **Independent review**: <!-- Who reviewed this change (human or model), what they reviewed, and
  what remains unreviewed. "Not yet reviewed" is a fine answer; leaving it unstated is not. -->

## Handoff

<!-- Choose one: ready_for_review or blocked. This is the submitter's state, not a verification
result. List the unverified scope, the known limitations, and the review status above. If blocked,
list what you tried, what is missing, and the next concrete step a taker can run. -->
