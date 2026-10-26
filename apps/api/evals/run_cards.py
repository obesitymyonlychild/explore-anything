"""P0 card-quality check (M6).

For each seed question: an intro card at `explain`, then "Go deeper" at `mechanism`, replayed
exactly like the app does. Records timings and tokens, then a blind judge scores every card.

    uv run python evals/run_cards.py run --effort low medium --label baseline
    uv run python evals/run_cards.py judge --label baseline
    uv run python evals/run_cards.py report --label baseline [--label tuned ...]

`run` and `judge` call the real API. Each prints a cost estimate and asks before spending (or pass
--yes), stops starting new work once --max-cost (default $5) is spent (calls already in flight still
finish, so it can overshoot by up to CONCURRENCY cards), and records every call in the
app's cost ledger as purpose eval/judge (these don't count toward the app's daily/monthly budgets).
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.llm.client import AnthropicCardLLM, Final, TextDelta, ThinkingStarted  # noqa: E402
from app.llm.pricing import cost_usd  # noqa: E402
from app.llm.prompt import system_blocks, user_turn  # noqa: E402
from app.schemas import Card  # noqa: E402
from app.services import budget  # noqa: E402
from app.settings import DEFAULT_USER_ID, REPO_ROOT, get_settings  # noqa: E402

RESULTS = REPO_ROOT / "evals" / "results"
CONCURRENCY = 4

# Typical cost per card / per judged card, from the M6 runs (evals/p0_cards.md). Used only for the
# up-front estimate; the guard itself uses real usage as calls finish.
EST_CARD_USD = {"low": {"intro": 0.03, "dive": 0.04}, "medium": {"intro": 0.045, "dive": 0.07}}
EST_CARD_USD_DEFAULT = {"intro": 0.08, "dive": 0.12}  # high/xhigh/max: unmeasured, assume more
EST_JUDGE_USD = 0.045


class CostGuard:
    """Tracks real spend as calls finish, records each in the ledger, and says when to stop."""

    def __init__(self, max_cost: float) -> None:
        self.max_cost = max_cost
        self.spent = 0.0
        self.ledger_ok = True

    @property
    def exceeded(self) -> bool:
        return self.spent >= self.max_cost

    async def add(self, purpose: str, model: str, usage: dict) -> None:
        self.spent += cost_usd(model, usage)
        if not self.ledger_ok:
            return
        try:
            async with SessionLocal() as session:
                budget.record(session, DEFAULT_USER_ID, purpose, model, usage)
                await session.commit()
        except Exception as e:  # noqa: BLE001 - the eval still runs without the DB
            self.ledger_ok = False
            print(f"  (cost ledger unavailable, continuing without it: {e.__class__.__name__})")


def confirm_spend(what: str, estimate: float, max_cost: float, yes: bool) -> None:
    print(f"{what}: estimated ~${estimate:.2f} (stops starting new work at ${max_cost:.2f}).")
    if estimate > max_cost:
        print("  The estimate is above --max-cost, so the run will stop partway. Raise --max-cost to finish it.")
    if yes:
        return
    if not sys.stdin.isatty():
        sys.exit("Refusing to spend without confirmation. Re-run with --yes.")
    if input("Continue? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled; nothing was spent.")


def estimate_run(efforts: list[str], n_questions: int) -> float:
    return n_questions * sum(sum(EST_CARD_USD.get(e, EST_CARD_USD_DEFAULT).values()) for e in efforts)


QUESTIONS = [
    "how do noise-cancelling headphones work?",
    "why is ice slippery?",
    "how do mRNA vaccines work?",
    "what happens when I tap my credit card at a shop?",
    "how does GPS know where I am?",
    "tides",
    "how do airplanes stay up?",
    "why does bread rise?",
    "how does a nuclear reactor make electricity?",
    "what is inflation and why does it happen?",
    "how do touchscreens detect my finger?",
    "how do bees tell each other where flowers are?",
    "what does sleep actually do for the brain?",
    "how do lithium-ion batteries work?",
    "how do container ports unload ships so fast?",
]


# --- run ---------------------------------------------------------------------


async def one_turn(llm: AnthropicCardLLM, system, history, guard: CostGuard) -> dict[str, Any]:
    t0 = time.monotonic()
    t_thinking = t_text = None
    text, final = "", None
    async for event in llm.stream_card(system, history):
        if isinstance(event, ThinkingStarted) and t_thinking is None:
            t_thinking = time.monotonic() - t0
        elif isinstance(event, TextDelta):
            if t_text is None:
                t_text = time.monotonic() - t0
            text += event.text
        elif isinstance(event, Final):
            final = event
    await guard.add("eval", final.model, final.usage)
    out = {
        "t_thinking": t_thinking,
        "t_first_text": t_text,
        "t_total": time.monotonic() - t0,
        "stop_reason": final.stop_reason,
        "usage": final.usage,
        "content": final.content,
        "text": text,
    }
    try:
        out["card"] = Card.model_validate_json(text).model_dump()
    except Exception as e:  # noqa: BLE001
        out["card"], out["error"] = None, f"invalid card: {e}"[:300]
    return out


async def run_question(effort: str, question: str, sem: asyncio.Semaphore, guard: CostGuard) -> list[dict[str, Any]]:
    settings = get_settings().model_copy(update={"chat_effort": effort})
    llm = AnthropicCardLLM()
    llm.settings = settings
    system = system_blocks()
    records = []
    async with sem:
        if guard.exceeded:
            return [{"effort": effort, "question": question, "turn": "intro", "error": "skipped: --max-cost reached"}]
        intro_msg = {"role": "user", "content": [{"type": "text", "text": user_turn("ask", "explain", None, question)}]}
        try:
            intro = await one_turn(llm, system, [intro_msg], guard)
        except anthropic.APIError as e:
            return [{"effort": effort, "question": question, "turn": "intro", "error": str(e)}]
        records.append({"effort": effort, "question": question, "turn": "intro", "depth": "explain", **intro})
        if not intro["card"]:
            return records
        if guard.exceeded:
            records.append(
                {"effort": effort, "question": question, "turn": "dive", "error": "skipped: --max-cost reached"}
            )
            return records
        concept = intro["card"]["concept"]
        dive_msg = {
            "role": "user",
            "content": [{"type": "text", "text": user_turn("dive", "mechanism", concept, "Go deeper.")}],
        }
        history = [intro_msg, {"role": "assistant", "content": intro["content"]}, dive_msg]
        try:
            dive = await one_turn(llm, system, history, guard)
        except anthropic.APIError as e:
            records.append({"effort": effort, "question": question, "turn": "dive", "error": str(e)})
            return records
        records.append({"effort": effort, "question": question, "turn": "dive", "depth": "mechanism", **dive})
    print(f"  done: [{effort}] {question}", flush=True)
    return records


async def cmd_run(efforts: list[str], label: str, limit: int | None, max_cost: float, yes: bool) -> None:
    n = len(QUESTIONS[:limit])
    confirm_spend(f"{n} questions x {len(efforts)} effort(s)", estimate_run(efforts, n), max_cost, yes)
    guard = CostGuard(max_cost)
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{label}.jsonl"
    sem = asyncio.Semaphore(CONCURRENCY)
    jobs = [run_question(e, q, sem, guard) for e in efforts for q in QUESTIONS[:limit]]
    with path.open("w") as f:
        for coro in asyncio.as_completed(jobs):
            for rec in await coro:
                rec.pop("content", None)
                if rec.get("card"):
                    rec.pop("text", None)  # keep raw text only when the card didn't parse
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
    print(f"wrote {path}; spent ${guard.spent:.2f}" + (" (stopped at --max-cost)" if guard.exceeded else ""))


# --- judge -------------------------------------------------------------------

JUDGE_SYSTEM = """You grade "hook cards" from a learning app that explains unfamiliar concepts to a curious \
adult. The user's profile says they are strong in data science/statistics/ML and new to most other fields. \
Each card should make the concept click and make the user want to keep going.

Score each dimension from 1 (poor) to 5 (excellent). Be strict: a 5 is rare and earned.
- hook: Does the one_liner plus the start of the card make you want to read on? Plain, vivid, not generic.
- example: Is the example a concrete scene or experiment someone can picture or try, with real objects or \
numbers? A generic statement scores 1-2.
- highlights: Are they surprising, specific and (to your knowledge) true, without overlapping the example?
- bridge: Is the data-science/ML analogy genuinely illuminating and correct? Forced, decorative or \
misleading analogies score 1-2. An empty bridge scores 3 (neutral) unless an obvious great analogy was missed (2).
- depth_fit: Does the card match its depth (explain = plain terms; mechanism = real steps, key numbers, why \
each step is needed) and, for a deeper card, add new information rather than restating the intro?
- accuracy_issues: list factual errors or dubious claims you notice (empty list if none).
- notes: one or two sentences on the biggest weakness."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "integer"},
        "example": {"type": "integer"},
        "highlights": {"type": "integer"},
        "bridge": {"type": "integer"},
        "depth_fit": {"type": "integer"},
        "accuracy_issues": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["hook", "example", "highlights", "bridge", "depth_fit", "accuracy_issues", "notes"],
    "additionalProperties": False,
}
DIMENSIONS = ["hook", "example", "highlights", "bridge", "depth_fit"]


async def judge_one(client: anthropic.AsyncAnthropic, rec: dict, intro_card: dict | None, sem, guard: CostGuard):
    parts = [f"User's question: {rec['question']}", f"Card type: {rec['turn']} at depth {rec['depth']}"]
    if rec["turn"] == "dive" and intro_card:
        parts.append("The intro card that came before it:\n" + json.dumps(intro_card, ensure_ascii=False))
    parts.append("The card to grade:\n" + json.dumps(rec["card"], ensure_ascii=False))
    async with sem:
        if guard.exceeded:
            return None
        response = await client.messages.create(
            model="claude-opus-5-5",
            max_tokens=8000,
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        )
    await guard.add("judge", response.model, response.usage.model_dump(mode="json", exclude_none=True))
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


async def cmd_judge(label: str, max_cost: float, yes: bool) -> None:
    path = RESULTS / f"{label}.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    intros = {(r["effort"], r["question"]): r.get("card") for r in records if r["turn"] == "intro"}
    client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    sem = asyncio.Semaphore(6)
    todo = [r for r in records if r.get("card") and "scores" not in r]
    confirm_spend(f"judging {len(todo)} cards", len(todo) * EST_JUDGE_USD, max_cost, yes)
    guard = CostGuard(max_cost)
    results = await asyncio.gather(
        *(judge_one(client, r, intros.get((r["effort"], r["question"])), sem, guard) for r in todo)
    )
    judged = 0
    for rec, scores in zip(todo, results, strict=True):
        if scores is not None:
            rec["scores"] = scores
            judged += 1
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    stopped = " (stopped at --max-cost; re-run judge to finish)" if judged < len(todo) else ""
    print(f"judged {judged}/{len(todo)} cards in {path}; spent ${guard.spent:.2f}{stopped}")


# --- report ------------------------------------------------------------------


def summarize(records: list[dict], effort: str, turn: str) -> dict:
    rs = [r for r in records if r["effort"] == effort and r["turn"] == turn]
    ok = [r for r in rs if r.get("card")]
    scored = [r for r in ok if "scores" in r]

    def med(key):
        vals = [r[key] for r in ok if r.get(key) is not None]
        return statistics.median(vals) if vals else None

    row = {
        "n": len(rs),
        "valid": len(ok),
        "first_text_s": med("t_first_text"),
        "total_s": med("t_total"),
        "out_tokens": statistics.median([r["usage"]["output_tokens"] for r in ok]) if ok else None,
        "thinking_tokens": statistics.median(
            [r["usage"].get("output_tokens_details", {}).get("thinking_tokens", 0) for r in ok]
        )
        if ok
        else None,
    }
    for d in DIMENSIONS:
        row[d] = round(statistics.mean(r["scores"][d] for r in scored), 2) if scored else None
    row["issues"] = sum(len(r["scores"]["accuracy_issues"]) for r in scored)
    return row


def cmd_report(labels: list[str]) -> None:
    cols = ["n", "valid", "first_text_s", "total_s", "out_tokens", "thinking_tokens", *DIMENSIONS, "issues"]
    print("| run | effort | turn | " + " | ".join(cols) + " |")
    print("|" + "---|" * (len(cols) + 3))
    for label in labels:
        records = [json.loads(line) for line in (RESULTS / f"{label}.jsonl").read_text().splitlines()]
        for effort in sorted({r["effort"] for r in records}):
            for turn in ("intro", "dive"):
                row = summarize(records, effort, turn)
                cells = [f"{v:.1f}" if isinstance(v, float) else str(v) for v in (row[c] for c in cols)]
                print(f"| {label} | {effort} | {turn} | " + " | ".join(cells) + " |")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--effort", nargs="+", default=["medium"])
    run.add_argument("--label", required=True)
    run.add_argument("--limit", type=int, help="only the first N questions (smoke test)")
    judge = sub.add_parser("judge")
    judge.add_argument("--label", required=True)
    for p in (run, judge):
        p.add_argument("--max-cost", type=float, default=5.0, help="stop starting new calls after this many USD")
        p.add_argument("--yes", action="store_true", help="don't ask before spending")
    report = sub.add_parser("report")
    report.add_argument("--label", action="append", required=True)
    args = parser.parse_args()

    if args.cmd == "run":
        asyncio.run(cmd_run(args.effort, args.label, args.limit, args.max_cost, args.yes))
    elif args.cmd == "judge":
        asyncio.run(cmd_judge(args.label, args.max_cost, args.yes))
    else:
        cmd_report(args.label)


if __name__ == "__main__":
    main()
