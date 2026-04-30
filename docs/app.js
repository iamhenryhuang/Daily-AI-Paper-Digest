const state = {
  entries: [],
  current: null,
  mode: "report",
  markdown: "",
  query: "",
  activeTag: "",
  tags: [],
};

const els = {
  dateSelect: document.querySelector("#dateSelect"),
  dateList: document.querySelector("#dateList"),
  content: document.querySelector("#content"),
  currentDate: document.querySelector("#currentDate"),
  statusText: document.querySelector("#statusText"),
  reportTab: document.querySelector("#reportTab"),
  sourcesTab: document.querySelector("#sourcesTab"),
  searchInput: document.querySelector("#searchInput"),
  tagFilters: document.querySelector("#tagFilters"),
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
      showEmpty("目前沒有可讀取的論文資料。");
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
  els.searchInput.addEventListener("input", () => {
    state.query = els.searchInput.value.trim();
    renderCurrentDocument();
  });
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
  els.statusText.textContent = state.mode === "report" ? "讀取摘要" : "讀取來源";
  els.content.innerHTML = '<p class="empty">讀取中...</p>';

  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`${path} ${response.status}`);
    state.markdown = await response.text();
    state.tags = extractTags(state.markdown);
    if (state.activeTag && !state.tags.includes(state.activeTag)) {
      state.activeTag = "";
    }
    renderTagFilters();
    renderCurrentDocument();
  } catch (error) {
    state.markdown = "";
    state.tags = [];
    state.activeTag = "";
    renderTagFilters();
    showEmpty(`讀取文件失敗：${error.message}`);
  }
}

function renderTagFilters() {
  els.tagFilters.innerHTML = "";
  els.tagFilters.hidden = state.tags.length === 0;
  if (!state.tags.length) return;

  for (const tag of state.tags) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-filter";
    button.classList.toggle("active", state.activeTag === tag);
    button.textContent = tag;
    button.addEventListener("click", () => {
      state.activeTag = state.activeTag === tag ? "" : tag;
      renderTagFilters();
      renderCurrentDocument();
    });
    els.tagFilters.append(button);
  }
}

function renderCurrentDocument() {
  const result = filterMarkdown(state.markdown, state.query, state.activeTag);
  if (!result.markdown.trim()) {
    const label = [state.query && `「${escapeHtml(state.query)}」`, state.activeTag && `#${escapeHtml(state.activeTag)}`]
      .filter(Boolean)
      .join(" + ");
    els.content.innerHTML = `<p class="empty">沒有找到${label || "符合條件的"}相關內容。</p>`;
  } else {
    els.content.innerHTML = renderMarkdown(result.markdown, state.query);
  }

  const modeText = state.mode === "report" ? "摘要" : "來源";
  if (state.query || state.activeTag) {
    const filters = [state.query && `「${state.query}」`, state.activeTag && `#${state.activeTag}`].filter(Boolean).join(" + ");
    els.statusText.textContent = `${modeText}：${result.count} 筆符合 ${filters}`;
  } else {
    els.statusText.textContent = modeText;
  }
}

function extractTags(markdown) {
  const tags = new Set();
  const tagLine = /^\s*-\s*Tags:\s*(.+)$/gim;
  for (const match of markdown.matchAll(tagLine)) {
    addTags(tags, match[1]);
  }

  const rows = markdown.replace(/\r\n/g, "\n").split("\n");
  for (const row of rows) {
    if (!row.includes("|")) continue;
    const cells = splitTableRow(row);
    if (cells.length < 3 || cells[2].toLowerCase() === "tags" || /^:?-{3,}:?$/.test(cells[2])) continue;
    addTags(tags, cells[2]);
  }

  return [...tags].sort((a, b) => a.localeCompare(b));
}

function addTags(tags, raw) {
  for (const tag of raw.split(",")) {
    const normalized = tag.trim();
    if (normalized) tags.add(normalized);
  }
}

function filterMarkdown(markdown, query, activeTag = "") {
  if (!query && !activeTag) return { markdown, count: 0 };

  const normalizedQuery = query.toLowerCase();
  const normalizedTag = activeTag.toLowerCase();
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const matches = [];
  let count = 0;

  for (let i = 0; i < lines.length; i += 1) {
    if (isTableStart(lines, i)) {
      const tableLines = [lines[i], lines[i + 1]];
      i += 2;

      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        const rowText = lines[i].toLowerCase();
        if (matchesFilters(rowText, normalizedQuery, normalizedTag)) {
          tableLines.push(lines[i]);
          count += 1;
        }
        i += 1;
      }

      if (tableLines.length > 2) matches.push(tableLines.join("\n"));
      continue;
    }

    const block = [lines[i]];
    while (i + 1 < lines.length && !isSearchBoundary(lines[i + 1]) && !isTableStart(lines, i + 1)) {
      i += 1;
      block.push(lines[i]);
    }

    const text = block.join("\n");
    if (matchesFilters(text.toLowerCase(), normalizedQuery, normalizedTag)) {
      matches.push(text);
      count += 1;
    }
  }

  return {
    markdown: matches.join("\n\n"),
    count,
  };
}

function matchesFilters(text, normalizedQuery, normalizedTag) {
  const queryMatch = !normalizedQuery || text.includes(normalizedQuery);
  const tagMatch = !normalizedTag || ((text.includes("tags:") || text.includes("|")) && text.includes(normalizedTag));
  return queryMatch && tagMatch;
}

function isSearchBoundary(line) {
  return /^(#{1,3})\s+/.test(line) || /^\d+\.\s+\*\*/.test(line);
}

function showEmpty(message) {
  els.currentDate.textContent = "沒有資料";
  els.statusText.textContent = "";
  els.content.innerHTML = `<p class="empty">${escapeHtml(message)}</p>`;
}

function renderMarkdown(markdown, query = "") {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listType = null;
  let inCode = false;
  let codeLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${inlineMarkdown(paragraph.join(" "), query)}</p>`);
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
      html.push(`<h${level}>${inlineMarkdown(heading[2], query)}</h${level}>`);
      continue;
    }

    if (isTableStart(lines, i)) {
      flushParagraph();
      closeList();
      const table = collectTable(lines, i);
      html.push(renderTable(table.rows, query));
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
      html.push(`<li>${inlineMarkdown((unordered || ordered)[1], query)}</li>`);
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

function renderTable(rows, query) {
  if (!rows.length) return "";
  const [head, ...body] = rows;
  const header = `<thead><tr>${head.map((cell) => `<th>${inlineMarkdown(cell, query)}</th>`).join("")}</tr></thead>`;
  const content = body
    .map((row) => `<tr>${row.map((cell) => `<td>${inlineMarkdown(cell, query)}</td>`).join("")}</tr>`)
    .join("");
  return `<table>${header}<tbody>${content}</tbody></table>`;
}

function inlineMarkdown(value, query) {
  return highlightQuery(escapeHtml(value), query)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function highlightQuery(html, query) {
  if (!query) return html;
  const escapedQuery = escapeRegExp(escapeHtml(query));
  if (!escapedQuery) return html;
  return html.replace(new RegExp(`(${escapedQuery})`, "gi"), '<mark>$1</mark>');
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeHtml(value) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
