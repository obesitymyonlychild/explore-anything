"""P0 card-quality check (M6).

For each seed question: an intro card at `explain`, then "Go deeper" at `mechanism`, replayed
exactly like the app does. Records timings and tokens, then a blind judge scores every card.

    uv run python evals/run_cards.py run --effort low medium --label baseline
    uv run python evals/run_cards.py judge --label baseline
    uv run python evals/run_cards.py report --label baseline [--label tuned ...]

Every `run` and `judge` calls the real API and costs money (a full run of 2 efforts is ~$2).
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

from app.llm.client import AnthropicCardLLM, Final, TextDelta, ThinkingStarted  # noqa: E402
from app.llm.prompt import system_blocks, user_turn  # noqa: E402
from app.schemas import Card  # noqa: E402
from app.settings import REPO_ROOT, get_settings  # noqa: E402

RESULTS = REPO_ROOT / "evals" / "results"
CONCURRENCY = 4

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


async def one_turn(llm: AnthropicCardLLM, system, history) -> dict[str, Any]:
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


async def run_question(effort: str, question: str, sem: asyncio.Semaphore) -> list[dict[str, Any]]:
    settings = get_settings().model_copy(update={"chat_effort": effort})
    llm = AnthropicCardLLM()
    llm.settings = settings
    system = system_blocks()
    records = []
    async with sem:
        intro_msg = {"role": "user", "content": [{"type": "text", "text": user_turn("ask", "explain", None, question)}]}
        try:
            intro = await one_turn(llm, system, [intro_msg])
        except anthropic.APIError as e:
            return [{"effort": effort, "question": question, "turn": "intro", "error": str(e)}]
        records.append({"effort": effort, "question": question, "turn": "intro", "depth": "explain", **intro})
        if not intro["card"]:
            return records
        concept = intro["card"]["concept"]
        dive_msg = {
            "role": "user",
            "content": [{"type": "text", "text": user_turn("dive", "mechanism", concept, "Go deeper.")}],
        }
        history = [intro_msg, {"role": "assistant", "content": intro["content"]}, dive_msg]
        try:
            dive = await one_turn(llm, system, history)
        except anthropic.APIError as e:
            records.append({"effort": effort, "question": question, "turn": "dive", "error": str(e)})
            return records
        records.append({"effort": effort, "question": question, "turn": "dive", "depth": "mechanism", **dive})
    print(f"  done: [{effort}] {question}", flush=True)
    return records


async def cmd_run(efforts: list[str], label: str, limit: int | None) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{label}.jsonl"
    sem = asyncio.Semaphore(CONCURRENCY)
    jobs = [run_question(e, q, sem) for e in efforts for q in QUESTIONS[:limit]]
    with path.open("w") as f:
        for coro in asyncio.as_completed(jobs):
            for rec in await coro:
                rec.pop("content", None)
                if rec.get("card"):
                    rec.pop("text", None)  # keep raw text only when the card didn't parse
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
    print(f"wrote {path}")


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


async def judge_one(client: anthropic.AsyncAnthropic, rec: dict, intro_card: dict | None, sem) -> dict:
    parts = [f"User's question: {rec['question']}", f"Card type: {rec['turn']} at depth {rec['depth']}"]
    if rec["turn"] == "dive" and intro_card:
        parts.append("The intro card that came before it:\n" + json.dumps(intro_card, ensure_ascii=False))
    parts.append("The card to grade:\n" + json.dumps(rec["card"], ensure_ascii=False))
    async with sem:
        response = await client.messages.create(
            model="claude-opus-5-5",
            max_tokens=8000,
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


async def cmd_judge(label: str) -> None:
    path = RESULTS / f"{label}.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    intros = {(r["effort"], r["question"]): r.get("card") for r in records if r["turn"] == "intro"}
    client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    sem = asyncio.Semaphore(6)
    todo = [r for r in records if r.get("card") and "scores" not in r]
    results = await asyncio.gather(*(judge_one(client, r, intros.get((r["effort"], r["question"])), sem) for r in todo))
    for rec, scores in zip(todo, results, strict=True):
        rec["scores"] = scores
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    print(f"judged {len(todo)} cards in {path}")


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
    report = sub.add_parser("report")
    report.add_argument("--label", action="append", required=True)
    args = parser.parse_args()

    if args.cmd == "run":
        asyncio.run(cmd_run(args.effort, args.label, args.limit))
    elif args.cmd == "judge":
        asyncio.run(cmd_judge(args.label))
    else:
        cmd_report(args.label)


if __name__ == "__main__":
    main()
