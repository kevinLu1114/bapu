## What and why

<!-- One change per pull request. Link the issue it resolves: "Fixes #123". -->

## 任務與權限

<!-- 填寫任務／issue、基準 revision、工作 branch、交件對象、負責的範圍與不做的事、
可重現驗收。若涉及外部寫入、付費服務、發佈或部署，列出對應授權；
此 PR 本身不授予這些權限。 -->

## 可重現交件

<!-- 受驗證的程式 revision；實際指令、工作目錄、相關工具版本、退出碼；
原始 log／工件的位置及 revision 或 digest。未執行的檢查明確標示，不得填 PASS。
受驗證內容變更後，重跑受影響的檢查。規則見根目錄 CONTRIBUTING.md。 -->

## Evidence checklist

- [ ] Behaviour changes are stated as clauses: one behaviour per requirement, each with a
      scenario (WHEN / THEN); an OpenSpec delta, if any, passes `bapu-gate`.
- [ ] Every new or changed test has a row in `seedred.json`, and
      `bapu-seedred seedred.json --only <id>` reports RED for it.
- [ ] Review findings I am responding to, or raising, quote their evidence verbatim.
- [ ] `python -m pytest -q` passes, and `ruff check .` and `ruff format --check .` are clean.
- [ ] `CHANGELOG.md` is updated under `[Unreleased]` for user-visible changes.
- [ ] AI assistance, if any, is disclosed below.

## Coverage

<!-- The failure classes the tests cover (absent, empty, malformed, boundary, stale, partial
failure, ...) and the classes deliberately not covered, with the reason. -->

## AI assistance

<!-- None, or what was used and for which part. -->

## 尚未完成與交接

<!-- 選擇 ready_for_review 或 blocked；這是交件者的狀態，不是系統驗收結果。
列出未驗證範圍、已知限制、獨立 review 狀態；若阻塞，列出已嘗試的操作、缺少什麼，
以及接手者可直接執行的下一步。不要把秘密或無關的環境資訊放進證據。 -->
