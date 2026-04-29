# Daily AI Paper Digest

每天早上自動抓 AI 論文，篩出幾篇值得看的，整理成繁體中文簡報。

資料來源：

- arXiv：`cs.AI`, `cs.CL`, `cs.LG`, `cs.CV`, `cs.MA`, `cs.IR`
- Hugging Face Daily Papers

輸出：

- `docs/reports/YYYY-MM-DD.md`：正式簡報
- `docs/sources/YYYY-MM-DD.md`：候選論文、分數、入選理由
- `docs/index.html`：GitHub Pages 靜態閱讀器

## 篩選規則

目前只看 5 個訊號：

- 機構背景：Google、OpenAI、Meta、清華、Stanford 等
- Hugging Face Daily Papers 收錄
- Hugging Face 票數熱度
- 頂會線索：ICLR、NeurIPS、ICML、ACL、CVPR 等
- 程式碼可用線索：GitHub、source code、open source 等

預設輸出：

- `重點關注`：最多 5 篇，會用 OpenAI 解讀
- `也值得關注`：最多 3 篇，只列連結和入選理由

同分時會隨機排序再取上限；同一天重跑會保持同一個結果。

解讀欄位：

- intro
- motivation
- method
- result
- conclusion
- research_gap

## 本機執行

需要 Python 3.11+，不需要安裝套件。

```powershell
Copy-Item .env.example .env
```

把 `.env` 裡的 key 換成自己的：

```text
OPENAI_API_KEY=你的 OpenAI API key
```

執行：

```powershell
python scripts/daily_papers.py
```

常用參數：

```powershell
python scripts/daily_papers.py --focus-count 5 --also-count 3 --lookback-days 3
```

## GitHub Actions

到 GitHub repo 設定 secret：

```text
OPENAI_API_KEY=你的 OpenAI API key
```

可選 Discord 通知：

```text
DISCORD_WEBHOOK_URL=你的 Discord webhook URL
```

workflow 會每天台北時間早上 7:00 執行。跑完後會把 `docs/reports/`、`docs/sources/` 和 `docs/manifest.json` commit 回 repo。

也可以手動跑：

1. 到 repo 的 `Actions`
2. 選 `Daily AI Paper Digest`
3. 按 `Run workflow`

## GitHub Pages

這個 repo 可以直接發成靜態網站。

設定方式：

1. 到 repo 的 `Settings`
2. 進入 `Pages`
3. Source 選 `Deploy from a branch`
4. Branch 選 `main`
5. Folder 選 `/docs`
6. 儲存

之後網站會在：

```text
https://你的帳號.github.io/Daily-AI-Paper-Digest/
```

首頁會讀 `manifest.json`，再載入對應日期的 `reports/` 或 `sources/`。

## Discord 通知

如果設定了 `DISCORD_WEBHOOK_URL`，Action 跑完會推送：

- 本期重點關注論文標題
- 正式簡報連結
- sources 評分頁連結
- Action 執行紀錄連結

Discord webhook 建立位置：

```text
Discord channel -> Edit Channel -> Integrations -> Webhooks
```

## 費用

預設每天最多呼叫 OpenAI 5 次，每篇重點論文 1 次。`也值得關注` 和 `sources` 不會呼叫模型。

以 `gpt-4o` 粗估，通常是每天幾美分、每月約幾美元。實際金額以 OpenAI 後台帳單為準。

## 調整

arXiv 分類可在 `.env` 或 workflow 裡改：

```text
ARXIV_CATEGORIES=cs.AI,cs.CL,cs.LG,cs.CV,cs.MA,cs.IR
```

模型可改：

```text
OPENAI_MODEL=gpt-4o
```
