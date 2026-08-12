# JAB AI Labs

**Building practical AI systems, documenting the process, and publishing what works.**

JAB AI Labs is the working repository for my applied AI projects. Its main line of
work is **MAIOS** — *My AI Operating System*, pronounced "Myos" — a framework for
reducing information overload, automating repetitive work, and organizing private
knowledge.

I'm a customer-facing solutions engineer with 30 years in enterprise technology
(Trend Micro, Juniper Networks), currently building AI systems hands-on rather than
only reading about them. This repo is where that happens in public.

---

## MAIOS

**The problem.** Too much time goes into reading, sorting, and mentally processing
AI newsletters, career email, and other inbound information — most of which repeats
the same handful of stories.

**The approach.** Build small, working pieces that each solve one concrete problem,
and keep the user in the loop rather than replacing their judgment. See
[PRINCIPLES.md](PRINCIPLES.md) for the design rules, and [ROADMAP.md](ROADMAP.md)
for where this is going.

**First user.** Me. Every feature has to survive my own daily use before it's worth
anyone else's attention.

---

## Projects

| Project | Status | What it does |
|---|---|---|
| [`maios-daily-brief`](projects/maios-daily-brief) | **v0.2 — working** | Turns a stream of inbound email into one prioritized morning brief |

### MAIOS Daily Brief — current state

The pipeline is `load → categorize + score → deduplicate → filter → summarize →
render`. Every stage reports how many items it removed, so the roadmap's
"reduce daily reading time by at least 80%" target is measured, not assumed.

```powershell
cd projects/maios-daily-brief
python generate_brief.py
```

Current run against the 18-item fixture, summarized by a local `llama3.2`
(cold start, including model load):

```
Items in:            18
Duplicates merged:  -3
Below relevance:    -9
Items out:           6
Reduction:           67%  (target: 80%)
Summarizer:          ollama:llama3.2
```

### Summarization backends

Tried in order, so the program runs for anyone who clones it:

| Backend | Requires | Why this order |
|---|---|---|
| **Ollama** (local) | `ollama pull llama3.2` | MAIOS Principle 1 — private by default |
| **Anthropic API** | `pip install anthropic` + `ANTHROPIC_API_KEY` | Used when no local model is present |
| **Extractive fallback** | nothing | Truncates the first sentence — **not a real summary** |

The brief names the backend that produced its summaries, so fallback output is
never presented as model-generated.

### Version history

**v0.1** (29 Jul 2026) — load, filter, sort, group, generate.

**v0.2** (30 Jul 2026) — automatic categorization, priority scoring, whole-word
matching to eliminate false positives, and *explainable* scoring: every priority
decision reports the keywords that produced it.

**v0.3** (12 Aug 2026) — pluggable model-based summarization; deduplication;
a relevance floor that actually filters; stage-by-stage measurement.

Sample output: [`daily_brief_2026-08-12.md`](projects/maios-daily-brief/output/daily_brief_2026-08-12.md)

### What v0.3 fixed

- **Deduplication now exists** (ROADMAP criterion #2, previously zero lines).
  Near-duplicates are detected by content-word overlap and consolidated, and
  each merge explains itself — similarity score plus the shared terms. Real
  duplicates in the fixture score 0.52–0.65; unrelated AI stories score 0.12.
- **The relevance floor filters.** v0.2 set `MINIMUM_PRIORITY` to `3` — the same
  value every item starts at — so anything matching no keyword passed by
  default. It is now `4`. A personal note that used to reach the brief no
  longer does.
- **Summarization calls a model** where one is available, instead of returning
  the source text unchanged.
- **Reduction is measured** at every stage rather than claimed.

### Known limitations

- **Condensation is not yet demonstrated.** Summaries are genuinely abstractive
  — 0 of 6 are byte-identical to their source, where v0.2 was 6 of 6 — but the
  fixture's bodies are single sentences, so there is nothing to compress:
  average length goes 18 words in, 20 words out. The reduction above comes from
  deduplication and filtering, not from shortening. Real multi-paragraph
  newsletters are needed to show the summarizer earning its place.
- **Input is a fixture**, not a live mailbox. The 67% is measured, but measured
  against sample data — which is also why the point above is still open.
- **Deduplication is lexical**, not semantic. Two write-ups of the same story
  that share little vocabulary will not be caught. Embeddings are the next step.
- **Throughput is one model call per item**, ~5s each on a local model. Fine for
  a daily brief; it would need batching for a larger inbox.

**v0.4**: live inbox input — which also closes out the condensation question —
then semantic deduplication.

---

## Curriculum

A structured self-study track feeding the projects above. Module 01 is written;
the rest are scaffolded and being filled in as the corresponding project work
demands them.

| Module | Topic | Status |
|---|---|---|
| 01 | [AI Foundations](curriculum/module-01-ai-foundations) | Written |
| 02 | Ollama / local models | Scaffolded |
| 03 | Prompt engineering | Scaffolded |
| 04 | RAG | Scaffolded |
| 05 | AI agents | Scaffolded |
| 06 | MCP and tool calling | Scaffolded |

---

## Repository structure

```
JAB-AI-Labs/
├── README.md
├── PRINCIPLES.md          design rules for everything here
├── ROADMAP.md             vision and success criteria
├── CHANGELOG.md
├── curriculum/            self-study modules 01–06
├── projects/
│   └── maios-daily-brief/ MAIOS v0.2 — the active project
├── labs/                  short experiments
└── references/            source material and notes
```

---

## Background

Related applied AI work not yet migrated into this repository:

- **SE Demo Generator** — a multi-stage prompting workflow converting unstructured
  customer discovery notes into structured opportunity data. Proof of concept:
  the extraction stage was validated against a constructed enterprise-security
  scenario; the downstream generation stages are specified but not built.
- **Local model experimentation** with Ollama (May 2026).

## Credentials

**Eight AI credentials completed between November 2025 and August 2026**, self-funded
and continuous, beginning the month after my Trend Micro tenure ended.

| Completed | Credential | Issuer |
|---|---|---|
| Aug 2026 | Build Anything with AI — No Code Required | Vanderbilt University |
| Jun 2026 | AI Strategy and Governance | Wharton, UPenn |
| May 2026 | AI Applications in Marketing and Finance | Wharton, UPenn |
| Mar 2026 | RAG, AI Apps, and AI Agents for Cybersecurity and Networking | Pearson / Omar Santos |
| Feb 2026 | Google Prompting Essentials Specialization | Google |
| Feb 2026 | AI Fundamentals for Non-Data Scientists | Wharton, UPenn |
| Dec 2025 | Artificial Intelligence on Microsoft Azure | Microsoft |
| Nov 2025 | Google AI Essentials Specialization | Google |

The three Wharton courses are 3 of the 4 in the *AI For Business* specialization
(*AI Applications in People Management* outstanding), so it is not yet a completed
specialization.

---

Jason Brockman · Raleigh, NC ·
[LinkedIn](https://linkedin.com/in/jason-brockman-242194172)
