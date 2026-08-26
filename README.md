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
| [`maios-daily-brief`](projects/maios-daily-brief) | **v0.5 — in progress** | Splits newsletters into stories, scores each with a local model, and turns an inbox into one prioritized morning brief. |
| [`se-demo-generator`](projects/se-demo-generator) | **Running; packs empty** | Turns sales-engineering discovery notes into a demo plan, talk tracks, and competitive positioning |
| [`receipt-scanner`](projects/receipt-scanner) | **v0.1 — loop verified; reading not yet measured** | Photograph a receipt, read it with Claude, confirm the fields, keep the image as long as the purchase can matter |

### MAIOS Daily Brief — current state

The pipeline is `load → split → categorize + score → deduplicate → filter →
summarize → render`. Every stage reports how many items it removed, so the
roadmap's "reduce daily reading time by at least 80%" target is measured, not
assumed.

**A newsletter is not one item.** Splitting each email into its individual
stories is the change that makes the rest work: relevance and summarization now
both operate on a single story's own text rather than on eight stories sharing
one subject line.

```powershell
cd projects/maios-daily-brief
python generate_brief.py --source ./inbox/
```

Current run — the most recent two issues from every newsletter actually
subscribed to, scored by a local `llama3.1:8b` and summarized by `llama3.2`:

```
Emails in:           28     from 13 newsletters
Stories after split: 149    (10 of 13 senders split)
Duplicates merged:  -12
Below relevance:    -90
Beyond top 4/issue:  -9
Items out:           38
Words to read:       39,276 -> 843
Reading reduction:   98%  (target: 80%)
```

**The roadmap's target is reading time, so the metric counts words, not items.**
An inbox of long newsletters and a brief of one-line summaries are not
comparable by item count alone. The input is counted as it arrived, before
anything is split or dropped — see
[the corrected baseline](#first-run-against-real-mail-14-aug-2026) for why that
distinction matters.

**The relevance floor removes 90 items and the per-issue cap only 9.** That
split is the point: an earlier v0.5 run had those at 39 and 30, which meant
structure was filtering the brief and the scorer was not. Priority now carries
information — 33% of stories reach the top score, against 66% before the
capability category was split.

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

Relevance scoring and deduplication are **local only**, with no API fallback:

| Stage | Model | Falls back to |
|---|---|---|
| Relevance | `llama3.1:8b` | keyword matching, named in the brief |
| Duplicates | `nomic-embed-text` + `llama3.1:8b` | lexical overlap |

Mail contains real correspondence, so a stage that would send it off the
machine to work is a stage that does not run.

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

**v0.4.1** (14 Aug 2026) — three ingestion bugs that only real mail could
expose: stub `text/plain` parts, numeric HTML entities, and URLs crowding out
the article body. See [First run against real mail](#first-run-against-real-mail-14-aug-2026).

**v0.5** (20 Aug 2026, in progress) — newsletters split into individual
stories; model-assisted relevance scoring; local embeddings and two-stage
duplicate detection; the reading-reduction baseline corrected to the whole
newsletter as it arrived.

Sample output: [`daily_brief_2026-08-25_email-newsletters.md`](projects/maios-daily-brief/output/daily_brief_2026-08-25_email-newsletters.md)
— 28 real newsletters, split into stories, scored and deduplicated by local
models. Each item states the category that produced its priority, and the brief
names every model that touched it.

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

### First run against real mail (14 Aug 2026)

Six newsletters downloaded from Gmail as `.eml` — Techpresso, The Neuron,
Smarter with AI:

```
Items in:            6
Below relevance:    -3
Words to read:       3,903 -> 74
Reading reduction:   98%  (target: 80%)
```

> **This baseline was wrong, and v0.5 corrected it.** Those 3,903 words are the
> *truncated* input — `ingest.py` capped each body at 4,000 characters, so 58%
> of the mail that actually arrived was discarded before being counted. The six
> newsletters carry 9,201 words. The percentage happened to be conservative, but
> the denominator was measuring the pipeline's own truncation.

Real mail broke three things the synthetic fixture never could:

1. **`text/plain` is often a stub.** Techpresso ships 210 characters — *"You
   are reading a plain text version of this post, view it online at…"* —
   beside 102KB of HTML holding the actual article. Preferring plain text
   discarded the entire newsletter. Now the two are compared and the one
   carrying content wins.
2. **Numeric HTML entities survived.** The hand-written entity table knew
   `&nbsp;` but not `&#160;` or `&#8204;`, and newsletters pad the inbox
   preview with hundreds of zero-width joiners. Replaced with
   `html.unescape()` plus an invisible-character strip.
3. **URLs crowded out the article.** A single tracking link can exceed 200
   characters, and the body is capped at 4,000.

Fixing those took Techpresso from 29 usable words to 630.

### What v0.5 fixed, and how it was found

Real mail exposed a fabrication, not just a scoring bug. The v0.4.1 brief led
with:

> Apple may pay publishers for Siri news **if a proposed deal is approved,
> potentially altering how AI-powered virtual assistants are monetized.**

The Apple story began at character 4,054 of that newsletter — past the
4,000-character body cap. The only Apple text the summarizer received was the
**table-of-contents line**. The real article, which says Apple pitched a
pay-as-you-go model against a nine-figure budget per a *Wall Street Journal*
report, was never in the prompt. The bolded half was generated from a headline.

Three bugs of the same shape were found this way — a story absorbing text that
is not its own, and the absorbed vocabulary then driving a decision:

| Bug | Symptom |
|---|---|
| 4,000-character body cap | 58% of every roundup discarded, including the subject's own story |
| Last story ran to end of file | A police-surveillance story scored 4/5 on `anthropic`, from a quick link in its footer |
| A hard wrap inside a TLDR marker | An mRNA cancer vaccine story absorbed one about humanoid robots |

Each was invisible until something downstream produced an absurd result.

### Relevance is now a model's judgment, enforced in code

The model answers one question — which of five categories this story is — using
the criterion *does it change what I would build, or what I would say to a
customer?* It **never emits a score**. The arithmetic is a dict in code, so the
weighting is visible and changeable in one place.

Everything below was tried as a prompt instruction first, and each one failed
until it was moved into code:

- **Advertising is labelled from above, not inside.** `FROM OUR PARTNERS` sits
  on the line *before* the heading it labels, so searching inside the block
  never finds it. One advert was headed `Secondary ad here`
- **Bullet lists are not stories.** Every list roundup carried 5+ list items;
  the most any real story carried was 3
- **House promotion names its own publication**
- **Furniture is structural.** Asked as a yes/no beside the relevance
  questions, the model's answers moved together — one prompt made everything
  furniture and nothing relevant, the next the exact reverse

Measured against the same stories, keyword scoring keeps 5 and model scoring
keeps 10. The keyword five still include a user-count story scoring 4/5 on the
word `openai`, and still miss both Grok launches, an autonomous agent intrusion,
and a remote hijack vulnerability.

### The scoring flaw real mail exposed (v0.4.1)

Keyword scoring inverted its own job on this sample:

| Item | Decision | Reason given |
|---|---|---|
| Grok 4.6 is here to slash your agent bill | **dropped** | no keywords matched |
| ChatGPT Can Now Edit Your Videos | **dropped** | no keywords matched |
| Apple may pay publishers for Siri news | **kept, 5/5** | matched `openai`, `enterprise` |

Two causes. `chatgpt` and `grok` are not in the keyword list, and no hand-kept
list survives contact with a field that names a new model every month.
Separately, newsletters are roundups of eight stories, so a keyword in story
seven scores the whole email — which is how an Apple/Siri headline scored on
`openai`.

Summarization already uses a model; relevance does not. That is the gap.

### Known limitations

- **Deduplication is built but not wired in.** Lexical overlap is measurably
  exhausted: across the corpus the true duplicate (Techpresso and The Neuron
  both covering the Grok 4.6 launch) scored **0.250**, *below* an unrelated pair
  at **0.263**. No threshold separates them. Embeddings alone do not fix it
  either — same topic is not the same event, and an mRNA vaccine story and a
  robotics story scored 0.786 against the true pair's 0.793. The two-stage
  design — embeddings to narrow 11,026 pairs to a handful, then one narrow
  *same event, yes or no* per candidate — is built and being measured.
- **`ben's bites` and `NVIDIA Developer Relations` do not split.** ben's bites
  is conversational prose with no heading structure; the NVIDIA digest is 4,974
  words and remains one story.
- **Relevance judgment is the only stage not enforced in code**, and the only
  one still sometimes wrong. `llama3.1:8b` scores 5 of 6 on cases where the 3B
  model scored 3 of 6, but a Grok launch mixing benchmarks with adoption
  statistics still lands in business news.
- **A fixed seed is required for comparable runs.** `temperature=0` alone is
  not reproducible — Ollama seeds each request randomly unless told otherwise,
  and two identical runs disagreed on two of 25 stories.
- **Newsletter furniture is stripped heuristically.** URLs, image placeholders,
  and punctuation rules are removed by pattern. Tuned against six real
  newsletters from three senders — a wider sample will surface more.
- **Newsletter structure is heuristic.** Four splitting patterns, each written
  after watching real mail defeat the previous one. Ten of thirteen senders
  split; a wider sample will surface more.
- **Throughput is one model call per story.** Relevance scoring runs ~33s per
  story on `llama3.1:8b` locally, so 149 stories is roughly 45 minutes and a
  full deduplication pass adds another 40. Fine overnight; a large mailbox
  would need batching.

**Next**: finish deduplication, then `ben's bites` and the NVIDIA digest.

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
│   ├── maios-daily-brief/ MAIOS v0.5 — in progress
│   ├── se-demo-generator/ discovery notes → demo plan; vendor packs unwritten
│   └── receipt-scanner/   photograph a receipt, keep it as long as it matters
├── labs/                  short experiments
└── references/            source material and notes
```

---

## Background

Related applied AI work not yet migrated into this repository:

- **Local model experimentation** with Ollama (May 2026) — now the default
  backend for both projects above.

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
