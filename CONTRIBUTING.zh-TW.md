# 貢獻 Bapu

謝謝你的協助。Bapu 存在的目的是檢查一個變更是否自帶證據，因此對 Bapu 的變更也受同一套規則
約束。Agent 與人使用同一份契約；誰交件，誰就對它負責，無論是自己寫的還是指揮工具寫的。

[English](CONTRIBUTING.md) | [繁體中文](CONTRIBUTING.zh-TW.md)

開始前，在 issue 或 pull request 說明任務是什麼、從哪個基準 revision 出發、你負責哪些範圍、你
刻意不做什麼，以及別人要如何重現你的驗收檢查。不要覆寫其他貢獻者尚未提交的工作。

外部寫入、付費服務、發佈與部署各自需要自己的授權；一個 pull request 不會授予這些權限。

交件須列出實際的指令、工具版本、退出碼，以及它們所對應的 revision。沒有執行的檢查是
NOT-RUN，不是 PASS。只有檢查不在變更範圍內時才可標 N/A，並附理由；必要檢查無法執行時，
變更仍是 blocked。受驗證的內容改變後，重跑受影響的檢查。遇到阻塞時，列出你試過什麼、
還缺什麼，以及別人可以直接執行的下一步。

公開證據不得包含金鑰、個人資料、私人路徑或無關的環境資訊。下面的指令是驗證的入口。

## 兩條路徑

**小型修正**——錯字、壞掉的連結、錯誤的訊息，或成因明顯的小 bug。不需要事先討論：直接開 pull
request，說明基準 revision、這個變更與它的證據，並且只包含這一個變更。

**需討論的新功能或行為變更**——新的行為、既有行為的改變、新的檢查，或工作流程的改變。先開
issue，在寫程式碼之前就條文達成共識：每個 requirement 一個行為（一個 SHALL 或 MUST，可從程式
外部觀察），並至少有一個 scenario，其 WHEN 是測試可以建立的、THEN 是測試可以觀察的。如果你也
把它寫成 OpenSpec delta，`bapu-gate` 必須回報 STRUCTURE-OK。如果你不寫成 delta，就在 issue 裡
陳述同樣的 requirement 與 scenario——重點是行為在程式碼之前先講定，而不是必須使用 OpenSpec。
OpenSpec 在這個 repository 是可選的。

兩條路徑都一樣：一個 owner、一個 branch、一個 pull request。

## 開發環境設定

Python 3.9 以上。

```
git clone https://github.com/kevinLu1114/bapu
cd bapu
python -m venv .venv
. .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## 執行檢查

```
python -m pytest -q                  # the test suite; offline, no key needed
ruff check . && ruff format --check .
bapu-gate --self-test                # each tool's planted known positives and negatives
bapu-findings --self-test
bapu-seedred seedred.json            # prove this repository's own tests (takes about a minute)
```

持續整合執行同樣的指令：`pytest` 矩陣 job、`lint` 與 `seed-red`。請對你交件的 revision 執行
它們，並連同輸出引用退出碼。

不是每一步都適用於每一個變更。純文件變更沒有可以寫成條文的行為，也沒有可以植入缺陷的測試：
把那些步驟標成不適用並說明原因。絕不要製造空表格或填充用的測試來讓某一步看起來是綠燈，也絕
不要跳過這個變更真正影響到的驗證。

測試套件從不連上網路：API 金鑰會被移除，而唯一開啟連線的函式在每個測試中都會被替換。需要
API 回答的測試使用假的回應。

## Commit message 與 pull request 標題

本專案遵循 [Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/)。標題
格式是 `<type>[optional scope][!]: <description>`，其中 type 是 `feat`、`fix`、`docs`、
`refactor`、`perf`、`test`、`build`、`ci`、`chore`、`style` 或 `revert` 之一，description 是
簡潔的英文祈使句；`!` 標記破壞性變更。

```
docs: define the small-fix and discussed-feature contribution tracks
fix(seedred): keep the restored file's timestamps
feat(gate): score a clause for stating one observable behaviour
refactor(jev): read the pinned model id from one constant
```

以上是本 repository 的寫法示例；你選的 type 與 scope 必須符合你的變更實際做的事。

Squash merge 應以 pull request 標題作為 commit 標題，所以把它當 commit message 寫，並在
請求 review 前先讓 `Validate PR title` job 接受它。維護者仍須另外設定 squash 訊息預設值
與必要狀態檢查；workflow 本身不會強制這兩項 repository 設定。一個 pull request 只包含一個
變更。不要改寫已公開的歷史：標題寫錯就改 pull request 標題，不要對 `main` 或別人的 branch
強制推送。

## 貢獻的證據規則

1. **超過小型修正的變更先開 issue**，並把你想要改變或新增的行為寫成條文：每個 requirement 一個
   行為，且至少有一個 scenario，其 WHEN 是測試可以建立的、THEN 是測試可以觀察的。如果你把它寫
   成 OpenSpec delta，`bapu-gate` 必須回報 STRUCTURE-OK。
2. **每個新增或修改的測試都由植入的缺陷證明。** 在 [`seedred.json`](seedred.json) 加一列，移除
   該測試守的行為，並顯示 `bapu-seedred seedred.json --only <id>` 回報 RED。如果某一列維持
   綠燈，代表這個測試並沒有守住它聲稱的東西；改測試，不要改那一列。
3. **Finding 引用它的證據。** 主張有缺陷的 review comment 要包含執行過的指令與它的輸出，逐字
   貼上，而每個主張要引用它所依據的那段輸出。`bapu-findings` 檢查的正是這件事，被判為
   NEEDS-EVIDENCE 的 finding 會退回給它的作者。
4. **分開陳述覆蓋範圍與它的缺口。** 在 pull request 列出你的測試涵蓋的失敗類別（缺漏、空值、
   格式錯誤、邊界、過期、部分失敗……）以及你刻意不涵蓋的類別和理由。
5. **揭露 AI 協助**，方式見下面〈AI 協助與問責〉一節。你仍然是它的作者。

## 上游重用與升級

Bapu 建立在其他專案之上，而不是重做它們，而一次升級就是一個普通的變更。當你採用某個上游——
或改用它的新版本——時，pull request 必須記錄：

- 被重用的精確上游版本或 commit；
- 在其上套用的本地修補或改寫，以及它們存在的原因；
- 針對那個釘住的組合執行過的驗證指令與它們的輸出。

這個 repository 裡沒有任何東西會自動選擇、排程或升級上游，而一個更新的上游版本不會只因為它
存在就被採用：被驗證過的是那個釘住的組合，除此之外不代表任何事。必要檢查若因缺少網路或金鑰
而無法執行，應標成 NOT-RUN，且變更維持 blocked，不可回報通過。

## AI 協助與問責

Bapu 接受人與 agent 的貢獻。請在 pull request 揭露 AI 協助，並指明對結果負責的貢獻者。
「模型寫的」不是解釋；誰交件，誰仍須對變更、證據與 review 負責。

以上是 Bapu 的政策，不是通則。其他專案自訂規則，有些限制或禁止 AI 協助的貢獻——[Astral 的 AI
政策](https://github.com/astral-sh/.github/blob/main/AI_POLICY.md)就是一個例子。當你對別處
貢獻時，以那個專案的政策為準，所以先讀它。

## 語言

英文是這個 repository 的正式語言：原始碼與註解、commit message、pull request 標題、issue 與
pull request 討論，以及公開的規範性文件。

貢獻者最先讀的兩份規範性文件——[README.md](README.md) 與本文件——有繁體中文對照版
[README.zh-TW.md](README.zh-TW.md) 與 [CONTRIBUTING.zh-TW.md](CONTRIBUTING.zh-TW.md)，讓中文
貢獻者能完整閱讀。對照版是翻譯，不是獨立來源：改了英文的規範性段落，就在同一個 pull request
裡一併翻譯，並以英文文字為準解決歧義。時間戳相同並不證明翻譯是最新的。

## Pull requests

- 一個 pull request 只包含一個變更，並且說明它為什麼需要，以及它做了什麼。
- 填寫 pull request 模板，包含交接狀態那一段：寫明 `ready_for_review` 或 `blocked`，若為
  `blocked`，列出你試過什麼、還缺什麼，以及下一步。
- 對使用者可見的變更，在 [CHANGELOG.md](CHANGELOG.md) 的 `[Unreleased]` 下更新。
- 每個工具的預設模式維持離線；只有在設定了 `TYPESAFE_API_KEY` 的線上模式下才會有網路存取。

## 回報 bug

使用 bug report 表單。一個離線可重現、且輸出逐字貼上的重現步驟，是通往修正最快的路。安全性
問題改走私下回報；見 [SECURITY.md](SECURITY.md)。每一位參與者都應遵守[行為準則](CODE_OF_CONDUCT.md)。
