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

## Run 2: tuned prompt (2026-10-25)

`prompts/system.md` now has stricter rules: bridges only when the mapping is structural (expect about half
empty), a plain-language one-liner and a real scene at every depth, and an Accuracy section (round numbers and
ranges, no overstated consensus, self-consistency, sanity-check calculations). The prompt's bridge example
was moved off the eval set (thermostat, not headphones).

| effort | turn | first text (s) | total (s) | output tok | thinking tok | hook | example | highlights | bridge | depth fit | issues |
|---|---|---|---|---|---|---|---|---|---|---|---|
| low | intro | 1.2 | 9.4 | 813 | 0 | 3.9 | 4.0 | 3.7 | 3.6 | 4.2 | 32 |
| low | dive | 1.1 | 15.6 | 1387 | 0 | 4.0 | 3.9 | 3.7 | 3.9 | 4.6 | 30 |
| medium | intro | 9.8 | 17.3 | 1573 | 695 | 4.0 | 4.1 | 4.3 | 4.2 | 4.3 | 26 |
| medium | dive | 13.6 | 29.1 | 2819 | 1284 | 3.9 | 4.0 | 4.1 | 3.9 | 4.7 | 30 |

### Baseline → tuned

| | low | medium |
|---|---|---|
| Accuracy flags (30 cards) | 85 → **62** (−27%) | 71 → **56** (−21%) |
| Deeper-card hook | 3.6 → **4.0** | 3.6 → **3.9** |
| Cards with a bridge | 30/30 → 15/30 | 29/30 → 21/30 |
| Score of the bridges that remain | 3.5 → **4.7** | 4.2 → **4.5** |
| Deeper one-liner length (words, median) | 36 → 30 | 33 → 29 |
| Highlights | 3.8 → 3.7 | 4.4 → 4.2 |

The per-card `bridge` average barely moves because an empty bridge scores a neutral 3; the bridges that remain
are much better. Highlights dipped slightly, within judge noise for n=15.

### Low vs medium, with the tuned prompt
- **Speed:** low shows text after ~1 s vs 10–14 s, and finishes 45% sooner on deeper cards (16 s vs 29 s).
- **Cost:** low uses about half the output tokens (≈ $0.02 vs $0.04 per card).
- **Quality:** equal on hook, example and depth fit, and similar on accuracy (62 vs 56 flags).
  Medium keeps an edge on **highlights (+0.4 to +0.6)** and writes a bridge more often.

## Decision
- **Keep the tuned prompt.** It's better at both efforts, mainly on accuracy and deeper-card hooks.
- **Effort: `low`** (decided 2026-10-25): text after ~1 s, half the cost, with a small highlights gap.
  Set `CHAT_EFFORT=medium` in `.env` to switch back.
