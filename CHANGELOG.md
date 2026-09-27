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
- 在 CONTRIBUTING 與 PR template 定義 agent 與人共用的任務、權限、證據與交接契約；
  README 明確區分 Mac 整合的產品方向、現有 CLI 與尚未實作的能力。

### Fixed

- 長測試名稱的種紅案例隔離繼承的 CI 環境，避免 pytest 關閉摘要截斷後漏測欄寬行為。
- 文件釐清 OpenSpec 的適用範圍，以及離線 STRUCTURE-OK 不需要線上評分收據。

[Unreleased]: https://github.com/kevinLu1114/bapu/commits/main
