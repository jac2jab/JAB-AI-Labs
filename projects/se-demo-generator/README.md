# SE Demo Generator

Turns raw discovery notes into a deal-ready demo plan: recommended demo flow,
executive and technical talk tracks, competitive positioning, and the questions
that advance the deal.

Built from thirty years of sales engineering, on the observation that the
expensive part of demo prep is not writing the document — it is knowing which
five minutes of the product to show *this* customer, and why.

---

## Status

| Stage | State |
|---|---|
| **1 — Extraction** (notes → structured opportunity profile) | Validated May 2026, running |
| **2 — Generation** (profile + vendor pack → demo plan) | Running as of Aug 2026 |
| **Vendor packs** | Schema and tooling built; **content not yet written** |

The pack content is the part that matters and the part that cannot be
generated — see below.

## Run it

```powershell
python generate_demo_plan.py --notes data/sample_discovery_notes.md --vendor trend-micro
```

Needs a model. Local is the default, because discovery notes contain customer
names, budgets, and competitive intelligence:

```powershell
ollama pull llama3.2          # local — MAIOS Principle 1, private by default
# or: pip install anthropic + set ANTHROPIC_API_KEY
```

There is deliberately **no offline fallback**. The Daily Brief can degrade to
an extractive summary and stay useful; a demo plan generated without a model
would be a template with the customer's name pasted in, which is worse than an
honest failure.

## Why two stages

Extraction and generation are separate calls because they fail differently.
Extraction failing means the discovery notes were thin. Generation failing
usually means the **vendor pack** was thin. One combined call hides which, and
the whole point is knowing where to go fix it.

Generation itself runs as three grouped calls rather than one. A single request
for all seven sections is roughly 1,500 words, which on a CPU-bound local model
exceeded a five-minute timeout and discarded the extraction that had already
succeeded. Grouping bounds each call, shows progress, and lets a partial plan
still reach the user with the missing parts named.

```
discovery notes
      |
      v
[ 1. EXTRACT ]  ---> opportunity profile (JSON)
      |               account, pains, stakeholders, competitors,
      |               budget/timeline signals, compelling event,
      |               inferences, missing information
      v
[ 2. GENERATE ] <--- vendor pack + generic SE playbook
      |
      v
demo plan (Markdown)
```

## Vendor packs are the moat

The generation layer is a commodity. Any SE can paste notes into a chatbot and
get a competent summary — and a technical, curious SE absolutely will. Prompts
are not defensible.

What an individual SE will *not* do is curate and maintain, across a team, the
demo flows that actually win, honest competitive positioning, pain-to-capability
mapping, and POC success criteria. That is organizational knowledge, it decays
without an owner, and it walks out the door when a senior SE leaves.

```powershell
python new_pack.py fortinet
```

Every section scaffolds with **the question it exists to answer**, not as a
blank file. Sections still carrying the `<!-- UNWRITTEN -->` marker are skipped
rather than sent to the model — template questions in a prompt get answered as
though they were content, which produces confident nonsense.

See [`vendor_packs/README.md`](vendor_packs/README.md) for what makes a pack
good. **`demo_flows.md` first** — highest value, hardest to reproduce.

## Known limitations

- **The packs are empty.** The schema, tooling, and completeness reporting are
  built; no vendor knowledge is written yet. Output quality is bounded by that,
  and the generated plan says so at the top when a pack is incomplete.
- **The model invents specifics when the pack is empty, and does not admit it.**
  With a 0% pack the current sample output claims "reduce your alert volume by
  80%", offers "$X per year" in savings, and describes an architecture nobody
  supplied. The system prompt instructs it to report shortfalls under `Gaps`
  instead of inventing; it listed competitor pricing questions there instead.

  Prompt-level honesty instructions are not a control. The thing that does
  work is the completeness banner at the top of every generated plan — it is
  computed from the pack in code, not requested from the model. Treat output
  from an incomplete pack as a structural draft, not as content.
- **Slow on a local model.** llama3.2 generates at roughly 4 tokens/second on
  CPU here. Extraction runs about 80 seconds and each generation group one to
  two minutes. A hosted model is far faster; the local default trades speed for
  privacy.
- **Output is capped** at 1,200 tokens per call (`SEDG_MAX_OUTPUT_TOKENS`).
  Ollama generates without limit by default, and a small model given an
  open-ended prose prompt can fall into a repetition loop that never emits a
  stop token — which hung one section group past a ten-minute timeout twice
  before the cap was added. A group that completes naturally uses around 400
  tokens, so the cap costs nothing in the normal case.
- **Ollama gets JSON mode, not the full schema.** Constraining decoding to the
  complete profile schema was tried first and was pathologically slow on
  llama3.2 — a single extraction did not finish inside ten minutes, against
  roughly ninety seconds unconstrained. Plain JSON mode fixes the failure that
  was actually occurring (malformed output); the caller normalizes the shape
  afterward. The Anthropic backend still receives the full schema.
- **No UI.** Command line only. A Streamlit front end is the obvious next step.
- **No evaluation.** There is no measurement of whether the generated plans are
  any good. Judging that needs real discovery notes and a written pack first.
