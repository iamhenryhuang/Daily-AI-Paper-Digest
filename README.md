# Daily AI Paper Agent

每天早上自動採集 AI 論文候選池，使用多訊號規則引擎篩選，再呼叫 Gemini 生成繁體中文論文解讀。

## 資料採集

預設採集 arXiv 6 個 AI 核心分類的新論文：

- `cs.AI`：Artificial Intelligence
- `cs.CL`：Computation and Language / NLP
- `cs.LG`：Machine Learning
- `cs.CV`：Computer Vision
- `cs.MA`：Multiagent Systems
- `cs.IR`：Information Retrieval

同時會抓取 Hugging Face Daily Papers，用於識別社群推薦與社群熱度。

## 篩選邏輯

每篇候選論文會進入規則引擎，綜合以下訊號打分：

| 訊號 | 目前實作 |
| --- | --- |
| 機構背景 | 在標題、摘要、comment、journal ref 中匹配 Google、OpenAI、Meta、清華、Stanford 等 40+ 頂級機構名稱。注意：arXiv metadata 通常不含作者 affiliation，所以這是保守啟發式。 |
| 社群推薦 | 被 Hugging Face Daily Papers 收錄則加分。 |
| 社群熱度 | Hugging Face votes 按 1、20、50、100 四檔加分。 |
| 頂會收錄 | 在 comment / journal ref / 摘要中匹配 ICLR、NeurIPS、ICML、ACL、CVPR 等頂會名稱。 |
| 程式碼可用 | metadata 中出現 GitHub、source code、open source 等線索則加分。 |

目前評分只使用上面 5 類訊號。arXiv 分類只用來建立候選池，不額外加分。

輸出分兩層：

- `重點關注`：預設最多 5 篇，達到較高門檻後由 Gemini 解讀。
- `也值得關注`：預設最多 12 篇，只列標題、連結和入選理由。

每期都會生成透明來源頁：`sources/YYYY-MM-DD.md`。你可以看到所有候選論文、分數、進入或被篩掉的理由。

## 解讀原則

Gemini 只解讀已經被規則引擎選出的 `重點關注` 論文，prompt 會約束它遵循下面原則：

- 先講問題，再講方案
- 從業者視角，說明這和工程、產品、研究落地有什麼關係
- 保持克制，不把所有內容都寫成「突破」
- 不編造 benchmark、結果、機構、程式碼連結或會議接收資訊

每篇解讀包含固定欄位：

- intro
- motivation
- solution
- benchmark
- result

## 本機執行

需要 Python 3.11+，不需要安裝第三方套件。

你可以複製 `.env.example` 成 `.env`，再填入自己的 key：

```powershell
Copy-Item .env.example .env
```

`.env` 不會被 commit，因為 `.gitignore` 已經排除它。

```powershell
$env:GEMINI_API_KEY="你的 Gemini API key"
python scripts/daily_papers.py
```

可選參數：

```powershell
python scripts/daily_papers.py --date 2026-04-29 --focus-count 5 --also-count 12 --lookback-days 3
```

## GitHub Actions 設定

1. 把這個資料夾推到 GitHub repo。
2. 到 repo 的 `Settings` -> `Secrets and variables` -> `Actions`。
3. 新增 secret：

```text
GEMINI_API_KEY=你的 Gemini API key
```

workflow 會每天 UTC 23:00 執行，也就是台北時間早上 7:00。執行後會把新的 `reports/*.md` 和 `sources/*.md` commit 回 repo。

## 為什麼 GitHub Actions 用 env，不用 .env？

`.env` 適合本機開發，但不應該 commit 到 GitHub，因為裡面通常會有 API key。GitHub Actions 的正確做法是把金鑰放在 GitHub Secrets，然後在 workflow 裡用 `env` 把 secret 注入成執行時環境變數：

```yaml
env:
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

這裡的 `env` 不是 repo 裡的 `.env` 檔，而是 Actions runner 當下的環境變數。腳本只需要讀環境變數，所以本機可以用 `.env` 或 shell 環境變數，GitHub Actions 則用 Secrets 注入。

## 調整篩選範圍

可以用環境變數覆蓋 arXiv 分類：

```powershell
$env:ARXIV_CATEGORIES="cs.AI,cs.CL,cs.LG,cs.CV,cs.MA,cs.IR"
python scripts/daily_papers.py
```

也可以直接調整 `.github/workflows/daily-papers.yml` 裡的 `env`。
