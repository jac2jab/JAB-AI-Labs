# JAB AI Labs Changelog

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
