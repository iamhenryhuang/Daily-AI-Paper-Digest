# Daily AI Paper Digest

每天早上自動整理 AI 論文，篩出值得看的幾篇，輸出成繁體中文簡報。

## 資料來源

- arXiv：`cs.AI`, `cs.CL`, `cs.LG`, `cs.CV`, `cs.MA`, `cs.IR`
- Hugging Face Daily Papers

## 怎麼選論文

每篇候選論文會依 5 個訊號打分：

- 機構背景：Google、OpenAI、Meta、清華、Stanford 等
- 社群推薦：是否被 Hugging Face Daily Papers 收錄
- 社群熱度：Hugging Face 票數，分 4 檔加分
- 頂會線索：ICLR、NeurIPS、ICML、ACL、CVPR 等
- 程式碼可用：GitHub、source code、open source 等線索

輸出分兩層：

- `重點關注`：最多 5 篇，會下載 PDF 並用 OpenAI 做全文解讀
- `也值得關注`：最多 3 篇，只列連結和入選理由

同分時會隨機排序再取上限；同一天重跑會保持同一組結果。

## 論文解讀欄位

每篇重點論文會整理：

- intro
- motivation
- method
- result
- conclusion
- research_gap

## 工作流

每天台北時間早上 7:00，GitHub Actions 會自動執行：

1. 抓 arXiv 和 Hugging Face Daily Papers
2. 對候選論文打分
3. 選出重點關注和也值得關注
4. 下載重點論文 PDF、抽取全文並呼叫 OpenAI 分析
5. 產生 Markdown 結果
6. 更新靜態閱讀器的 manifest
7. commit 回 repo

輸出檔案：

- `docs/reports/YYYY-MM-DD.md`
- `docs/sources/YYYY-MM-DD.md`
- `docs/manifest.json`

## 使用

需要設定 GitHub secret：

```text
OPENAI_API_KEY=你的 OpenAI API key
```

本機測試可以複製 `.env.example`：

```powershell
Copy-Item .env.example .env
python scripts/daily_papers.py
```

常用參數：

```powershell
python scripts/daily_papers.py --focus-count 5 --also-count 3 --lookback-days 3
```

## 調整

可在 `.env` 或 workflow 裡調整：

```text
OPENAI_MODEL=gpt-4.1-mini
ARXIV_CATEGORIES=cs.AI,cs.CL,cs.LG,cs.CV,cs.MA,cs.IR
```

預設模型是 `gpt-4.1-mini`。每天最多呼叫 OpenAI 5 次，每篇重點論文 1 次；`也值得關注` 和 `sources` 不會呼叫模型，也不會下載 PDF。PDF 抽取文字會快取在 `.cache/papers`。
