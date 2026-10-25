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
};

const state = {
  threadId: null,
  streaming: false,
  lastTurn: null, // last turn request body, for Retry
};

// --- API -------------------------------------------------------------------

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "content-type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(typeof detail.detail === "string" ? detail.detail : `HTTP ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

// POST a turn and call onEvent(name, data) for each server-sent event.
async function streamTurn(threadId, body, onEvent) {
  const res = await fetch(`/api/threads/${threadId}/turns`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
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

// Renders a (possibly partial) card. Fields that haven't streamed in yet are skipped.
function renderCard(card, { final = false } = {}) {
  const tag = [card.kind, card.depth].filter(Boolean).join(" · ");
  const highlights = (card.highlights || []).filter(Boolean);
  const branches = final ? card.branches || [] : [];
  return el(
    "article",
    { class: "card" },
    el("div", { class: "card-head" },
      el("span", { class: "card-concept" }, card.concept || ""),
      el("span", { class: "card-tag" }, tag)),
    card.one_liner && el("p", { class: "one-liner" }, card.one_liner),
    card.example && el("p", {}, el("span", { class: "label" }, "Example: "), card.example),
    highlights.length > 0 && el("ul", { class: "highlights" }, highlights.map((h) => el("li", {}, h))),
    card.bridge && el("p", { class: "bridge" }, el("span", { class: "label" }, "For you: "), card.bridge),
    card.body_md && el("div", { class: "body" }, html(renderMd(card.body_md))),
    branches.length > 0 &&
      el("div", { class: "branches" },
        branches.map((b) =>
          el("button", {
            type: "button",
            class: "branch",
            "data-kind": b.kind,
            onclick: () => sendTurn(BRANCH_TURN[b.kind](b)),
          }, b.kind === "related" ? `→ ${b.label}` : b.label))),
  );
}

function renderMessage(msg) {
  if (msg.role === "user") return el("div", { class: "user-msg" }, msg.content);
  return msg.card ? renderCard(msg.card, { final: true }) : el("div", { class: "user-msg" }, msg.content);
}

function scrollToBottom() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

function setStreaming(on) {
  state.streaming = on;
  els.send.disabled = on;
  els.depth.disabled = on;
  document.querySelectorAll("button.branch").forEach((b) => (b.disabled = on));
}

// --- threads ---------------------------------------------------------------

async function loadThreads() {
  const threads = await api("/threads");
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
  els.messages.replaceChildren(...thread.messages.map(renderMessage));
  scrollToBottom();
  setStreaming(false);
  loadThreads();
}

function newThread() {
  state.threadId = null;
  history.replaceState(null, "", "#");
  els.title.textContent = "New exploration";
  els.depth.value = "explain";
  els.messages.replaceChildren(els.empty);
  loadThreads();
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
  const label = body.text || DEFAULT_LABEL[body.action](body);
  els.messages.append(el("div", { class: "user-msg" }, label));
  let slot = el("div", { class: "status" }, "Starting");
  els.messages.append(slot);
  scrollToBottom();

  const replace = (node) => {
    slot.replaceWith(node);
    slot = node;
  };

  let failed = false;
  try {
    await streamTurn(state.threadId, body, (name, data) => {
      if (name === "meta") els.depth.value = data.depth;
      else if (name === "status") replace(el("div", { class: "status" }, "Thinking"));
      else if (name === "card") replace(renderCard(data));
      else if (name === "done") replace(renderCard(data.card, { final: true }));
      else if (name === "error") {
        failed = true;
        replace(errorBox(data));
      }
      scrollToBottom();
    });
  } catch (e) {
    failed = true;
    replace(errorBox({ message: `Connection lost: ${e.message}` }));
  }

  setStreaming(false);
  if (!failed) {
    const thread = await api(`/threads/${state.threadId}`);
    els.title.textContent = thread.title || "Untitled";
  }
  loadThreads();
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

els.newThread.addEventListener("click", newThread);
window.addEventListener("hashchange", route);

route();
