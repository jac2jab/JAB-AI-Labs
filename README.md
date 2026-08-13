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

Current run against the 18-item fixture, summarized by a local `llama3.2`:

```
Items in:            18
Duplicates merged:  -3
Below relevance:    -9
Items out:           6
Item reduction:      67%
Words to read:       1,589 -> 130
Reading reduction:   92%  (target: 80%)
```

**The roadmap's target is reading time, so the metric counts words, not items.**
An inbox of long newsletters and a brief of one-line summaries are not
comparable by item count alone.

### Input sources

```powershell
python generate_brief.py                        # the JSON fixture
python generate_brief.py --source ./inbox/      # a directory of .eml files
python generate_brief.py --source mail.mbox     # a Gmail Takeout archive
```

Reading exported mail from disk needs no password, no OAuth consent screen, and
no network — MAIOS Principle 1, private by default. Mail is read locally,
summarized by a local model, and never leaves the machine. Multipart messages
prefer their plain-text part; HTML-only messages are stripped of tags, scripts,
and entities.

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

**v0.4** (13 Aug 2026) — real email ingestion (`.eml`, `.mbox`); reading-time
measured in words; a length-robust similarity metric. **First version to meet
the roadmap's 80% target.**

Sample output: [`daily_brief_2026-08-13.md`](projects/maios-daily-brief/output/daily_brief_2026-08-13.md)

### What v0.4 fixed

Feeding the pipeline realistic multi-paragraph bodies broke deduplication, and
the fix is the most interesting thing in this release.

**Jaccard similarity was the wrong metric.** It divides shared terms by the
*union*, so it penalizes length mismatch. A 160-word article and a 70-word
write-up of the same story scored **0.24** — below any threshold that also
excluded unrelated mail. Duplicate detection silently dropped to zero.

The **overlap coefficient** asks the question that actually matters for
newsletters: how much of the shorter item's vocabulary appears in the longer
one? Measured across the fixture:

| Metric | Worst true duplicate | Closest false pair | Margin |
|---|---|---|---|
| Jaccard | 0.238 | 0.144 | 0.094 |
| **Overlap coefficient** | **0.446** | **0.262** | **0.185** |

Nearly double the separation, so the threshold sits at 0.35 with room on both
sides — chosen by measuring, not by taste.

### Known limitations

- **Deduplication is lexical**, not semantic. Two write-ups of the same story
  that share little vocabulary still will not be caught. Embeddings are the
  next step.
- **The fixture is synthetic.** Bodies are now realistically long, but they are
  written, not captured. The `.eml` path is tested against generated messages
  covering plain-text, multipart, and HTML-only shapes — real newsletters will
  surface encodings these do not.
- **Throughput is one model call per item**, ~5s each locally. Fine for a daily
  brief; a large mailbox would need batching.
- **Scoring is still keyword-based.** Summarization uses a model; relevance
  does not.

**v0.5**: semantic deduplication via embeddings, and model-assisted scoring.

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
