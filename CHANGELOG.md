# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `bapu-gate`: an offline structure check for OpenSpec delta specs (scenario steps, scenarios
  per requirement, WHEN and THEN per scenario, a purpose for new capabilities, exact headings),
  an optional online mode that scores each clause with Jev and holds on the lower of two
  wordings, and receipts that `--check-receipt` re-derives offline.
- `bapu-seedred`: a runner that plants the defect each test guards and requires the test to pass
  before, fail with the mutation and pass after a byte-for-byte restore.
- `bapu-findings`: an offline check that every sub-claim of a review finding quotes its evidence
  verbatim, and an optional online mode that scores support and separates contradicted from
  merely unsupported sub-claims.
- A minimal client for TypeSafe's System One API, used only in online mode.
- `--self-test` for each tool, with planted known positives and known negatives.
- Documentation of the workflow, each tool, the online mode, and a public case study.
- A seed-red table that proves this repository's own tests.
- A shared contribution contract for humans and agents, covering task scope, authorization,
  evidence, and handoff. The README distinguishes delivered CLIs from the future Mac integration.
- English-first contribution guidance with synchronized Traditional Chinese README and
  contribution guides, Conventional Commit conventions, and semantic pull request title checks.

### Fixed

- Seed-red coverage for long test names isolates inherited CI settings so pytest's untruncated
  summaries do not bypass the output-width regression.
- Documentation clarifies when OpenSpec applies and why offline STRUCTURE-OK needs no online receipt.

[Unreleased]: https://github.com/kevinLu1114/bapu/commits/main
