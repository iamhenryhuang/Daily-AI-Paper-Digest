const FAVORITES_KEY = "paper-digest-favorites-v1";
const TONES = ["terra", "blue", "sage", "plum", "mustard", "teal"];
const CATEGORY_TONE = { "cs.CV": 0, "cs.CL": 1, "cs.LG": 2, "cs.AI": 3, "cs.MA": 4, "cs.IR": 5 };
const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const SECTIONS = [
  { key: "intro", label: "背景導讀", en: "Intro" },
  { key: "motivation", label: "研究動機", en: "Motivation" },
  { key: "method", label: "方法", en: "Method" },
  { key: "result", label: "實驗結果", en: "Result" },
  { key: "conclusion", label: "結論", en: "Conclusion" },
  { key: "research_gap", label: "研究缺口", en: "Research Gap" },
];
const SECTION_HEADING = {
  Intro: "intro",
  Motivation: "motivation",
  Method: "method",
  Result: "result",
  Conclusion: "conclusion",
  "Research Gap": "research_gap",
};

const state = {
  entries: [],
  favorites: loadFavorites(),
  query: "",
  docs: new Map(), // path -> Promise<string>
  reports: new Map(), // date -> parsed report
  cleanup: null,
};

const app = document.querySelector("#app");
const progress = document.querySelector("#progress");

init();

async function init() {
  window.addEventListener("hashchange", route);
  document.addEventListener("keydown", onKeydown);
  bindTopbar();
  try {
    const response = await fetch("manifest.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`manifest.json ${response.status}`);
    const manifest = await response.json();
    state.entries = [...manifest].sort((a, b) => b.date.localeCompare(a.date));
  } catch (error) {
    app.innerHTML = `<p class="empty">讀取 manifest.json 失敗：${esc(error.message)}</p>`;
    return;
  }
  updateSavedCount();
  route();
}

/* ───────── Routing ───────── */

function route() {
  state.cleanup?.();
  state.cleanup = null;
  progress.style.opacity = "0";

  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  setNav(navKey(parts));

  if (!state.entries.length) {
    app.innerHTML = '<p class="empty">目前沒有可讀取的論文資料。</p>';
    return;
  }
  if (parts[0] === "saved") return renderSaved();
  if (parts[0] === "archive") return renderHome({ toArchive: true, focusSearch: parts[1] === "search" });
  if (parts[0] === "d" && parts[1]) {
    const entry = state.entries.find((item) => item.date === parts[1]);
    if (!entry) return renderNotFound();
    if (parts[2] === "sources") return renderSources(entry);
    if (parts[2]) return renderArticle(entry, parts[2]);
    return renderIssue(entry);
  }
  renderHome();
}

function navKey(parts) {
  if (parts[0] === "saved" || parts[0] === "archive") return parts[0];
  if (parts[0] === "d") return parts[1] === state.entries[0]?.date ? "latest" : "archive";
  return "latest";
}

function setNav(active) {
  for (const key of ["latest", "archive", "saved"]) {
    document.querySelector(`#nav${key[0].toUpperCase()}${key.slice(1)}`).classList.toggle("active", key === active);
  }
}

function bindTopbar() {
  const topbar = document.querySelector("#topbar");
  const onScroll = () => topbar.classList.toggle("scrolled", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // Already on #/archive/search: the hash won't change, so re-run the route to refocus the field.
  document.querySelector("#searchBtn").addEventListener("click", (event) => {
    if (location.hash === "#/archive/search") {
      event.preventDefault();
      route();
    }
  });
}

function show(html, title) {
  app.innerHTML = html;
  document.title = title ? `${title} · Paper Digest` : "Paper Digest · 每日 AI 論文簡報";
  window.scrollTo({ top: 0, behavior: "instant" });
}

function renderNotFound() {
  show('<p class="empty">找不到這一期。<a href="#/">回到封面</a></p>', "找不到頁面");
}

function onKeydown(event) {
  if (event.target.closest("input, textarea") || event.metaKey || event.ctrlKey || event.altKey) return;
  const selector = { ArrowLeft: "[data-nav=prev]", ArrowRight: "[data-nav=next]" }[event.key];
  const target = selector && document.querySelector(selector);
  if (target) location.hash = target.getAttribute("href");
}

/* ───────── Home / cover ───────── */

async function renderHome({ toArchive = false, focusSearch = false } = {}) {
  const latest = state.entries[0];
  const total = state.entries.reduce((sum, entry) => sum + (entry.focus?.length || 0), 0);
  state.openMonths ??= new Set([latest.date.slice(0, 7)]);

  const tone = issueTone(latest.date);

  show(`
    <section class="hero tone-${tone}" data-day="${esc(latest.date.slice(8))}">
      <div>
        <span class="eyebrow">Issue No.${state.entries.length} · ${esc(formatDate(latest.date))}</span>
        <h1>Paper<br><em>Digest</em></h1>
        <p class="hero-lede">每天一份 AI 論文簡報。先看標題大綱，再讀全文解讀與研究缺口。已累積 ${state.entries.length} 期、${total} 篇重點論文。</p>
        <a class="btn" href="#/d/${esc(latest.date)}">閱讀本期 →</a>
      </div>
      <ol class="hero-outline">
        ${(latest.focus || [])
          .map((paper) => `<li><a href="${paperHref(latest.date, paper)}"><span>${esc(paper.title)}</span></a></li>`)
          .join("")}
      </ol>
    </section>

    <div class="section-head" id="archiveHead">
      <div>
        <span class="eyebrow">Archive</span>
        <h2>往期封面</h2>
      </div>
      <label class="search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="search" type="search" placeholder="搜尋標題、分類或 arXiv ID" value="${esc(state.query)}" aria-label="搜尋論文">
      </label>
    </div>
    <div id="archive"></div>
  `);

  const input = document.querySelector("#search");
  input.addEventListener("input", () => {
    state.query = input.value.trim();
    renderArchive(latest.date);
  });
  renderArchive(latest.date);

  if (toArchive) document.querySelector("#archiveHead").scrollIntoView();
  if (focusSearch) input.focus({ preventScroll: true });
}

function renderArchive(latestDate) {
  const container = document.querySelector("#archive");
  if (!container) return;

  if (state.query) {
    const hits = searchPapers(state.query);
    container.innerHTML = hits.length
      ? `<div class="rows">${hits.slice(0, 80).map((hit) => paperRow(hit.entry.date, hit.paper, hit.kind)).join("")}</div>`
      : `<p class="empty">沒有找到「${esc(state.query)}」相關論文。</p>`;
    bindFavorites(container);
    return;
  }

  const months = new Map();
  for (const entry of state.entries) {
    const key = entry.date.slice(0, 7);
    if (!months.has(key)) months.set(key, []);
    months.get(key).push(entry);
  }

  container.innerHTML = [...months]
    .map(([key, list]) => {
      const papers = list.reduce((sum, entry) => sum + (entry.focus?.length || 0), 0);
      const cards = list
        .map(
          (entry) => `
        <a class="issue-card tone-${issueTone(entry.date)}${entry.date === latestDate ? " latest" : ""}" href="#/d/${esc(entry.date)}">
          <div class="day"><strong>${esc(entry.date.slice(8))}</strong><span>${esc(MONTHS[Number(entry.date.slice(5, 7)) - 1])} · ${esc(weekday(entry.date))}</span></div>
          <ol>${(entry.focus || []).slice(0, 3).map((paper) => `<li>${esc(paper.title)}</li>`).join("")}</ol>
          <div class="meta"><span>${entry.focus?.length || 0} 重點 · ${entry.also?.length || 0} 延伸</span><span>閱讀 →</span></div>
        </a>`,
        )
        .join("");
      return `<details class="month" data-month="${key}"${state.openMonths.has(key) ? " open" : ""}>
        <summary>
          <span class="month-name"><b>${esc(MONTHS[Number(key.slice(5)) - 1])}</b> ${esc(key.slice(0, 4))}</span>
          <span class="month-meta">${list.length} 期 · ${papers} 篇重點</span>
        </summary>
        <div class="issue-grid">${cards}</div>
      </details>`;
    })
    .join("");

  for (const details of container.querySelectorAll("details.month")) {
    details.addEventListener("toggle", () => {
      if (details.open) state.openMonths.add(details.dataset.month);
      else state.openMonths.delete(details.dataset.month);
    });
  }
}

function searchPapers(query) {
  const needle = query.toLowerCase();
  const hits = [];
  for (const entry of state.entries) {
    for (const [kind, list] of [["focus", entry.focus || []], ["also", entry.also || []]]) {
      for (const paper of list) {
        const haystack = `${paper.title} ${paper.id || ""} ${(paper.categories || []).join(" ")}`.toLowerCase();
        if (haystack.includes(needle)) hits.push({ entry, paper, kind });
      }
    }
  }
  return hits;
}

function paperRow(date, paper, kind) {
  const href = kind === "focus" ? paperHref(date, paper) : arxivUrl(paper.id);
  const external = kind === "focus" ? "" : ' target="_blank" rel="noopener noreferrer"';
  return `
    <div class="row tone-${paperTone(paper)}">
      <div class="row-date">${esc(date)}<br>${kind === "focus" ? "重點關注" : "也值得關注"}</div>
      <div>
        <a class="row-title" href="${href}"${external}>${esc(paper.title)}</a>
        <div class="chips">${(paper.categories || []).map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>
      </div>
      ${favoriteButton({ id: paper.id, title: paper.title, date })}
    </div>`;
}

/* ───────── Issue (outline) ───────── */

async function renderIssue(entry) {
  show('<p class="loading">載入中…</p>');
  const report = await loadReport(entry).catch((error) => error);
  if (report instanceof Error) {
    app.innerHTML = `<p class="empty">讀取失敗：${esc(report.message)}</p>`;
    return;
  }

  const tone = issueTone(entry.date);
  const prev = neighbor(entry.date, 1);
  const next = neighbor(entry.date, -1);

  show(
    `
    <section class="issue-head tone-${tone}" data-day="${esc(entry.date.slice(8))}">
      <span class="eyebrow">Issue No.${state.entries.length - state.entries.indexOf(entry)} · ${esc(formatDate(entry.date))}</span>
      <h1>${esc(entry.date)}</h1>
      <p>${report.focus.length} 篇重點論文附全文解讀，另有 ${report.also.length} 篇延伸推薦。模型：${esc(report.meta.model || "—")}。</p>
      ${issueTabs(entry.date, "outline")}
    </section>

    <ol class="outline">
      ${report.focus
        .map(
          (paper, index) => `
        <li class="tone-${paperTone(paper)}">
          <span class="num">${String(index + 1).padStart(2, "0")}</span>
          <div>
            <h3><a href="${paperHref(entry.date, paper)}">${esc(paper.title)}</a></h3>
            <p class="hook">${esc(firstSentence(paper.sections.intro))}</p>
            <div class="chips">
              <span class="chip solid">Score ${paper.score}</span>
              ${paper.categories.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}
            </div>
          </div>
          ${favoriteButton({ id: paper.id, title: paper.title, date: entry.date })}
        </li>`,
        )
        .join("")}
    </ol>

    ${
      report.also.length
        ? `<div class="section-head"><div><span class="eyebrow">Also Worth Watching</span><h2>也值得關注</h2></div></div>
      <div class="also-list">
        ${report.also
          .map(
            (paper) => `
          <div class="also-card tone-${paperTone(paper)}">
            <a href="${arxivUrl(paper.id)}" target="_blank" rel="noopener noreferrer">${esc(paper.title)} ↗</a>
            <div class="chips"><span class="chip solid">Score ${paper.score}</span>${paper.categories.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>
            <small>${esc(llmReason(paper.reasons) || paper.reasons)}</small>
            ${favoriteButton({ id: paper.id, title: paper.title, date: entry.date })}
          </div>`,
          )
          .join("")}
      </div>`
        : ""
    }

    <nav class="pager" aria-label="前後期">
      ${prev ? `<a data-nav="prev" href="#/d/${esc(prev.date)}"><small>← 上一期</small><span>${esc(prev.date)}</span></a>` : "<span></span>"}
      ${next ? `<a data-nav="next" class="next" href="#/d/${esc(next.date)}"><small>下一期 →</small><span>${esc(next.date)}</span></a>` : ""}
    </nav>`,
    entry.date,
  );
  bindFavorites(app);
}

function issueTabs(date, active) {
  return `<div class="tabs" role="tablist">
    <a href="#/d/${esc(date)}" class="${active === "outline" ? "active" : ""}">大綱</a>
    <a href="#/d/${esc(date)}/sources" class="${active === "sources" ? "active" : ""}">來源</a>
  </div>`;
}

/* ───────── Article ───────── */

async function renderArticle(entry, paperId) {
  show('<p class="loading">載入中…</p>');
  const report = await loadReport(entry).catch((error) => error);
  if (report instanceof Error) {
    app.innerHTML = `<p class="empty">讀取失敗：${esc(report.message)}</p>`;
    return;
  }
  const index = report.focus.findIndex((paper) => paper.id === paperId);
  if (index < 0) return renderNotFound();

  const paper = report.focus[index];
  const prev = report.focus[index - 1];
  const next = report.focus[index + 1];
  const { signals, llm } = parseReasons(paper.reasons);
  const tone = paperTone(paper);

  const sections = SECTIONS.map((section, i) => {
    const text = paper.sections[section.key];
    if (!text) return "";
    const heading = `<h2><span>${String(i + 1).padStart(2, "0")}</span>${section.label}<em>${section.en}</em></h2>`;
    if (section.key === "research_gap") return `<section id="s-${section.key}" class="callout">${heading}<p>${esc(text)}</p></section>`;
    return `<section id="s-${section.key}">${heading}<p${section.key === "intro" ? ' class="lede"' : ""}>${esc(text)}</p></section>`;
  }).join("");

  show(
    `
    <div class="tone-${tone}">
      <nav class="crumbs" aria-label="路徑">
        <a href="#/">封面</a> / <a href="#/d/${esc(entry.date)}">${esc(entry.date)}</a> / <span>第 ${index + 1} 篇</span>
      </nav>

      <header class="article-cover" data-num="${String(index + 1).padStart(2, "0")}">
        <div class="chips">
          <span class="chip">Score ${paper.score}</span>
          ${paper.categories.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}
        </div>
        <h1>${esc(paper.title)}</h1>
        <div class="cover-foot">
          <div class="cover-meta">
            <span>發表 ${esc(paper.published)}</span>
            <a href="${arxivUrl(paper.id)}" target="_blank" rel="noopener noreferrer">arXiv:${esc(paper.arxiv)} ↗</a>
          </div>
          <div class="cover-actions">${favoriteButton({ id: paper.id, title: paper.title, date: entry.date })}</div>
        </div>
      </header>

      <div class="article-wrap">
        <aside class="toc" aria-label="文章目錄">
          <span class="eyebrow">目錄</span>
          ${SECTIONS.map((s) => `<button type="button" data-target="s-${s.key}">${s.label} <small>${s.en}</small></button>`).join("")}
        </aside>

        <article class="prose">
          ${
            signals.length || llm
              ? `<div class="why">
              <span class="eyebrow">為什麼選這篇</span>
              <div class="chips">${signals.map((s) => `<span class="chip"><b>+${s.points}</b>${esc(s.text)}</span>`).join("")}${llm ? `<span class="chip solid">LLM #${llm.rank} · ${llm.score}/10</span>` : ""}</div>
              ${llm?.reason ? `<blockquote>${esc(llm.reason)}</blockquote>` : ""}
            </div>`
              : ""
          }
          ${sections}
          <nav class="pager" aria-label="前後篇">
            ${prev ? `<a data-nav="prev" href="${paperHref(entry.date, prev)}"><small>← 上一篇</small><span>${esc(prev.title)}</span></a>` : "<span></span>"}
            ${next ? `<a data-nav="next" class="next" href="${paperHref(entry.date, next)}"><small>下一篇 →</small><span>${esc(next.title)}</span></a>` : ""}
          </nav>
        </article>
      </div>
    </div>`,
    paper.title,
  );

  bindFavorites(app);
  bindReading(tone);
}

function bindReading(tone) {
  const toc = [...document.querySelectorAll(".toc button")];
  const targets = toc.map((button) => document.getElementById(button.dataset.target)).filter(Boolean);
  for (const button of toc) {
    button.addEventListener("click", () => document.getElementById(button.dataset.target)?.scrollIntoView({ behavior: "smooth" }));
  }

  const observer = new IntersectionObserver(
    (items) => {
      for (const item of items) {
        if (!item.isIntersecting) continue;
        for (const button of toc) button.classList.toggle("on", button.dataset.target === item.target.id);
      }
    },
    { rootMargin: "-20% 0px -70% 0px" },
  );
  targets.forEach((target) => observer.observe(target));
  toc[0]?.classList.add("on");

  progress.className = `progress tone-${tone}`;
  const onScroll = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    progress.style.opacity = "1";
    progress.style.transform = `scaleX(${max > 0 ? Math.min(1, scrollY / max) : 0})`;
  };
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  state.cleanup = () => {
    observer.disconnect();
    removeEventListener("scroll", onScroll);
  };
}

/* ───────── Sources ───────── */

async function renderSources(entry) {
  show('<p class="loading">載入中…</p>');
  const md = await fetchDoc(entry.sources).catch((error) => error);
  if (md instanceof Error) {
    app.innerHTML = `<p class="empty">讀取失敗：${esc(md.message)}</p>`;
    return;
  }
  const rows = parseSources(md);
  const candidates = md.match(/arXiv 候選論文數：(\d+)/)?.[1];
  const hf = md.match(/命中 Hugging Face Daily Papers：(\d+)/)?.[1];
  const tone = issueTone(entry.date);

  show(
    `
    <section class="issue-head tone-${tone}" data-day="${esc(entry.date.slice(8))}">
      <span class="eyebrow">Transparency · ${esc(formatDate(entry.date))}</span>
      <h1>來源與評分</h1>
      <p>規則引擎檢查了 ${esc(candidates || "—")} 篇 arXiv 候選論文，其中 ${esc(hf || "—")} 篇出現在 Hugging Face Daily Papers。以下是有得分的論文與理由。</p>
      ${issueTabs(entry.date, "sources")}
    </section>
    <div class="sources-bar">
      <p id="sourceCount">${rows.length} 篇</p>
      <label class="search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="sourceFilter" type="search" placeholder="篩選標題或分類" aria-label="篩選來源">
      </label>
    </div>
    <div id="sourceRows" class="rows"></div>`,
    `${entry.date} 來源`,
  );

  const list = document.querySelector("#sourceRows");
  const count = document.querySelector("#sourceCount");
  const paint = (query) => {
    const needle = query.toLowerCase();
    const shown = rows.filter((row) => !needle || `${row.title} ${row.categories} ${row.id}`.toLowerCase().includes(needle));
    count.textContent = `${shown.length} 篇`;
    list.innerHTML = shown.length
      ? shown
          .map(
            (row) => `
        <div class="row tone-${paperTone({ categories: row.categories.split(",").map((c) => c.trim()) })}">
          <span class="score">${row.score}</span>
          <div>
            <a class="row-title" href="${esc(row.url)}" target="_blank" rel="noopener noreferrer">${esc(row.title)} ↗</a>
            <div class="chips">${row.categories.split(",").map((c) => `<span class="chip">${esc(c.trim())}</span>`).join("")}<span class="chip plain">${esc(row.published)}</span></div>
            <details><summary>評分理由</summary><p>${esc(row.reasons)}</p></details>
          </div>
          ${favoriteButton({ id: row.id, title: row.title, date: entry.date })}
        </div>`,
          )
          .join("")
      : '<p class="empty">沒有符合的論文。</p>';
    bindFavorites(list);
  };
  document.querySelector("#sourceFilter").addEventListener("input", (event) => paint(event.target.value.trim()));
  paint("");
}

function parseSources(md) {
  const rows = [];
  for (const line of md.replace(/\r\n/g, "\n").split("\n")) {
    if (!line.startsWith("|") || /^\|\s*-/.test(line) || line.includes("| 分數 |")) continue;
    const cells = line.replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, "|"));
    if (cells.length < 5) continue;
    const link = cells[1].match(/^\[(.+)\]\((.+)\)$/);
    rows.push({
      score: cells[0],
      title: link ? link[1] : cells[1],
      url: link ? link[2] : "",
      id: baseId(link?.[2] || ""),
      published: cells[2],
      categories: cells[3],
      reasons: cells[4],
    });
  }
  return rows;
}

/* ───────── Saved ───────── */

function renderSaved() {
  const items = Object.values(state.favorites).sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  show(
    `
    <div class="section-head">
      <div><span class="eyebrow">Saved</span><h2>我的收藏</h2></div>
      <span class="eyebrow">${items.length} 篇</span>
    </div>
    ${
      items.length
        ? `<div class="rows">${items
            .map((item) => {
              const entry = state.entries.find((e) => e.date === item.date);
              const focus = entry?.focus?.some((p) => p.id === item.id);
              return paperRow(item.date || "", { id: item.id, title: item.title, categories: [] }, focus ? "focus" : "also");
            })
            .join("")}</div>`
        : '<p class="empty">還沒有收藏。在任何一篇論文旁點書籤圖示就能加入。</p>'
    }`,
    "我的收藏",
  );
  bindFavorites(app);
}

/* ───────── Report parsing ───────── */

function loadReport(entry) {
  if (state.reports.has(entry.date)) return Promise.resolve(state.reports.get(entry.date));
  return fetchDoc(entry.report).then((md) => {
    const parsed = parseReport(md);
    state.reports.set(entry.date, parsed);
    return parsed;
  });
}

function fetchDoc(path) {
  if (!state.docs.has(path)) {
    const request = fetch(path, { cache: "no-cache" }).then((response) => {
      if (!response.ok) throw new Error(`${path} ${response.status}`);
      return response.text();
    });
    request.catch(() => state.docs.delete(path));
    state.docs.set(path, request);
  }
  return state.docs.get(path);
}

function parseReport(md) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const meta = { model: (md.match(/摘要模型：OpenAI `([^`]+)`/) || [])[1] || "" };
  const focus = [];
  const also = [];
  let section = "";
  let paper = null;
  let field = "";

  for (const line of lines) {
    if (line.startsWith("## ")) {
      section = line.slice(3).trim();
      paper = null;
      continue;
    }
    const focusHead = line.match(/^###\s+\d+\.\s+(.+)$/);
    const alsoHead = line.match(/^\d+\.\s+\*\*(.+)\*\*\s*$/);
    if (section === "重點關注" && focusHead) {
      paper = newPaper(focusHead[1].trim());
      focus.push(paper);
      field = "";
      continue;
    }
    if (section === "也值得關注" && alsoHead) {
      paper = newPaper(alsoHead[1].trim());
      also.push(paper);
      field = "";
      continue;
    }
    if (!paper) continue;

    const bullet = line.match(/^\s*-\s*(分數|arXiv|發表日期|分類|入選理由)\s*[：:]\s*(.*)$/);
    if (bullet) {
      const [, key, value] = bullet;
      if (key === "分數") paper.score = Number(value) || 0;
      else if (key === "arXiv") {
        paper.arxiv = (value.match(/\[([^\]]+)\]/) || [, value])[1].trim();
        paper.id = baseId(paper.arxiv);
      } else if (key === "發表日期") paper.published = value.trim();
      else if (key === "分類") paper.categories = value.split(",").map((c) => c.trim()).filter(Boolean);
      else paper.reasons = value.trim();
      continue;
    }

    const labelled = line.match(/^\*\*(Intro|Motivation|Method|Result|Conclusion|Research Gap):\*\*\s*(.*)$/);
    if (labelled) {
      field = SECTION_HEADING[labelled[1]];
      paper.sections[field] = labelled[2].trim();
    } else if (field && line.trim()) {
      paper.sections[field] += ` ${line.trim()}`;
    }
  }
  return { meta, focus, also };
}

function newPaper(title) {
  return { title, score: 0, arxiv: "", id: "", published: "", categories: [], reasons: "", sections: {} };
}

function parseReasons(reasons) {
  const llmMatch = reasons.match(/LLM rank #(\d+)(?: \/ (\d+)\/10)?(?::\s*([\s\S]*))?$/);
  const rest = llmMatch ? reasons.slice(0, llmMatch.index) : reasons;
  const signals = rest
    .split(/;\s*/)
    .map((part) => part.trim().match(/^\+(\d+)\s+(.+)$/))
    .filter(Boolean)
    .map((m) => ({ points: Number(m[1]), text: m[2] }));
  const llm = llmMatch ? { rank: llmMatch[1], score: llmMatch[2] || "—", reason: (llmMatch[3] || "").trim() } : null;
  return { signals, llm };
}

function llmReason(reasons) {
  return parseReasons(reasons).llm?.reason || "";
}

/* ───────── Favorites ───────── */

function favoriteButton(paper) {
  if (!paper.id) return "";
  const on = Boolean(state.favorites[paper.id]);
  const label = on ? "取消收藏" : "收藏論文";
  const attrs = `data-id="${esc(paper.id)}" data-title="${esc(paper.title)}" data-date="${esc(paper.date || "")}"`;
  const path = "M1 1.5A.5.5 0 0 1 1.5 1h9a.5.5 0 0 1 .5.5v11.29a.5.5 0 0 1-.8.4L6 10.12l-4.2 3.07A.5.5 0 0 1 1 12.79V1.5z";
  return `<button type="button" class="fav" ${attrs} aria-pressed="${on}" title="${label}" aria-label="${label}">
    <svg viewBox="0 0 12 14" fill="${on ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>
  </button>`;
}

function bindFavorites(root) {
  for (const button of root.querySelectorAll(".fav")) {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const { id, title, date } = button.dataset;
      if (state.favorites[id]) delete state.favorites[id];
      else state.favorites[id] = { id, title, url: arxivUrl(id), date };
      saveFavorites();
      updateSavedCount();
      const on = Boolean(state.favorites[id]);
      for (const same of document.querySelectorAll(`.fav[data-id="${CSS.escape(id)}"]`)) {
        same.setAttribute("aria-pressed", String(on));
        same.title = on ? "取消收藏" : "收藏論文";
        same.setAttribute("aria-label", same.title);
        same.querySelector("svg").setAttribute("fill", on ? "currentColor" : "none");
      }
      if (location.hash.startsWith("#/saved") && !on) renderSaved();
    });
  }
}

function updateSavedCount() {
  const badge = document.querySelector("#savedCount");
  const count = Object.keys(state.favorites).length;
  badge.hidden = count === 0;
  badge.textContent = String(count);
}

function loadFavorites() {
  try {
    return JSON.parse(localStorage.getItem(FAVORITES_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveFavorites() {
  try {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(state.favorites));
  } catch {
    // Keep the in-memory favorite state for the current page even if storage is blocked.
  }
}

/* ───────── Helpers ───────── */

function paperHref(date, paper) {
  return `#/d/${encodeURIComponent(date)}/${encodeURIComponent(paper.id)}`;
}

function arxivUrl(id) {
  return `https://arxiv.org/abs/${id}`;
}

function baseId(value) {
  const match = String(value).match(/(\d{4}\.\d{4,5})(?:v\d+)?/);
  return match ? match[1] : "";
}

function hash(value) {
  let h = 0;
  for (const char of String(value)) h = (h * 31 + char.charCodeAt(0)) >>> 0;
  return h;
}

function issueTone(date) {
  return TONES[hash(date) % TONES.length];
}

function paperTone(paper) {
  const category = paper.categories?.[0] || "";
  return TONES[category in CATEGORY_TONE ? CATEGORY_TONE[category] : hash(category) % TONES.length];
}

function neighbor(date, offset) {
  const index = state.entries.findIndex((entry) => entry.date === date);
  return state.entries[index + offset];
}

function formatDate(date) {
  const [y, m, d] = date.split("-").map(Number);
  return `${y}.${String(m).padStart(2, "0")}.${String(d).padStart(2, "0")} ${weekday(date)}`;
}

function weekday(date) {
  return ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"][new Date(`${date}T00:00:00Z`).getUTCDay()];
}

function firstSentence(text = "") {
  const match = text.match(/^.+?[。！？]/);
  return match ? match[0] : text;
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
