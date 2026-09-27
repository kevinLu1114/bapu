# Contributing to Bapu

Thank you for helping. Bapu checks that changes carry their own evidence, and contributions to
it are held to the same rules.

Agent 與人使用相同的證據標準。開始前在 issue 或 PR 說明任務、基準 revision、
負責範圍、不做的事與可重現驗收；不要覆寫其他貢獻者尚未提交的工作。
外部寫入、付費服務、發布與部署須另有授權，PR 本身不授予這些權限。
交件須列出實際指令、工具版本、退出碼與對應 revision；未執行的檢查不得標成 PASS。
受驗證內容改變後重跑受影響的檢查。遇到阻塞，列明已嘗試的操作、缺少的條件與下一步。
公開證據不得包含金鑰、個人資料、私人路徑或無關的環境資訊。下面的指令是驗證入口。

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

The test suite never reaches the network: the API key is removed and the one function that
opens a connection is replaced for every test. Tests that need an answer from the API use a fake.

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
5. **Disclose AI assistance** in the pull request description when you used it.

## Pull requests

- Keep one change per pull request, and explain why it is needed as well as what it does.
- Fill in the checklist in the pull request template.
- Update [CHANGELOG.md](CHANGELOG.md) under `[Unreleased]` for user-visible changes.
- 程式碼與註解使用英文；面向貢獻者的新增或修改文件使用繁體中文。
- The default mode of every tool stays offline; network access only ever happens in online
  mode, with `TYPESAFE_API_KEY` set.

## Reporting bugs

Use the bug report form. A reproduction that runs offline, with its output pasted verbatim, is
the fastest way to a fix. Security issues go through private reporting instead; see
[SECURITY.md](SECURITY.md).
