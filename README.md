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

Reads inbound email records, assigns each a category and a 1–5 priority score,
filters out low-relevance items, groups what's left by category, and writes a dated
Markdown brief with recommended next actions.

```powershell
cd projects/maios-daily-brief
python generate_brief.py
```

**v0.1** (29 Jul 2026) — load, filter, sort, group, generate.
**v0.2** (30 Jul 2026) — automatic categorization, priority scoring, whole-word
matching to eliminate false positives, and *explainable* scoring: every priority
decision reports the keywords that produced it.

Sample output: [`daily_brief_2026-07-30.md`](projects/maios-daily-brief/output/daily_brief_2026-07-30.md)

### Known limitations — the v0.3 backlog

Stated plainly, because knowing what a system *doesn't* do is part of engineering it:

- **Scoring is deterministic, not model-based.** v0.2 uses keyword and rule
  matching only — there is no LLM call in the pipeline yet.
- **Summarization is a pass-through.** `create_summary()` currently returns the
  source text unchanged. It reformats; it does not condense.
- **No deduplication.** When five newsletters cover the same story, the brief
  reports it five times. This is the highest-value gap.
- **Input is sample data.** The pipeline runs against a small JSON fixture, not a
  live mailbox, so the roadmap's "reduce reading time by 80%" target is not yet
  measurable.

**v0.3** closes these in order: model-based summarization → deduplication → live
inbox input → measurement instrumentation.

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
