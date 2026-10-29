// Minimal MVP page: threads, streaming hook cards, branches, depth, composer.
// Plain JS on purpose (see docs/P0_SPEC.md §3); the real frontend comes in P1.

const $ = (sel) => document.querySelector(sel);
const els = {
  threads: $("#threads"),
  title: $("#thread-title"),
  depth: $("#depth"),
  messages: $("#messages"),
  empty: $("#empty"),
  composer: $("#composer"),
  input: $("#input"),
  send: $("#send"),
  newThread: $("#new-thread"),
  surprise: $("#surprise"),
  stop: $("#stop"),
  banner: $("#banner"),
  spend: $("#spend"),
  concepts: $("#concepts"),
  panel: $("#panel"),
  layout: $(".layout"),
  menu: $("#menu"),
  notes: $("#notes"),
  scrim: $("#scrim"),
  conceptOptions: $("#concept-options"),
};

const state = {
  threadId: null,
  streaming: false,
  lastTurn: null, // last turn request body, for Retry
  lang: "both", // set from localStorage at startup
  abort: null, // AbortController of the running turn
  panelConceptId: null, // concept shown in the right panel
  threadTitles: {}, // thread id -> title, for "cards about this concept"
};

// --- API -------------------------------------------------------------------

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "content-type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) signIn();
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(typeof detail.detail === "string" ? detail.detail : `HTTP ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

// APP_PASSWORD is set and this device has no session (or the password changed).
function signIn() {
  location.href = "/login";
}

// POST a turn and call onEvent(name, data) for each server-sent event.
async function streamTurn(threadId, body, onEvent, signal) {
  const res = await fetch(`/api/threads/${threadId}/turns`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (res.status === 401) signIn();
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    onEvent("error", { code: "http", message: typeof detail.detail === "string" ? detail.detail : `HTTP ${res.status}` });
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let name = "message";
      let data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      onEvent(name, JSON.parse(data));
    }
  }
}

// --- rendering helpers -----------------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue; // e.g. disabled: false
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return node;
}

// Like node.append, but skips null/false children (for `cond && el(...)`).
function append(node, ...children) {
  node.append(...children.flat().filter((c) => c != null && c !== false));
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Tiny Markdown subset (paragraphs, bullet lists, headings, bold, italic, code).
// Input is escaped first, so model output can never inject HTML.
function inlineMd(s) {
  return escapeHtml(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
}

function renderMd(md) {
  const blocks = [];
  let para = [];
  const flushPara = () => {
    if (para.length) blocks.push(`<p>${inlineMd(para.join(" "))}</p>`);
    para = [];
  };
  let items = [];
  let listTag = null;
  const flushList = () => {
    if (items.length) blocks.push(`<${listTag}>${items.map((i) => `<li>${inlineMd(i)}</li>`).join("")}</${listTag}>`);
    items = [];
    listTag = null;
  };
  for (const raw of md.split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (bullet || numbered) {
      flushPara();
      const tag = bullet ? "ul" : "ol";
      if (listTag && listTag !== tag) flushList();
      listTag = tag;
      items.push((bullet || numbered)[1]);
    } else if (heading) {
      flushPara();
      flushList();
      blocks.push(`<p><strong>${inlineMd(heading[1])}</strong></p>`);
    } else if (!line.trim()) {
      flushPara();
      flushList();
    } else {
      flushList();
      para.push(line.trim());
    }
  }
  flushPara();
  flushList();
  return blocks.join("");
}

function html(markup) {
  const div = document.createElement("div");
  div.innerHTML = markup;
  return div;
}

// --- cards -----------------------------------------------------------------

const BRANCH_TURN = {
  deeper: () => ({ action: "dive" }),
  related: (b) => ({ action: "branch", concept: b.concept }),
  switch: () => ({ action: "switch" }),
};

// Language: "en", "zh" or "both". Cards are written in English; card.zh holds the Chinese
// (same fields, lists paired by index). Remembered per browser.
const LANGS = ["en", "zh", "both"];
function loadLang() {
  try {
    const v = localStorage.getItem("lang");
    return LANGS.includes(v) ? v : "both";
  } catch {
    return "both";
  }
}

// One text field in the chosen language(s). In "both", the Chinese follows on its own line.
function bi(en, zh) {
  if (!en && !zh) return [];
  if (state.lang === "en" || !zh) return [en];
  if (state.lang === "zh") return [el("span", { class: "zh-only", lang: "zh-Hans" }, zh)];
  return [en, el("span", { class: "zh", lang: "zh-Hans" }, zh)];
}

const LABELS = {
  example: { en: "Example: ", zh: "例子：" },
  bridge: { en: "For you: ", zh: "联系你的领域：" },
};
const label = (key) => (state.lang === "zh" ? LABELS[key].zh : LABELS[key].en);

// Final cards are registered by message id, so a late translation or a language switch can
// re-render them in place.
const cards = new Map(); // messageId -> { card, conceptId }

function rerenderCard(messageId) {
  const entry = cards.get(messageId);
  const node = document.querySelector(`article.card[data-message-id="${messageId}"]`);
  if (entry && node) node.replaceWith(renderCard(entry.card, { final: true, messageId, conceptId: entry.conceptId }));
}

function rerenderAllCards() {
  for (const id of cards.keys()) rerenderCard(id);
}

async function translateCard(messageId, button) {
  button.disabled = true;
  button.textContent = "翻译中…";
  try {
    const { zh } = await api(`/messages/${messageId}/translate`, { method: "POST" });
    cards.get(messageId).card.zh = zh;
    rerenderCard(messageId);
  } catch (e) {
    button.disabled = false;
    button.textContent = `翻译失败，重试 (${e.message})`;
  }
}

// Renders a (possibly partial) card. Fields that haven't streamed in yet are skipped.
// Final cards carry their message and concept ids, which enable the concept link and "+ takeaway".
function renderCard(card, { final = false, messageId = null, conceptId = null } = {}) {
  if (final && messageId) cards.set(messageId, { card, conceptId });
  const zh = card.zh || {};
  const tag = [card.kind, card.depth].filter(Boolean).join(" · ");
  const highlights = (card.highlights || []).map((h, i) => [h, (zh.highlights || [])[i]]).filter(([h]) => h);
  const branches = final ? card.branches || [] : [];
  const needsTranslation = final && messageId && state.lang !== "en" && !card.zh;
  const article = el("article", { class: "card", ...(messageId ? { "data-message-id": messageId } : {}) });
  append(article,
    el("div", { class: "card-head" },
      el("span", { class: "card-concept" },
        conceptId
          ? el("a", { href: "#", onclick: (e) => { e.preventDefault(); showConcept(conceptId); setSheet(true); } }, ...bi(card.concept, zh.concept))
          : card.concept || ""),
      el("span", { class: "card-tag" }, tag)),
    card.one_liner && el("p", { class: "one-liner" }, ...bi(card.one_liner, zh.one_liner)),
    card.example && el("p", {}, el("span", { class: "label" }, label("example")), ...bi(card.example, zh.example)),
    renderDiagram(card.diagram, zh),
    highlights.length > 0 && el("ul", { class: "highlights" }, highlights.map(([h, hz]) => el("li", {}, ...bi(h, hz)))),
    card.bridge && el("p", { class: "bridge" }, el("span", { class: "label" }, label("bridge")), ...bi(card.bridge, zh.bridge)),
    card.body_md && renderBody(card.body_md, zh.body_md),
    renderImages(card.images, zh.captions),
    branches.length > 0 &&
      el("div", { class: "branches" },
        branches.map((b, i) => {
          const zhLabel = (zh.branch_labels || [])[i];
          const text = state.lang === "zh" && zhLabel ? zhLabel : state.lang === "both" && zhLabel ? `${b.label} · ${zhLabel}` : b.label;
          return el("button", {
            type: "button",
            class: "branch",
            "data-kind": b.kind,
            onclick: () => sendTurn(BRANCH_TURN[b.kind](b)),
          }, b.kind === "related" ? `→ ${text}` : text);
        })),
    final && conceptId &&
      el("div", { class: "card-actions" },
        el("button", {
          type: "button",
          class: "link-button",
          onclick: (e) => {
            e.target.parentElement.remove();
            article.append(takeawayForm({ conceptId, messageId, onDone: () => showConcept(conceptId) }));
          },
        }, "+ takeaway"),
        needsTranslation &&
          el("button", { type: "button", class: "link-button translate", onclick: (e) => translateCard(messageId, e.target) }, "翻译成中文"),
        messageId === state.sparkMessageId &&
          el("button", { type: "button", class: "link-button not-interested", onclick: (e) => notInterested(e.target) }, "Not interested → another")),
  );
  return article;
}

function renderBody(md, zhMd) {
  if (state.lang === "en" || !zhMd) return el("div", { class: "body" }, html(renderMd(md)));
  const zhBlock = el("div", { class: "body-zh", lang: "zh-Hans" }, html(renderMd(zhMd)));
  if (state.lang === "zh") return el("div", { class: "body" }, zhBlock);
  return el("div", { class: "body" }, html(renderMd(md)), zhBlock);
}

// --- diagrams ----------------------------------------------------------------
// The card supplies structured items; each kind is drawn here (see services/diagrams.py).
// Items stream in one by one, so every renderer copes with a partial list.

const MIN_ITEMS = { flow: 2, cycle: 3, timeline: 2, compare: 2, bars: 2, causes: 2 };

function diagramItems(d) {
  // Cards stored before 2026-10-28 have {steps: [{label, detail}]}.
  return (d.items || d.steps || []).filter((i) => i && i.label);
}

function zhDiagram(zh) {
  const items = zh.diagram_items || zh.diagram_steps || [];
  return { title: zh.diagram_title, columns: zh.diagram_columns || [], items };
}

// Text for a tight spot (ring labels, column headings): one language only.
const pick = (en, zh) => (state.lang === "zh" && zh ? zh : en);

function renderDiagram(d, zh = {}) {
  if (!d || !MIN_ITEMS[d.kind]) return null;
  const items = diagramItems(d);
  if (items.length < MIN_ITEMS[d.kind]) return null;
  const z = zhDiagram(zh);
  const draw = { flow: drawFlow, cycle: drawCycle, timeline: drawTimeline, bars: drawBars, compare: drawCompare, causes: drawCauses }[d.kind];
  return el("figure", { class: `diagram diagram-${d.kind}` },
    d.title && el("figcaption", {}, ...bi(d.title, z.title)),
    draw(items, z, d));
}

function drawFlow(items, z) {
  return el("ol", { class: "flow" },
    items.map((s, i) =>
      el("li", {},
        el("span", { class: "step-n" }, String(i + 1)),
        el("strong", {}, ...bi(s.label, z.items[i]?.label)),
        s.detail && el("span", { class: "step-detail" }, ...bi(s.detail, z.items[i]?.detail)))));
}

let svgIds = 0;
function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  node.append(...children);
  return node;
}

// A real ring: stages placed around a circle, arcs with arrowheads between them, details below.
function drawCycle(items, z) {
  const n = items.length;
  const R = 38; // ring radius, in % of the box
  const pos = (i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return [50 + R * Math.cos(a), 50 + R * Math.sin(a), a];
  };
  const id = `arrow-${++svgIds}`;
  const gap = Math.min(0.32, Math.PI / n / 1.6); // leave room around each node
  const arcs = items.map((_, i) => {
    const a1 = -Math.PI / 2 + (2 * Math.PI * i) / n + gap;
    const a2 = -Math.PI / 2 + (2 * Math.PI * (i + 1)) / n - gap;
    const [x1, y1] = [50 + R * Math.cos(a1), 50 + R * Math.sin(a1)];
    const [x2, y2] = [50 + R * Math.cos(a2), 50 + R * Math.sin(a2)];
    return svg("path", { d: `M ${x1} ${y1} A ${R} ${R} 0 0 1 ${x2} ${y2}`, class: "ring-arc", "marker-end": `url(#${id})` });
  });
  const ring = svg("svg", { viewBox: "0 0 100 100", class: "ring", "aria-hidden": "true" },
    svg("defs", {},
      svg("marker", { id, viewBox: "0 0 10 10", refX: "8", refY: "5", markerWidth: "5", markerHeight: "5", orient: "auto-start-reverse" },
        svg("path", { d: "M 0 0 L 10 5 L 0 10 z", class: "ring-head" }))),
    ...arcs);
  const nodes = items.map((s, i) => {
    const [x, y] = pos(i);
    return el("div", { class: "ring-node", style: `left:${x}%;top:${y}%` },
      el("span", { class: "step-n" }, String(i + 1)), " ", pick(s.label, z.items[i]?.label));
  });
  return el("div", {},
    el("div", { class: "ring-box" }, ring, ...nodes),
    el("ol", { class: "legend" },
      items.map((s, i) =>
        el("li", {},
          el("strong", {}, ...bi(s.label, z.items[i]?.label)),
          s.detail && el("span", { class: "step-detail" }, ...bi(s.detail, z.items[i]?.detail))))));
}

function drawTimeline(items, z) {
  return el("ol", { class: "timeline" },
    items.map((s, i) =>
      el("li", {},
        el("span", { class: "when" }, ...bi(s.label, z.items[i]?.label)),
        el("span", { class: "what" }, ...bi(s.detail, z.items[i]?.detail)))));
}

// Bars to scale. Linear, so "8,000 L vs 40 L" looks as big as it is; log only when the values span
// more than 1,000x and linear would leave most bars invisible.
function drawBars(rawItems, z) {
  // Sorted by size so the comparison reads at a glance; z.items stay paired via the original index.
  const order = rawItems.map((it, i) => [it, i]).sort((a, b) => (Number(a[0].value) || 0) - (Number(b[0].value) || 0));
  const items = order.map(([it]) => it);
  z = { ...z, items: order.map(([, i]) => z.items[i]) };
  const vals = items.map((i) => Number(i.value) || 0).filter((v) => v > 0);
  if (vals.length < 2) return el("p", { class: "muted" }, "…");
  const max = Math.max(...vals);
  const min = Math.min(...vals);
  const log = max / min > 1000;
  const width = (v) => {
    if (!(v > 0)) return 0;
    if (!log) return (100 * v) / max;
    const lo = Math.log10(min) - 0.3;
    return (100 * (Math.log10(v) - lo)) / (Math.log10(max) - lo);
  };
  return el("div", {},
    el("div", { class: "bars" },
      items.map((s, i) =>
        el("div", { class: "bar-row" },
          el("span", { class: "bar-label" }, ...bi(s.label, z.items[i]?.label)),
          el("span", { class: "bar-track" },
            el("span", { class: "bar-fill", style: `width:${Math.max(2, width(Number(s.value))).toFixed(1)}%` })),
          el("span", { class: "bar-value" }, pick(s.value_text || String(s.value), z.items[i]?.value_text))))),
    log && el("p", { class: "scale-note" }, state.lang === "zh" ? "对数刻度：每一格是十倍" : "Log scale: each step is 10×"));
}

function drawCompare(items, z, d) {
  const cols = d.columns || [];
  return el("table", { class: "compare" },
    el("thead", {}, el("tr", {}, el("th", {}), ...[0, 1].map((c) => el("th", {}, pick(cols[c] || "", z.columns[c]))))),
    el("tbody", {},
      items.map((s, i) =>
        el("tr", {},
          el("th", { scope: "row" }, ...bi(s.label, z.items[i]?.label)),
          el("td", {}, ...bi(s.detail, z.items[i]?.detail)),
          el("td", {}, ...bi(s.detail_b, z.items[i]?.detail_b))))));
}

// Factors on the left converge on the outcome (the diagram title) on the right.
function drawCauses(items, z, d) {
  return el("div", { class: "causes" },
    el("ul", { class: "factors" },
      items.map((s, i) =>
        el("li", {},
          el("strong", {}, ...bi(s.label, z.items[i]?.label)),
          s.detail && el("span", { class: "step-detail" }, ...bi(s.detail, z.items[i]?.detail))))),
    el("div", { class: "converge", "aria-hidden": "true" }, "→"),
    el("div", { class: "outcome" }, pick(d.title || "", z.title)));
}

// Images the server resolved from Wikipedia (final cards only).
function renderImages(images, zhCaptions = []) {
  if (!images || images.length === 0) return null;
  return el("div", { class: "pictures" },
    images.map((img, i) =>
      el("figure", {},
        el("a", { href: img.page_url, target: "_blank", rel: "noopener noreferrer" },
          el("img", { src: img.thumb_url, alt: img.caption || img.title, loading: "lazy" })),
        el("figcaption", {},
          ...bi(img.caption, zhCaptions[i]), " ",
          el("a", { href: img.page_url, target: "_blank", rel: "noopener noreferrer", class: "source" }, `Wikipedia: ${img.title}`)))));
}

function renderMessage(msg) {
  if (msg.role === "user") return el("div", { class: "user-msg" }, msg.content);
  return msg.card
    ? renderCard(msg.card, { final: true, messageId: msg.id, conceptId: msg.concept_id })
    : el("div", { class: "user-msg" }, msg.content);
}

function scrollToBottom() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

function setStreaming(on) {
  state.streaming = on;
  els.send.hidden = on;
  els.stop.hidden = !on;
  els.surprise.disabled = on;
  els.depth.disabled = on;
  document.querySelectorAll("button.branch, button.ask").forEach((b) => (b.disabled = on));
}

// --- threads ---------------------------------------------------------------

async function loadThreads() {
  const threads = await api("/threads");
  state.threadTitles = Object.fromEntries(threads.map((t) => [t.id, t.title || "Untitled"]));
  els.threads.replaceChildren(
    ...threads.map((t) =>
      el("li", {},
        el("a", { href: `#/t/${t.id}`, class: t.id === state.threadId ? "active" : "" }, t.title || "Untitled"))),
  );
}

async function openThread(id) {
  state.threadId = id;
  const thread = await api(`/threads/${id}`);
  els.title.textContent = thread.title || "Untitled";
  els.depth.value = thread.depth;
  cards.clear();
  // The first card of a Surprise me thread gets the "Not interested" button.
  state.sparkMessageId =
    thread.messages[0]?.action === "spark" ? thread.messages.find((m) => m.role === "assistant")?.id : null;
  els.messages.replaceChildren(...thread.messages.map(renderMessage));
  scrollToBottom();
  setStreaming(false);
  await loadThreads();
  if (thread.current_concept_id) showConcept(thread.current_concept_id);
  else clearPanel();
}

function newThread() {
  state.threadId = null;
  state.sparkMessageId = null;
  history.replaceState(null, "", "#");
  els.title.textContent = "New exploration";
  els.depth.value = "explain";
  cards.clear();
  els.messages.replaceChildren(els.empty);
  loadThreads();
  clearPanel();
  els.input.focus();
}

function route() {
  const m = location.hash.match(/^#\/t\/([0-9a-f-]{36})$/);
  if (m) openThread(m[1]).catch(() => newThread());
  else newThread();
}

// --- turns -----------------------------------------------------------------

// Same text the server stores for turns without typed text (services/orchestrator.py).
const DEFAULT_LABEL = {
  dive: () => "Go deeper.",
  branch: (b) => `Related: ${b.concept}`,
  switch: () => "Show me something completely different.",
  spark: (b) => `Surprise me: ${b.text || b.concept}`,
};

async function sendTurn(body) {
  if (state.streaming) return;
  setStreaming(true);
  state.lastTurn = body;

  try {
    if (!state.threadId) {
      const thread = await api("/threads", { method: "POST", body: {} });
      state.threadId = thread.id;
      history.replaceState(null, "", `#/t/${thread.id}`);
      els.messages.replaceChildren();
    }
  } catch (e) {
    showError({ message: e.message });
    setStreaming(false);
    return;
  }

  // Optimistic user bubble; the server stores the same text.
  const label = body.action === "spark" ? DEFAULT_LABEL.spark(body) : body.text || DEFAULT_LABEL[body.action](body);
  els.messages.append(el("div", { class: "user-msg" }, label));
  let slot = el("div", { class: "status" }, "Starting");
  els.messages.append(slot);
  scrollToBottom();

  const replace = (node) => {
    slot.replaceWith(node);
    slot = node;
  };

  const abort = new AbortController();
  state.abort = abort;
  let finished = false; // a card or an error arrived
  try {
    await streamTurn(state.threadId, body, (name, data) => {
      if (name === "meta") els.depth.value = data.depth;
      else if (name === "status") replace(el("div", { class: "status" }, "Thinking"));
      else if (name === "card") replace(renderCard(data));
      else if (name === "done") {
        finished = true;
        if (body.action === "spark") state.sparkMessageId = data.message_id;
        replace(renderCard(data.card, { final: true, messageId: data.message_id, conceptId: data.concept_id }));
        setStreaming(false); // a title may still follow; the card is usable now
        if (state.abort === abort) state.abort = null; // Stop no longer applies to this turn
        if (els.title.textContent === "New exploration") els.title.textContent = data.card.concept;
        showConcept(data.concept_id);
        loadConcepts();
        loadThreads();
      } else if (name === "translation") {
        const entry = cards.get(data.message_id);
        if (entry) {
          entry.card.zh = data.zh;
          rerenderCard(data.message_id);
        }
      } else if (name === "title") {
        els.title.textContent = data.title;
        loadThreads();
      } else if (name === "error") {
        finished = true;
        replace(errorBox(data));
      }
      if (name !== "title") scrollToBottom();
    }, abort.signal);
    if (!finished) replace(errorBox({ message: "The connection closed before the card finished." }));
  } catch (e) {
    if (!finished) {
      const stopped = e.name === "AbortError";
      replace(errorBox({ message: stopped ? "Stopped." : `Connection lost: ${e.message}` }));
    }
  }
  checkHealth(); // spend line, and the banner if a budget is near or reached
  // The stream stays open for the title after `done`; by then a newer turn may be running.
  if (state.abort === abort) {
    state.abort = null;
    setStreaming(false);
  }
}

async function surprise() {
  if (state.streaming) return;
  newThread();
  const slot = el("div", { class: "status" }, "Picking something surprising");
  els.messages.replaceChildren(slot);
  setStreaming(true);
  let pick;
  try {
    pick = await api("/spark", { method: "POST" });
  } catch (e) {
    slot.replaceWith(el("div", { class: "error" }, e.message, el("button", { type: "button", onclick: surprise }, "Retry")));
    setStreaming(false);
    checkHealth();
    return;
  }
  slot.remove();
  setStreaming(false);
  sendTurn({
    action: "spark",
    concept: pick.concept,
    text: pick.question,
    topic_area: pick.topic_area,
    angle: pick.angle,
    depth: els.depth.value,
  });
}

// Tells Surprise me to show this kind of pick less, then picks another.
async function notInterested(button) {
  if (state.streaming) return;
  button.disabled = true;
  try {
    await api(`/threads/${state.threadId}/not-interested`, { method: "POST" });
  } catch (e) {
    button.disabled = false;
    button.textContent = `Couldn't save (${e.message}). Retry`;
    return;
  }
  surprise();
}

// One banner for setup problems and budget warnings; refreshed on load and after every turn.
async function checkHealth() {
  const problems = [];
  try {
    const h = await api("/health");
    if (!h.db) problems.push("The database is unreachable (is Docker running? try `make dev`).");
    if (!h.anthropic_api_key) problems.push("ANTHROPIC_API_KEY is not set in .env, so cards can't be generated. Add it and restart.");
    if (h.db) {
      const u = await api("/usage");
      showSpend(u);
      if (u.blocked) problems.push(u.reason);
      else if (u.warn) problems.push(`Heads up: over 80% of a budget used (${spendText(u)}).`);
    }
  } catch {
    problems.push("The API server isn't responding.");
  }
  els.banner.textContent = problems.join(" ");
  els.banner.hidden = problems.length === 0;
}

const usd = (x) => `$${x.toFixed(2)}`;
const limit = (x) => (x > 0 ? ` / ${usd(x)}` : "");

function spendText(u) {
  return `today ${usd(u.today_usd)}${limit(u.daily_budget_usd)} · month ${usd(u.month_usd)}${limit(u.monthly_budget_usd)}`;
}

function showSpend(u) {
  els.spend.textContent = `API spend: ${spendText(u)}`;
  els.spend.classList.toggle("warn", u.warn);
}

function errorBox(err) {
  const box = el("div", { class: "error" },
    el("span", {}, err.message || "Something went wrong."),
    state.lastTurn && el("button", {
      type: "button",
      onclick: () => {
        box.previousElementSibling?.remove(); // the optimistic user bubble; the retry re-adds it
        box.remove();
        sendTurn(state.lastTurn);
      },
    }, "Retry"));
  return box;
}

function showError(err) {
  els.messages.append(errorBox(err));
  scrollToBottom();
}

// --- concepts & the right panel --------------------------------------------

async function loadConcepts() {
  const concepts = await api("/concepts?limit=500");
  els.concepts.replaceChildren(
    ...concepts.map((c) =>
      el("li", {},
        el("a", {
          href: "#",
          "data-id": c.id,
          class: c.id === state.panelConceptId ? "active" : "",
          title: c.explored ? "" : "not explored yet",
          onclick: (e) => { e.preventDefault(); showConcept(c.id); setDrawer(false); setSheet(true); },
        }, c.explored ? c.name : `${c.name} ·`))),
  );
}

function clearPanel() {
  state.panelConceptId = null;
  els.panel.replaceChildren(el("p", { class: "muted" }, "Your links and takeaways for the current concept show up here."));
}

async function showConcept(id) {
  state.panelConceptId = id;
  let detail;
  try {
    detail = await api(`/concepts/${id}`);
  } catch (e) {
    els.panel.replaceChildren(el("p", { class: "form-error" }, e.message));
    return;
  }
  if (state.panelConceptId !== id) return; // a newer request won
  const { concept, cards, links, takeaways } = detail;
  const refresh = () => { showConcept(id); loadConcepts(); };

  const threadsSeen = [...new Map(cards.map((m) => [m.thread_id, m])).values()];

  els.panel.replaceChildren();
  append(els.panel,
    el("p", { class: "kind" }, "Concept"),
    el("p", { class: "concept-name" }, concept.name),
    !concept.explored && el("p", { class: "muted" }, "Not explored yet."),

    el("h2", {}, `Links (${links.length})`),
    links.length > 0 &&
      el("ul", {}, links.map((l) =>
        el("li", {},
          el("div", { class: "row" },
            el("a", { href: "#", onclick: (e) => { e.preventDefault(); showConcept(l.concept.id); } }, l.concept.name),
            el("button", {
              type: "button",
              class: "link-button",
              title: "Remove link",
              onclick: async () => { await api(`/links/${l.link_id}`, { method: "DELETE" }); refresh(); },
            }, "×")),
          l.note && el("div", { class: "note" }, l.note)))),
    linkForm(concept, refresh),

    el("h2", {}, `My takeaways (${takeaways.length})`),
    takeaways.length > 0 &&
      el("ul", {}, takeaways.map((t) =>
        el("li", {},
          el("div", { class: "row" },
            el("span", { class: `kind kind-${t.kind}` }, t.kind),
            el("button", {
              type: "button",
              class: "link-button",
              title: "Delete",
              onclick: async () => { await api(`/takeaways/${t.id}`, { method: "DELETE" }); refresh(); },
            }, "×")),
          el("div", {}, t.body),
          t.concepts.length > 1 &&
            el("div", { class: "note" }, "also: " + t.concepts.filter((c) => c.id !== id).map((c) => c.name).join(", ")),
          t.kind === "question" &&
            el("button", {
              type: "button",
              class: "ask",
              disabled: state.streaming,
              onclick: () => sendTurn({ action: "ask", text: t.body, takeaway_id: t.id }),
            }, "Ask")))),
    takeawayForm({ conceptId: id, onDone: refresh }),

    threadsSeen.length > 0 && el("h2", {}, "Explored in"),
    threadsSeen.length > 0 &&
      el("ul", {}, threadsSeen.map((m) =>
        el("li", {}, el("a", { href: `#/t/${m.thread_id}` }, state.threadTitles[m.thread_id] || "a thread")))),
  );
  els.concepts.querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.id === id));
}

function linkForm(concept, onDone) {
  const name = el("input", { list: "concept-options", placeholder: "Link to concept…", required: "" });
  const note = el("input", { placeholder: "How are they connected? (optional)" });
  const msg = el("span", { class: "form-error" });
  let timer;
  name.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = name.value.trim();
      const options = q ? await api(`/concepts?q=${encodeURIComponent(q)}&limit=10`) : [];
      els.conceptOptions.replaceChildren(
        ...options.filter((c) => c.id !== concept.id).map((c) => el("option", { value: c.name })),
      );
    }, 150);
  });
  return el("form", {
    class: "stack",
    onsubmit: async (e) => {
      e.preventDefault();
      msg.textContent = "";
      try {
        // get-or-create: linking to a concept you haven't explored yet is fine.
        const other = await api("/concepts", { method: "POST", body: { name: name.value } });
        await api("/links", {
          method: "POST",
          body: { a_concept_id: concept.id, b_concept_id: other.id, note: note.value },
        });
        onDone();
      } catch (err) {
        msg.textContent = err.message === "HTTP 409" ? "Already linked." : err.message;
      }
    },
  }, name, note, el("div", { class: "actions" }, msg, el("button", { type: "submit" }, "Link")));
}

function takeawayForm({ conceptId, messageId = null, onDone }) {
  const kind = el("select", {},
    el("option", { value: "takeaway" }, "takeaway"),
    el("option", { value: "idea" }, "idea"),
    el("option", { value: "question" }, "question"));
  const body = el("textarea", { rows: "3", placeholder: "Your takeaway, idea, or question…", required: "" });
  const msg = el("span", { class: "form-error" });
  const form = el("form", {
    class: "stack",
    onsubmit: async (e) => {
      e.preventDefault();
      msg.textContent = "";
      try {
        await api("/takeaways", {
          method: "POST",
          body: { kind: kind.value, body: body.value, concept_ids: [conceptId], message_id: messageId },
        });
        if (messageId) form.replaceWith(el("p", { class: "muted" }, "Saved to the concept panel."));
        else body.value = "";
        onDone();
      } catch (err) {
        msg.textContent = err.message;
      }
    },
  }, body, el("div", { class: "actions" }, msg, kind, el("button", { type: "submit" }, "Save")));
  if (messageId) setTimeout(() => body.focus());
  return form;
}

// --- events ----------------------------------------------------------------

els.composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.input.value.trim();
  if (!text || state.streaming) return;
  els.input.value = "";
  // A depth picked before the first message has no thread to PATCH yet, so send it with the turn.
  sendTurn(state.threadId ? { action: "ask", text } : { action: "ask", text, depth: els.depth.value });
});

els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    els.composer.requestSubmit();
  }
});

els.depth.addEventListener("change", async () => {
  if (!state.threadId) return; // new thread: sent with the first turn
  await api(`/threads/${state.threadId}`, { method: "PATCH", body: { depth: els.depth.value } });
});

function setLangButtons() {
  document.querySelectorAll("#lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === state.lang)));
}

document.querySelectorAll("#lang button").forEach((b) =>
  b.addEventListener("click", () => {
    state.lang = b.dataset.lang;
    try {
      localStorage.setItem("lang", state.lang);
    } catch {
      /* private window: the choice just isn't remembered */
    }
    setLangButtons();
    rerenderAllCards();
  }));

// --- phone: the sidebar becomes a drawer and the concept panel a bottom sheet (CSS ≤700px) ---

function setDrawer(open) {
  els.layout.classList.toggle("menu-open", open);
  els.menu.setAttribute("aria-expanded", String(open));
  els.scrim.hidden = !els.layout.matches(".menu-open, .sheet-open");
}

function setSheet(open) {
  els.layout.classList.toggle("sheet-open", open);
  els.scrim.hidden = !els.layout.matches(".menu-open, .sheet-open");
}

function closeOverlays() {
  setDrawer(false);
  setSheet(false);
}

els.menu.addEventListener("click", () => setDrawer(!els.layout.classList.contains("menu-open")));
els.notes.addEventListener("click", () => setSheet(true));
$("#sheet-close").addEventListener("click", closeOverlays);
els.scrim.addEventListener("click", closeOverlays);
document.addEventListener("keydown", (e) => e.key === "Escape" && closeOverlays());

els.newThread.addEventListener("click", () => { setDrawer(false); newThread(); });
els.surprise.addEventListener("click", () => { setDrawer(false); surprise(); });
els.stop.addEventListener("click", () => state.abort?.abort());
window.addEventListener("hashchange", () => { closeOverlays(); route(); });

state.lang = loadLang();
setLangButtons();
checkHealth();
loadConcepts();
route();
