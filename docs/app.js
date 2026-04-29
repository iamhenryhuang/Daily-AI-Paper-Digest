const state = {
  entries: [],
  current: null,
  mode: "report",
};

const els = {
  dateSelect: document.querySelector("#dateSelect"),
  dateList: document.querySelector("#dateList"),
  content: document.querySelector("#content"),
  currentDate: document.querySelector("#currentDate"),
  statusText: document.querySelector("#statusText"),
  reportTab: document.querySelector("#reportTab"),
  sourcesTab: document.querySelector("#sourcesTab"),
};

init();

async function init() {
  bindEvents();
  try {
    const response = await fetch("manifest.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`manifest.json ${response.status}`);
    const manifest = await response.json();
    state.entries = [...manifest].sort((a, b) => b.date.localeCompare(a.date));
    if (!state.entries.length) {
      showEmpty("目前還沒有簡報。");
      return;
    }
    renderDates();
    await selectDate(state.entries[0].date);
  } catch (error) {
    showEmpty(`讀取 manifest.json 失敗：${error.message}`);
  }
}

function bindEvents() {
  els.dateSelect.addEventListener("change", () => selectDate(els.dateSelect.value));
  els.reportTab.addEventListener("click", () => switchMode("report"));
  els.sourcesTab.addEventListener("click", () => switchMode("sources"));
}

function renderDates() {
  els.dateSelect.innerHTML = "";
  els.dateList.innerHTML = "";

  for (const entry of state.entries) {
    const option = document.createElement("option");
    option.value = entry.date;
    option.textContent = entry.date;
    els.dateSelect.append(option);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "date-button";
    button.textContent = entry.date;
    button.dataset.date = entry.date;
    button.addEventListener("click", () => selectDate(entry.date));
    els.dateList.append(button);
  }
}

async function selectDate(date) {
  state.current = state.entries.find((entry) => entry.date === date);
  if (!state.current) return;

  els.dateSelect.value = date;
  for (const button of els.dateList.querySelectorAll(".date-button")) {
    button.classList.toggle("active", button.dataset.date === date);
  }
  els.currentDate.textContent = date;
  await loadCurrentDocument();
}

async function switchMode(mode) {
  if (state.mode === mode) return;
  state.mode = mode;
  els.reportTab.classList.toggle("active", mode === "report");
  els.sourcesTab.classList.toggle("active", mode === "sources");
  await loadCurrentDocument();
}

async function loadCurrentDocument() {
  if (!state.current) return;
  const path = state.mode === "report" ? state.current.report : state.current.sources;
  els.statusText.textContent = state.mode === "report" ? "正式簡報" : "評分來源";
  els.content.innerHTML = "<p class=\"empty\">讀取中...</p>";

  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`${path} ${response.status}`);
    const markdown = await response.text();
    els.content.innerHTML = renderMarkdown(markdown);
  } catch (error) {
    showEmpty(`讀取檔案失敗：${error.message}`);
  }
}

function showEmpty(message) {
  els.currentDate.textContent = "沒有資料";
  els.statusText.textContent = "";
  els.content.innerHTML = `<p class="empty">${escapeHtml(message)}</p>`;
}

function renderMarkdown(markdown) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listType = null;
  let inCode = false;
  let codeLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = null;
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];

    if (line.startsWith("```")) {
      if (inCode) {
        html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        inCode = false;
      } else {
        flushParagraph();
        closeList();
        inCode = true;
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      closeList();
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    if (isTableStart(lines, i)) {
      flushParagraph();
      closeList();
      const table = collectTable(lines, i);
      html.push(renderTable(table.rows));
      i = table.end;
      continue;
    }

    const unordered = line.match(/^\s*[-*]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const nextType = unordered ? "ul" : "ol";
      if (listType !== nextType) {
        closeList();
        html.push(`<${nextType}>`);
        listType = nextType;
      }
      html.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`);
      continue;
    }

    paragraph.push(line.trim());
  }

  flushParagraph();
  closeList();
  return html.join("\n");
}

function isTableStart(lines, index) {
  return lines[index]?.includes("|") && /^\s*\|?\s*:?-{3,}:?\s*\|/.test(lines[index + 1] || "");
}

function collectTable(lines, start) {
  const rows = [];
  let index = start;
  while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
    if (!/^\s*\|?\s*:?-{3,}:?\s*\|/.test(lines[index])) {
      rows.push(splitTableRow(lines[index]));
    }
    index += 1;
  }
  return { rows, end: index - 1 };
}

function splitTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderTable(rows) {
  if (!rows.length) return "";
  const [head, ...body] = rows;
  const header = `<thead><tr>${head.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("")}</tr></thead>`;
  const content = body
    .map((row) => `<tr>${row.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join("")}</tr>`)
    .join("");
  return `<table>${header}<tbody>${content}</tbody></table>`;
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function escapeHtml(value) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
