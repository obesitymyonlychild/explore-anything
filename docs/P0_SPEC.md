# P0 MVP: Detailed Spec

> Goal: prove the **features** work before investing in UI. Explore any concept through structured
> **hook cards**, **connect concepts yourself**, and capture **your own takeaways, ideas and questions**,
> all in a deliberately bare-bones local web page.

Related: [ARCHITECTURE.md](ARCHITECTURE.md)

**Principle:** the MVP UI is minimal and disposable. Each feature first goes in as plain HTML. Once a
feature proves useful in daily use, it gets real UI work in P1.

---

## 1. The three layers

| Layer | What it holds | Who creates it (MVP) |
|---|---|---|
| **1. Exploration** | Threads and messages: what Claude explained, as hook cards | Claude, steered by you |
| **2. Concepts & links** | One record per concept you've met, plus **links** between concepts ("these are connected because…") | Concepts: registered automatically when a card is about them. **Links: you, manually** |
| **3. Insights** | **Your** takeaways, ideas and questions, e.g. *"this is where the product actually works; could XX improve it? does that already exist?"* Attached to one or more concepts | **You, manually** |

Layer 1 is what the AI knows. Layers 2 and 3 are **your thinking**. That's the part a plain chat never captures, and the part P2+ will build on (AI-suggested links, search, revisits).

---

## 2. Scope

### In
- Start a thread by **typing a concept or question**, or **Surprise me** (simple version).
- Every assistant reply streams in as a **hook card** (§4) with branch buttons and a depth dial.
- **Concepts** registered automatically from each card's `concept` field (deduplicated by name).
- **Manual links**: connect the current concept to any other concept (existing, or new by name), with a short "how they connect" note.
- **Takeaways**: add a takeaway / idea / question to any card; it attaches to that card's concept (more concepts can be added).
- A question-type takeaway has an **Ask** button that sends it into the thread, so Claude can answer "does that exist?".
- **Concept page**: everything about one concept: the cards about it, its links, your takeaways.
- **Claude sees your layer**: when a thread is on a concept you've linked or annotated, those links and takeaways are included in the prompt, so answers can build on them.
- Interest events logged from day one.

### Out (later)
Polished UI, graph view, Obsidian export (P1) · AI-suggested links, embeddings, search (P2) · smart Surprise me (P3) · auth and deploy (P4).

### Definition of done
1. `make dev` starts the DB and the API, which also serves the page, on a fresh clone with `ANTHROPIC_API_KEY` set.
2. "air conditioning" → a card starts streaming within ~2 s with an example, highlights, a data-science bridge and 4 branches.
3. *Go deeper* twice → depth reaches `mechanism`; answers get clearly more technical.
4. Explore "heat pump" in another thread, then link it to "air conditioning" with a note. The link shows on both concept pages.
5. Add an idea to a card ("could predictive maintenance on the compressor cut energy use? does it exist?"), press **Ask**, and get a card answering it in context.
6. Reopen the browser → threads, concepts, links and takeaways are all there.

---

## 3. Minimal UI

**No frontend framework or build step.** FastAPI serves one `index.html` + `app.js` + `style.css` (plain JS, about 300 lines). It uses the same JSON API the real frontend will use later, so nothing is thrown away except the page itself.

```
┌─────────────┬───────────────────────────────────────┬──────────────────────┐
│ [+ New]     │ Air conditioning      depth [explain▾]│ CONCEPT              │
│ [Surprise]  │                                       │ Air conditioning     │
│             │ > how does air conditioning work?     │                      │
│ Threads     │                                       │ Links                │
│ - Air cond. │ AIR CONDITIONING                      │ - Heat pump: "same   │
│ - Tides     │ A heat pump that moves heat out...    │   cycle, run in      │
│             │ Example: touch the back of your...    │   reverse"           │
│ Concepts    │ * Refrigerant boils at -26 °C         │ [link to: ____ ]     │
│ - Air cond. │ * ...                                 │ [why: ______ ] [+]   │
│ - Heat pump │ For you: thermostat = feedback loop   │                      │
│ - Tides     │ [Deeper] [Refrig. cycle] [Heat        │ My takeaways         │
│             │  pumps] [Something else]              │ 💡 Predictive maint. │
│             │ [+ takeaway]                          │    on compressor?    │
│             │                                       │    [Ask]             │
│             │ [ ask anything...              ][Send]│                      │
└─────────────┴───────────────────────────────────────┴──────────────────────┘
```

- Left: threads and an alphabetical concept list (clicking a concept opens its page in the right panel).
- Middle: the thread. Cards are rendered as plain text blocks with buttons.
- Right: the **current concept**: its links (with an add form whose concept box autocompletes) and your takeaways.
- `+ takeaway` under a card opens an inline textarea with a kind selector: `takeaway | idea | question`.
- **Expertise profile**: a plain text file, `config/profile.md`, edited in your editor and read on each request. No settings screen.

### Interactions
| Action | Effect | Interest event |
|---|---|---|
| Type a concept / question | New thread, or next turn in the current one | `ask` |
| Surprise me | New thread on a random concept (§5.4) | `spark_shown`; the previous spark gets `skip` if untouched |
| Not interested → another | Marks this spark unwanted, then Surprise me again | `skip` (`how: not_interested`) |
| Deeper | `depth += 1` on the current concept | `dive` |
| Related: X | Same thread, focus moves to X | `branch` |
| Something else | Same thread, an unrelated concept | `switch` |
| Change depth dropdown | Sets depth from the next turn | `depth_set` |
| Add link | `concept_link` row | `link` |
| Add takeaway | `takeaway` row | `takeaway` |
| Ask (on a question) | Sends the question as an `ask` turn in the current thread | `ask` |

---

## 4. The hook card

### 4.1 Schema
One schema for every assistant turn, enforced with Claude **structured outputs** (`output_config.format` + JSON Schema).

```jsonc
{
  "concept":    "Air conditioning",          // canonical name → registers/looks up the concept
  "kind":       "intro",                     // intro | deeper | answer
  "depth":      "explain",                   // glance | explain | mechanism | expert
  "one_liner":  "A heat pump that moves heat out of a room.",
  "example":    "Touch the back of your fridge...",
  "highlights": ["...", "...", "..."],       // 0–3
  "diagram":    {"kind": "cycle", "title": "How a fridge moves heat",   // none|flow|cycle|timeline|compare|bars|causes
                 "columns": [],                                          // compare: the two headings
                 "items": [{"label": "Refrigerant evaporates", "detail": "soaks up heat from food",
                            "detail_b": "", "value": 0, "value_text": ""}, ...]},
  "bridge":     "A thermostat is a feedback controller...", // "" if no good analogy
  "body_md":    "",                          // longer explanation (deeper levels, free questions)
  "pictures":   [{"wikipedia_title": "Vapor-compression refrigeration", "caption": "Vapor-compression refrigeration on Wikipedia"}],
  "branches": [
    {"kind": "deeper",  "label": "Go deeper",           "concept": "Air conditioning"},
    {"kind": "related", "label": "Refrigeration cycle", "concept": "Vapor-compression refrigeration cycle"},
    {"kind": "related", "label": "Heat pumps",          "concept": "Heat pump"},
    {"kind": "switch",  "label": "Something else",      "concept": ""}
  ]
}
```
**Visuals** (adapted from the `visual-briefing` skill: smallest useful visual, never one that repeats the text):
- `diagram` is one small visual, drawn by the page from structured items. Claude chooses the kind by what the
  reader needs to see: a `cycle` (a real ring), a `timeline` (times or dates), `bars` (quantities to scale,
  linear unless they span over 1,000×), `compare` (two columns), `causes` (factors converging on one outcome),
  or `flow` (only for genuinely ordered steps); `none` when no visual adds anything. `services/diagrams.py`
  drops diagrams that can't be drawn well (too few items, bars without values, compare without two columns).
  No Mermaid, so there's no diagram syntax that can fail to render. Cards stored before 2026-10-28 use the
  older `steps` shape, which still renders.
- `pictures` are English Wikipedia article titles. The server resolves each one to the article's lead image
  through Wikipedia's free REST API (`services/pictures.py`) and adds `images: [{title, caption, thumb_url,
  page_url}]` to the stored card. Claude never writes image URLs, and captions name the subject only, since
  Claude can't see the image. Lookups cost nothing; throttled lookups (403/429) are retried once and never cached.
- Cost: about 120 extra output tokens per card (~$0.002).

**Chinese (简体)**: cards are always written in English (it's what history, concept names and branches use).
After each card, the light model translates it into Simplified Chinese (`services/translate.py`), streamed so
the Chinese fills in about 2 s after the English finishes, and stores it as `card["zh"]` (same text fields;
lists paired by index). The page has an EN / 中文 / Both toggle (remembered per browser). Cards made before
this get a "翻译成中文" button (`POST /api/messages/{id}/translate`). The cost is about $0.0007 per card,
recorded as purpose `translate`. Turn it off with `TRANSLATE_CARDS=false`.

Rules (in the system prompt):
- **intro**: `one_liner` + `example` + 2–3 `highlights` required.
- **deeper**: example and highlights move to the new level of detail; `body_md` carries the explanation.
- **answer** (free question or an Ask from a takeaway): `body_md` first; other fields may be empty; branches always present.
- Always 1 `deeper`, 2 `related`, 1 `switch` branch.
- When your takeaways or links are in context, Claude may refer to them ("you noted… — here's what exists").

### 4.2 Depth levels
| Level | Style |
|---|---|
| `glance` | One-liner + one vivid example, no jargon |
| `explain` *(default)* | How it works in plain terms; analogies |
| `mechanism` | The real physics/biology/engineering, key numbers |
| `expert` | Equations, trade-offs, failure modes, open problems |

---

## 5. LLM integration

### 5.1 Calls
| Call | Model | Settings |
|---|---|---|
| **Turn** (hook card) | `claude-opus-5-5` | streaming; `output_config: {effort: "low", format: <card schema>}` (low since M6; see evals/p0_cards.md); adaptive thinking (default); `max_tokens: 16000`; `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) |
| **Title** | `claude-haiku-5-5` | small schema `{title}`, after the first turn |
| **Spark** | `claude-haiku-5-5` | small schema `{concept, teaser}` |

Model names and effort are config values. We check `stop_reason` (`refusal`, `max_tokens`) and show an error card when needed.

### 5.2 Prompt assembly
```
system:
  [1] persona & card rules        (prompts/system.md, static)   ← cached prefix
  [2] depth definitions           (static)
  [3] expertise profile           (config/profile.md, rarely changes)
messages:
  ...thread history...            (user text; assistant turns replayed as their card JSON)
  user: [action=dive depth=mechanism concept="Air conditioning"]
        [your notes on this concept]
          links: Heat pump: "same cycle, run in reverse"
          idea: "could predictive maintenance on the compressor cut energy use?"
        <user text, if any>
```
- Per-turn context (action, depth, your links and takeaways) goes in the **user turn**, so the cached system prefix never changes and history stays append-only.
- Only the current concept's links and takeaways are included, capped at ~20 items (newest first).
- **History is append-only and replayed verbatim** from `message.api_content`: user turns exactly as sent
  (header included), assistant turns exactly as returned (thinking blocks included). Newer API accounts reject
  edited history that carries thinking blocks, and any change would also break prompt caching.
- If a stream fails, the user turn stays without a reply; the next turn (the retry) replaces it, so turns
  always alternate user/assistant.

### 5.3 Streaming a structured card
The API streams the JSON as text. The backend parses it as partial JSON (`jiter`, `partial_mode="trailing-strings"`) at most every ~50 ms and sends the partial card as an SSE `card` event. At the end it validates the card with Pydantic, registers the concept, stores the message and sends `done`.

### 5.4 Surprise me
Each pick combines two independent random choices:
- **Area** (what it's about): ~60 broad areas in `prompts/topic_areas.txt`: science and technology, but also
  work and institutions, money, culture and everyday life, places and the past. The last 10 used are skipped.
- **Angle** (what kind of question), weighted, from `prompts/spark_angles.txt`: how it works, a day in the life,
  behind the scenes, why it is so, a person and their turning point, a place, a custom, how it makes money,
  a craft, an open question, by the numbers. "How it works" is ~15% of the weight; the last 3 angles used are skipped.

`POST /api/spark` sends both to Haiku, which picks a subject you haven't met and frames a question
(`{concept, question, teaser, topic_area, angle}`, about $0.0002). The page starts a thread with `action=spark`,
`text=question` and the angle; the turn header carries `angle="…"`, and the card prompt adapts the fields to it
(e.g. day-in-the-life: the diagram is the shift's timeline). Area and angle are logged so both rotate. Questions
must name the subject, and myths or fringe claims are asked about as beliefs, never as facts.

**Skips steer the picks.** A spark counts as skipped when you ask for another one without having engaged with it
(no ask, dive, branch, switch, link or takeaway on its thread or concept), or when you press **Not interested →
another** on its card (a stronger signal). Each area and angle then gets a factor
`(1 + sparks kept) / (1 + skip penalty)` over the last 200 sparks (implicit skip 1, Not interested 2), clamped to
0.2–2, so a skipped kind of pick comes up less and a kept one more, but nothing is ruled out.

Measured on 30 real picks (2026-10-27): 9 of 11 angles and 21 areas appeared; 7 of 30 were "how it works".

---

## 6. Backend (FastAPI)

### 6.1 Endpoints
| Method | Path | Body / query | Returns |
|---|---|---|---|
| `GET` | `/` | — | the minimal page |
| `GET` | `/api/threads` | `?archived=false` | thread list |
| `POST` | `/api/threads` | `{text}` or `{spark: true}` | new thread |
| `GET` | `/api/threads/{id}` | — | thread + messages |
| `PATCH` | `/api/threads/{id}` | `{title?, depth?, archived?}` | thread |
| `POST` | `/api/threads/{id}/turns` | `{action, text?, concept?, depth?, takeaway_id?}` | **SSE stream** |
| `GET` | `/api/concepts` | `?q=` (prefix search for autocomplete) | concept list |
| `POST` | `/api/concepts` | `{name}` | concept (get-or-create) |
| `GET` | `/api/concepts/{id}` | — | concept + messages about it + links + takeaways |
| `POST` | `/api/links` | `{a_concept_id, b_concept_id, note}` | link |
| `PATCH` / `DELETE` | `/api/links/{id}` | `{note?}` | link / 204 |
| `GET` | `/api/takeaways` | `?concept_id=&kind=` | takeaways |
| `POST` | `/api/takeaways` | `{body, kind, concept_ids[], message_id?}` | takeaway |
| `PATCH` / `DELETE` | `/api/takeaways/{id}` | `{body?, kind?, concept_ids?}` | takeaway / 204 |
| `POST` | `/api/spark` | — | `{concept, question, teaser, topic_area, angle}` for Surprise me |
| `POST` | `/api/threads/{id}/not-interested` | — | 204; 404 if the thread didn't start from a spark |
| `GET` | `/api/health` | — | db + api-key status |

### 6.2 SSE protocol
```
event: meta   data: {"user_message_id": "...", "depth": "explain"}
event: status data: {"state": "thinking"}         (Claude is reasoning; deeper levels can take 10+ s)
event: card   data: {<partial card>}             (repeated)
event: done   data: {<final card>, "concept_id": "...", "usage": {...}}
event: error  data: {"code": "refusal|max_tokens|auth|rate_limited|overloaded|api_error|connection|invalid_card|internal", "message": "..."}
event: translation data: {"message_id": "...", "zh": {...}, "partial": true|false}   (after done; streamed, last one complete)
event: title  data: {"title": "..."}                (after a thread's first card only; generated by the light model)
```

### 6.3 Modules
```
apps/api/app/
├── main.py  settings.py  db.py  models.py  schemas.py
├── routes/     threads.py  turns.py  concepts.py  links.py  takeaways.py
├── services/   orchestrator.py  concepts.py  spark.py  titles.py  interest.py
├── llm/        client.py  card_schema.py  partial.py
└── static/     index.html  app.js  style.css          ← the disposable MVP UI
prompts/        system.md  topic_areas.txt
config/         profile.md   (gitignored; profile.example.md committed)
```

---

## 7. Database

```sql
create extension if not exists vector;    -- enabled now, used in P2

create table app_user (
  id uuid primary key default gen_random_uuid(),
  name text not null default 'me',
  created_at timestamptz not null default now()
);

-- Layer 1: exploration
create table thread (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_user(id),
  title text,
  root_concept_id uuid,                -- fk added below
  current_concept_id uuid,
  depth text not null default 'explain'
    check (depth in ('glance','explain','mechanism','expert')),
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  last_active_at timestamptz not null default now()
);

create table message (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references thread(id) on delete cascade,
  seq int not null,
  role text not null check (role in ('user','assistant')),
  action text,                         -- user: ask|dive|branch|switch|spark
  content text not null,               -- what the UI shows: user text, or card JSON
  card jsonb,
  api_content jsonb,                   -- exact content blocks sent/received, replayed verbatim (see §5.2)
  concept_id uuid,                     -- assistant: the card's concept
  model text, usage jsonb,
  created_at timestamptz not null default now(),
  unique (thread_id, seq)
);

-- Layer 2: concepts & links
create table concept (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_user(id),
  name text not null,
  slug text not null,                  -- lower-cased, normalized: dedupe key
  explored boolean not null default false,   -- false if created only as a link target
  created_at timestamptz not null default now(),
  unique (user_id, slug)
);

create table concept_link (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_user(id),
  a_concept_id uuid not null references concept(id) on delete cascade,
  b_concept_id uuid not null references concept(id) on delete cascade,
  note text not null default '',       -- "how they connect"
  created_by text not null default 'user',   -- 'ai' arrives in P2 (suggested, user-confirmed)
  created_at timestamptz not null default now(),
  check (a_concept_id < b_concept_id), -- undirected: store each pair once
  unique (a_concept_id, b_concept_id)
);

-- Layer 3: insights
create table takeaway (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_user(id),
  kind text not null check (kind in ('takeaway','idea','question')),
  body text not null,
  thread_id uuid references thread(id) on delete set null,
  message_id uuid references message(id) on delete set null,  -- the card it was written on
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table takeaway_concept (
  takeaway_id uuid references takeaway(id) on delete cascade,
  concept_id uuid references concept(id) on delete cascade,
  primary key (takeaway_id, concept_id)
);

create table interest_event (
  id bigserial primary key,
  user_id uuid not null references app_user(id),
  thread_id uuid references thread(id) on delete set null,
  concept_id uuid references concept(id) on delete set null,
  action text not null,   -- spark_shown|ask|dive|branch|switch|skip|depth_set|link|takeaway
  meta jsonb,
  ts timestamptz not null default now()
);
```
Every query filters by `user_id`, so multi-user later only needs auth.

---

## 8. Dev setup & tests
| Thing | Choice |
|---|---|
| Python | 3.12, **uv**, **ruff**, **pytest** + `pytest-asyncio` |
| DB | `pgvector/pgvector:pg17` via docker-compose, **Alembic** migrations |
| UI | static files served by FastAPI, no Node toolchain in the MVP |
| Run | `make dev`: compose up DB → alembic upgrade → `uvicorn --reload` on :8000 |
| Config | `.env`: `ANTHROPIC_API_KEY`, `DATABASE_URL`, `CHAT_MODEL`, `CHAT_EFFORT`, `LIGHT_MODEL` |

Tests: the partial-JSON parser, prompt assembly (including the injected links and takeaways), concept dedup and link pair ordering, and API endpoints with a **fake LLM client** replaying recorded streams (no API calls in tests). There's also a manual card-quality check on ~15 concepts (`evals/p0_cards.md`).

---

## 9. Build order
| Step | Deliverable | Check |
|---|---|---|
| **M0 Skeleton** | Repo layout, docker-compose, FastAPI `/health` + static page, Makefile, `.env.example` | `make dev` serves the page |
| **M1 Data** | All tables, migrations, seed user, thread/concept/link/takeaway CRUD | pytest passes; data survives restart |
| **M2 LLM turn** | Card schema, system prompt v1, orchestrator, SSE, partial parser, concept registration | `curl -N` streams a card; concept row created |
| **M3 Chat page** | Threads, streaming cards, branches, depth, composer | Done items 2, 3 |
| **M4 Your layer** | Concept panel, link form with autocomplete, takeaways, Ask, notes injected into prompt | Done items 4, 5 |
| **M5 Extras** | Surprise me, titles, interest events, error/retry | Done items 1, 6 |
| **M6 Tune** | Manual card eval, prompt iteration, model/effort decision | Average ≥ 4/5 on hook and example |

---

## 10. Decisions (say if you disagree)
1. **Concepts register automatically, links never do.** A concept is just a name, so creating it isn't "connecting the dots". Making the connection is your job in the MVP.
2. **Links are undirected, with a free-text note.** No relation types yet (part-of, causes…). We'll add them if your notes show recurring patterns.
3. **Takeaways can attach to several concepts.** An idea that bridges two concepts (e.g. AC + anomaly detection) belongs to both.
4. **Claude sees your links and takeaways for the current concept**, so it can answer "does that exist?" in context.
5. **Profile is a text file** in the MVP, so it needs no UI.
6. **Opus 5.5 at low effort** for cards (decided in M6: ~1 s to first text, half the cost; medium only wins on highlights), Haiku 5.5 for titles and sparks; refusal fallback on.
