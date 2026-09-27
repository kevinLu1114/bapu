# Case study: incoai/splash issue #122

This page shows the evidence-first shape of a contribution to an open-source project, using
only what is public on the issue and on the pull request that fixed it.

## What happened

- On 2026-09-23, issue [#122](https://github.com/incoai/splash/issues/122), "Responses:
  missing previous_response_id prevents stale-history fallback", was opened.
- The issue carried an exact reproduction on a pinned upstream commit.
- It proposed a change: keep HTTP 404 and `invalid_request_error`, and return the code
  `previous_response_not_found` from the parent lookup.
- It included before-and-after results of three focused HTTP regressions: two expected failures
  before the change, three passes after it.
- It was filed issue-first, as the project's CONTRIBUTING.md asks, and disclosed that AI
  assistance was used.
- The maintainer fixed it in pull request [#155](https://github.com/incoai/splash/pull/155),
  "Report a missing previous response as previous_response_not_found", which says
  "Fixes #122". The pull request was merged on 2026-09-25.

The fix came from the maintainer. The issue contributed the reproduction, the proposed
behaviour and the regression evidence.

## How it maps onto the workflow

| Stage | What the public record shows |
|---|---|
| Spec | One behaviour, as proposed: keep HTTP 404 and `invalid_request_error`, and return the code `previous_response_not_found` from the parent lookup. |
| Reproduction | An exact reproduction on a pinned upstream commit, so it can be re-run against the same code. |
| Tests proven by failure | Three focused regressions: two failed before the change, as expected, and all three passed after it. A test that has been seen to fail against the defect is the same evidence a seed-red row records. |
| Process | Filed issue-first, per the project's CONTRIBUTING.md, with AI assistance disclosed. |
| Land | The maintainer's pull request #155, which says "Fixes #122", merged on 2026-09-25. |

## Why this shape matters to maintainers

An AI-assisted issue or pull request costs a maintainer time in proportion to how much of it
they have to take on trust. When a report states one behaviour, pins the code it was run
against, and shows its regressions failing before the change and passing after, the maintainer
can verify it by re-running it, and can keep, change or replace the proposed fix on their own
terms.
