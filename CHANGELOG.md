# JAB AI Labs Changelog

## 2026-08-14 — MAIOS Daily Brief v0.4.1

**First run against real mail.** Six newsletters downloaded from Gmail as
`.eml`: 3,903 words in, 70 words out, **98% reading reduction** in 59 seconds.

### Fixed — all three found only by using real email
- **`text/plain` is often a stub.** Techpresso ships 210 characters pointing at
  the web version beside 102KB of HTML holding the article. Preferring plain
  text silently discarded the whole newsletter. The two parts are now compared
  and the one carrying content is used — this took Techpresso from 29 usable
  words to 630
- **Numeric HTML entities survived stripping.** The hand-written table knew
  `&nbsp;` but not `&#160;` or `&#8204;`, and newsletters pad the inbox preview
  with hundreds of zero-width joiners. Replaced with `html.unescape()` and an
  invisible-character strip
- **URLs crowded out the article.** One tracking link can exceed 200 characters
  against a 4,000-character body cap. URLs, image placeholders, and punctuation
  rules are now stripped

### Found, not yet fixed
- **Keyword relevance scoring is wrong on roundup newsletters.** It dropped
  "Grok 4.6 is here to slash your agent bill" and "ChatGPT Can Now Edit Your
  Videos" for matching no keywords, while keeping an Apple/Siri story at 5/5 on
  `openai` and `enterprise` — words appearing elsewhere in a 630-word roundup.
  Two causes: a hand-kept vocabulary cannot track a field that names a new
  model monthly, and one keyword anywhere scores the entire email. Summarization
  uses a model; relevance does not. That is v0.5

## 2026-08-14 — SE Demo Generator scaffold

A second project, from Jason's own domain rather than his inbox. Discovery
notes in, demo plan out. The extraction stage was validated in May 2026; the
generation stage and the vendor pack system are new.

### Added
- `projects/se-demo-generator/` — two-stage pipeline, deliberately separated
  because the stages fail differently. Extraction failing means the notes were
  thin; generation failing usually means the vendor pack was thin
- `packs.py` — vendor pack schema, loading, and completeness reporting. Eleven
  sections plus metadata, defined once and used for scaffolding, validation,
  and loading so they cannot drift apart
- `new_pack.py` — scaffold a vendor pack. Every section is created carrying
  **the question it exists to answer**, not as a blank file
- `vendor_packs/generic/se_playbook.md` — vendor-agnostic SE method, loaded
  alongside every pack
- `llm.py` — local Ollama first, Anthropic second. No offline fallback: a demo
  plan generated without a model would be a template with the customer's name
  pasted in, which is worse than an honest failure
- `data/sample_discovery_notes.md` — the constructed enterprise-security
  scenario the extraction stage was validated against, written as messy
  in-call notes rather than a tidy summary
- `.gitignore` entries keeping real discovery notes and exported mail local

### Design decisions made under measurement
- **Ollama gets JSON mode, not the full schema.** Schema-constrained decoding
  was tried first and was pathologically slow on llama3.2 — a single extraction
  did not finish inside ten minutes, against roughly ninety seconds
  unconstrained. JSON mode fixes the failure that was actually occurring
  (intermittently malformed output); the caller normalizes the shape afterward.
  The Anthropic backend still receives the full schema
- **Generation runs as three grouped calls, not one.** A single request for all
  seven sections exceeded a five-minute timeout and discarded the extraction
  that had already succeeded. Grouping bounds each call, shows progress, and
  lets a partial plan reach the user with the missing parts named
- **Section membership is enforced in code.** The model does not reliably honour
  "produce exactly these sections and nothing else" — the first run emitted a
  Gaps section from two different groups. Each group now declares the headings
  it owns and anything else is discarded
- **Output is capped per call.** Ollama generates without limit by default, and
  a small model given an open-ended prose prompt can fall into a repetition
  loop that never emits a stop token. One section group hung past a ten-minute
  timeout twice before this was found; the same prompt with a token cap
  finished in 104 seconds and stopped naturally at 422 tokens. Measured
  throughput on llama3.2 here is about 4 tokens/second

### Known state
- **Vendor packs are empty.** Schema, tooling, and reporting are built; no
  vendor knowledge is written. Generated plans say so at the top, and with an
  empty pack the competitive positioning is visibly generic — which is the
  clearest available evidence for why the packs are the defensible part
- **Asking the model to admit gaps does not work.** With a 0% pack it invented
  an architecture, an 80% alert reduction, and a "$X per year" saving, while
  its `Gaps` section listed competitor pricing questions instead of the actual
  shortfall. The completeness banner — computed from the pack in code — is the
  control that holds. Same lesson as section membership: enforce, do not ask

## 2026-08-13 — MAIOS Daily Brief v0.4

**First version to meet the ROADMAP's "reduce daily reading time by at least
80%" target: 92% measured.**

### Added
- `ingest.py` — read real mail from `.eml` files, a directory of them, or a
  `.mbox` archive, alongside the JSON fixture. Standard library only: no
  password, no OAuth consent screen, no network (MAIOS Principle 1). Multipart
  messages prefer their plain-text part; HTML-only messages are stripped of
  tags, scripts, and entities
- `--source` argument for choosing the input
- Reading-time measured in **words**, not items. The roadmap's target is about
  time spent reading, and an inbox of long newsletters is not comparable to a
  brief of one-line summaries by item count
- The brief now records its own provenance — which source and which summarizer

### Changed
- Fixture bodies rewritten to realistic newsletter length (~88 words average,
  up from ~20), so condensation can actually be measured

### Fixed
- **Deduplication silently broke on realistic body lengths.** Jaccard
  similarity divides by the union, so it penalizes length mismatch: a 160-word
  article and a 70-word write-up of the same story scored 0.24 and merged
  nothing. Replaced with the overlap coefficient, which measures how much of
  the shorter item's vocabulary appears in the longer one. Separation between
  true and false duplicates widened from 0.094 to 0.185; threshold retuned
  from 0.45 to 0.35 against measurements rather than taste

### Measured
- Reading reduction: **92%** (target 80%) — 1,589 words in, 130 words out
- Item reduction: 67% — 3 duplicates consolidated, 9 below the relevance floor
- Verified end to end against real `.eml` files in plain-text, multipart, and
  HTML-only shapes, with no markup leaking into any body

## 2026-08-12 — MAIOS Daily Brief v0.3

### Added
- `summarizer.py` — pluggable summarization with three backends tried in order:
  local Ollama, the Anthropic API, then a clearly-labelled extractive fallback
  so the program runs for anyone who clones the repository
- `deduplicate.py` — explainable near-duplicate consolidation, closing ROADMAP
  success criterion #2, which previously had zero lines of implementation
- Stage-by-stage measurement: items in, duplicates merged, items filtered,
  items out, and the reduction percentage against the 80% target
- Expanded the fixture from 5 to 18 records, including genuine duplicate
  coverage of the same stories

### Fixed
- `MINIMUM_PRIORITY` raised from `3` to `4`. It had equalled the baseline score
  every item starts at, so anything matching no keyword passed by default
- `create_summary()` no longer returns the source body unchanged
- Raised the local-model request timeout from 60s to 180s. The first call also
  loads the model into memory, and on a cold start that exceeded the old
  timeout — silently degrading the entire brief to the fallback

### Measured
- Reduction against the fixture: **20% → 67%** (target 80%)
- Summaries byte-identical to their source: **6 of 6 → 0 of 6**, all produced by
  a local `llama3.2` via Ollama
- Full cold-start run, including model load: ~45s for 18 items

## 2026-08-12

### Added
- `PRINCIPLES.md` — the seven MAIOS design principles, drafted in July and
  previously existing only in a chat transcript
- README: project status, known limitations, v0.3 backlog, and credentials

### Changed
- Renamed throughout: "Jason AI Labs" → **JAB AI Labs**, "Jason OS" → **MAIOS**
- README now documents the repository as it actually is; removed five directories
  it described that had never been created
- `Jason_AI_Labs_Roadmap_v1_Outline.pdf` → `JAB_AI_Labs_Roadmap_v1_Outline.pdf`

### Removed
- Empty placeholder projects `jason-os`, `everpure-os`, `workout-ai`
  (recoverable from history if revived)

### Note
This changelog missed the v0.1 and v0.2 releases below; they are recorded here
retroactively from the commit history. Principle 5 is *version everything*.

## 2026-07-30

### Added — MAIOS Daily Brief v0.2
- Automatic email categorization
- Priority scoring, 1–5, with explainable keyword matches
- Whole-word matching to prevent false positives
- Relevance-based filtering

## 2026-07-29

### Added — MAIOS Daily Brief v0.1
- Load structured email records from JSON
- Filter, sort by priority, group by category
- Generate a dated Markdown brief with recommended next actions

## 2026-07-27

### Added
- Created GitHub repository
- Set up GitHub Desktop
- Installed and configured VS Code
- Created ROADMAP.md
- Established MAIOS vision and first project
