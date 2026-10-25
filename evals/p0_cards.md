# P0 card-quality check (M6)

Harness: [apps/api/evals/run_cards.py](../apps/api/evals/run_cards.py). Each of 15 seed questions gets an
intro card at `explain`, then "Go deeper" at `mechanism`, replayed exactly as the app does. A blind Claude
Opus 5.5 judge (it doesn't know the effort level or prompt version) scores every card 1–5 on hook, example,
highlights, bridge and depth fit, and lists accuracy issues. Raw results live in `evals/results/` (gitignored).

```bash
cd apps/api
uv run python evals/run_cards.py run --effort low medium --label <name>   # ~$2, real API
uv run python evals/run_cards.py judge --label <name>                     # ~$1
uv run python evals/run_cards.py report --label baseline --label <name>
```

## Run 1: baseline prompt (2026-10-25)

Medians for timing/tokens; means for scores; `issues` = total accuracy flags across 15 cards.

| effort | turn | first text (s) | total (s) | output tok | thinking tok | hook | example | highlights | bridge | depth fit | issues |
|---|---|---|---|---|---|---|---|---|---|---|---|
| low | intro | 1.2 | 10.6 | 920 | 0 | 3.9 | 3.8 | 3.8 | 3.5 | 4.1 | 39 |
| low | dive | 1.1 | 18.0 | 1577 | 0 | 3.6 | 3.8 | 3.8 | 3.6 | 4.7 | 46 |
| medium | intro | 8.7 | 18.7 | 1704 | 683 | 4.0 | 4.1 | 4.5 | 4.2 | 4.1 | 29 |
| medium | dive | 14.0 | 29.8 | 2915 | 1218 | 3.6 | 4.2 | 4.2 | 4.1 | 4.9 | 42 |

**Speed:** `low` never thinks, so text appears in ~1 s and cards finish in roughly 60% of the time.
`medium` thinks for 700–1,200 tokens first, so nothing appears for 9–14 s.

**Quality:** `medium` is better where it matters most: highlights (+0.4 to +0.7), bridges (+0.5 to +0.7),
examples (+0.3), and fewer accuracy flags on intros (29 vs 39). The hook is the same at both levels.

**Spot check of the judge:** one flagged claim ("a 10% timing mismatch leaves the residual ~20 dB down") was
checked by hand. A 36° phase error leaves |1 − e^{i·36°}| ≈ 0.62, about −4 dB, so the judge was right.

### Patterns found (both efforts)
1. **Forced bridges.** 59 of 60 cards had one, despite the prompt allowing "". The weakest are vibe-level
   ("gluten is like model capacity", "the ice surface is like an edge case").
2. **Deeper cards' one-liners become jargon lists** ("cap, UTRs, poly-A, four-lipid particle…"), and deeper
   examples drift into lists of numbers instead of scenes. Dive hooks score 3.6 at both efforts.
3. **False precision and overstatement:** made-up-precise figures, contested findings stated as settled
   (glymphatic clearance during sleep), and cards that contradict themselves (a "boiling" example next to a
   body describing a pressurized reactor).

## Run 2: tuned prompt (pending)

`prompts/system.md` now has stricter rules: bridges only when the mapping is structural (expect about half
empty), a plain-language one-liner and a real scene at every depth, and a new Accuracy section (round numbers
and ranges, no overstated consensus, self-consistency, sanity-check calculations). This run **has not run
yet**: the API account ran out of credit before it started. Re-run with `--label tuned`, then compare.

## Decision so far
Keep `CHAT_EFFORT=medium` until the tuned run is in. If the tuned prompt closes most of the quality gap at
`low`, switch the default to `low` for the ~1 s first text.
