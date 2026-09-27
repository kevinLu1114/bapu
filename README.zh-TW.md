# Bapu

**在既有上游之上，整合 Mac 上從 agent 到推論的開發路徑。**

*If it can't fail, it didn't pass.*

[English](README.md) | [繁體中文](README.zh-TW.md)

本文件是 [README.md](README.md) 的繁體中文對照版；規範性內容以英文原文為準，兩者一起更新。

[![tests](https://github.com/kevinLu1114/bapu/actions/workflows/tests.yml/badge.svg)](https://github.com/kevinLu1114/bapu/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python: 3.9 to 3.13](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)

Bapu 的長期方向是減少 Mac 開發環境中 agent、工具與推論服務之間的手動整合工作，而不是重做上游
產品。日常流程預設由 OMP 承接，整合契約保持 harness-neutral，因此替換其中一個元件不必改寫整個
工作流程。

這些是產品方向，不是今天已交付的完整平台：跨 harness adapters、推論服務部署、排程與自動升級都
尚未實作，沒有任何東西會自行路由或自行升級。重用上游——或改用上游的新版本——是一個刻意且經過
驗證的步驟：釘住精確的上游版本、記錄本地修補，並在那個釘住的組合上重跑驗證，然後才依賴它。

目前的 `0.1.0` 提供三個可獨立使用的驗證 CLI：

| Tool | What it checks |
|---|---|
| `bapu-gate` | 在寫任何程式碼之前，逐條檢查 OpenSpec delta spec |
| `bapu-seedred` | 檢查每一個測試：植入它守的缺陷，並要求它轉紅 |
| `bapu-findings` | 檢查每一條 review finding：要求它的主張逐字引用證據 |

三者都離線執行，支援 Python 3.9 以上，沒有相依套件。`bapu-gate` 與 `bapu-findings` 另有可選的
線上模式，向判斷模型要評分。

## Why

AI agent 寫程式、spec 與 review comment 的速度超過人能檢查的速度，瓶頸因此轉移：不再是產出一個
變更，而是驗證隨它而來的主張。Bapu 針對三種能通過一眼掃過的問題形態：

- **一個不可能失敗的綠燈測試**：它應該守的缺陷可以被植入，而測試仍然綠燈；
- **一條包住多個行為的 spec 條文**：沒有單一測試、也沒有任何 reviewer 能照它寫的樣子檢查它；
- **一條主張不被自身證據支持的 review finding**：引用的輸出從未被貼上，或說的是別的事。

每個工具把其中一種變成機械檢查，附帶已知的正例與已知的負例，所以「它通過了」才有意義。

對開源維護者而言，同一個想法從另一側成立：一個 AI 協助產出的 issue 或 pull request 應該自帶可
重現的證據，讓維護者能驗證它，而不是信任它。
[docs/case-study-splash-122.md](docs/case-study-splash-122.md) 走過一個公開的例子。

## Install

Bapu 由原始碼安裝：它尚未發佈到 PyPI，下列指令是取得 `0.1.0` 的支援方式。

```
git clone https://github.com/kevinLu1114/bapu
cd bapu
pip install -e ".[dev]"
```

`bapu-seedred` 用 pytest 執行你的測試，所以 pytest 必須安裝在它使用的那個直譯器裡（`--python`，
預設是執行 Bapu 的那一個）。

## Quickstart (offline)

下列指令使用 [`examples/`](examples/) 裡的檔案，不需要金鑰，也不需要網路。

**在寫程式碼之前檢查 spec。**

```
$ bapu-gate examples/openspec/changes/add-overwrite-guard
POPULATION target=add-overwrite-guard deltas=1 requirements=2 scenarios=2 model=offline files_sha256=8e9514bae04f
verdict: STRUCTURE-OK

$ bapu-gate examples/openspec/changes/draft-audit-log
...
  hold: structure: specs/audit-log/spec.md: scenario 'Exports are audited' has no THEN step
  hold: structure: specs/audit-log/spec.md: requirement 'Audit entries are readable' has no scenario
  hold: structure: specs/audit-log/spec.md: new capability 'audit-log' has no '## Purpose' section
verdict: HOLD
```

**證明每個測試都能失敗。**

```
$ bapu-seedred examples/seedred/table.json --root examples/seedred
[cap] RED       before=passed after=failed restored=passed  tests/test_retry.py::test_delays_never_exceed_the_cap
[doubling] RED       before=passed after=failed restored=passed  tests/test_retry.py::test_delays_double_each_attempt
[negative] RED       before=passed after=failed restored=passed  tests/test_retry.py::test_negative_attempts_are_refused

3/3 mutations went red

$ bapu-seedred examples/seedred/table-weak.json --root examples/seedred
[cap-with-the-wrong-test] NOT-RED   before=passed after=passed restored=passed  tests/test_retry.py::test_delays_double_each_attempt
      the mutation survived: the test still passes with the defect planted
...
0/1 mutations went red
```

每一個被改動的檔案都會逐位元組還原，包含時間戳。

**檢查 review finding 是否引用它的證據。**

```
$ bapu-findings examples/findings.json
id  verdict         p_sup  why
F1  QUOTED              -  every sub-claim quotes the evidence verbatim
F2  NEEDS-EVIDENCE      -  quote not found verbatim in the evidence: sub-claim(s) [0]
F3  NEEDS-EVIDENCE      -  sub-claim(s) [0] quote nothing from the evidence

2 NEEDS-EVIDENCE, 1 QUOTED
```

每個工具在全部檢查通過時退出碼為 0，有東西需要注意時為 1，無法檢查時為 2（用法或輸入錯誤，或
一次沒有產生結果的執行）。每個工具都有 `--json`；`bapu-gate` 與 `bapu-findings` 有
`--self-test`，`bapu-seedred` 有 `--check`，可以在不執行表格的情況下驗證它。沒有 console
script 時，執行 `python -m bapu gate|seedred|findings`。

## Optional online mode

`bapu-gate --online` 與 `bapu-findings --online` 向 TypeSafe 的 System One 模型 Jev 要有限度的
判斷：一條條文是否只陳述一個可觀察的行為、一個 scenario 是否可測、證據是否顯示每個 sub-claim。
只有在同時傳入 `--online` **且** 設定了 `TYPESAFE_API_KEY` 環境變數時才會使用線上模式；否則什麼
都不會送出。

```
export TYPESAFE_API_KEY=...        # your own key
bapu-gate --self-test --online     # known-good and known-bad clauses, judged live
bapu-gate openspec/changes/my-change --online
bapu-gate openspec/changes/my-change --check-receipt   # offline, for CI
```

分數用來排序人應該先看什麼。它們本身從不授權任何事。送了什麼、答案怎麼用，見
[docs/online-mode.md](docs/online-mode.md)。

## How the pieces fit

```
spec --> bapu-gate --> implement --> bapu-seedred --> independent review --> bapu-findings --> land
          HOLD:                       NOT-RED:                                NEEDS-EVIDENCE:
          fix the clause              fix the test                            back to the reviewer
```

這個 repository 把工具用在自己身上：[`seedred.json`](seedred.json) 在 `src/bapu/` 植入缺陷，
每個缺陷搭配一個必須抓到它的測試，而持續整合要求每一個都讓它的測試轉紅。

## Documentation

- [docs/workflow.md](docs/workflow.md)：工作流程，逐步說明
- [docs/gate.md](docs/gate.md)：`bapu-gate` 的規則、問題、門檻與收據
- [docs/seedred.md](docs/seedred.md)：`bapu-seedred` 的表格、判定與安全
- [docs/evidence.md](docs/evidence.md)：`bapu-findings` 的輸入、判定與限制
- [docs/online-mode.md](docs/online-mode.md)：可選的線上模式
- [docs/case-study-splash-122.md](docs/case-study-splash-122.md)：一個公開、證據先行的 issue

## Contributing

歡迎貢獻，而貢獻遵循工具所檢查的同一套證據規則。見 [CONTRIBUTING.md](CONTRIBUTING.md)
（[繁體中文](CONTRIBUTING.zh-TW.md)）。安全性問題請依 [SECURITY.md](SECURITY.md) 私下回報。
每一位參與者都應遵守[行為準則](CODE_OF_CONDUCT.md)。

## License

[MIT](LICENSE)
