# JAB AI Labs Changelog

## 2026-08-24 — Receipt Scanner v0.1: the model reports, the code decides

A receipt scanner built in Google AI Studio in 2026 never reached working state
and was parked. Rebuilt here as Python + FastAPI + SQLite + Claude vision, on
this machine, with the phone as its client.

**The design decision everything follows from.** A restaurant tip box holds
`10-`, or `-`, or `CASH`, or nothing. Those are conventions, not numbers, and a
model re-decides what they mean on every call. So the model is asked for one
thing — the characters physically in the box — and `amounts.py` decides what
they mean. Then arithmetic checks the handwriting: if `subtotal + tax + tip`
misses `total` by more than a cent the receipt is flagged, so a model that reads
`10-` as `100` is caught by the sum rather than at tax time. When the tip box
alone is illegible it is *derived* from the other three and the derivation is
shown.

### Added
- `amounts.py` — written-amount interpretation and reconciliation. 21 rules,
  each with its example
- `retention.py` — how long a receipt is kept. No warranty item, two years;
  warranty item, the term plus 90 days; lifetime, indefinitely. Retention is
  policy, so it is a table in code and not something the model is asked for
- `extract.py` — Claude vision via `messages.parse()` with a Pydantic schema, so
  the shape is enforced at the API boundary rather than requested in a prompt.
  Every money field returns as a *string*, verbatim. Also runs as a CLI, with
  `--compare` to put two models on the same receipts
- `db.py` — SQLite archive. Money as integer cents; FTS5 over transcripts, so a
  receipt is findable by a word printed on the paper
- `auth.py`, `images.py`, `pdf.py`, `app.py` — accounts, photo preparation,
  per-receipt searchable PDF, and the pages
- `selftest_app.py` — the whole loop end to end against real HTTP and real
  SQLite: 55 checks

### Fixed — defects carried over from the AI Studio original
- **Every failure became `setError("Failed to process document.")`**, discarding
  the exception. A Google outage and a bug in the app were indistinguishable,
  which is exactly where the original stalled. Each stage now reports its own
  failure with the real error and status code
- **Extraction ran before storage**, so an API failure lost the photograph too.
  Inverted: the image is stored and the row created first, and a failed reading
  leaves the receipt queued with the image safe. The paper can go in the bin the
  moment the upload completes
- **`purgeOldDocs` deleted everything older than two years**, ignoring both
  `retention` and `isWarranty` — it would have destroyed a ten-year-warranty
  receipt, the exact document the app exists to keep. Cleanup now offers only
  receipts past their own retention date
- **`doc.amount.toFixed(2)` ran on unvalidated model output**, so one null field
  blanked the library. Fields are Pydantic-validated; an unread receipt renders
  as `—`
- **`handleShare` wrote an email into your own user document** while documents
  were only ever read from `users/{uid}/documents`, so sharing did nothing

### Found while building
- `db.connect(path=DB_PATH)` bound the default at import, so reassigning
  `db.DB_PATH` silently had no effect — the first self-test wrote into the real
  archive. Resolved at call time now, with `PIXELSCAN_DATA` as the supported
  override
- `hashlib.scrypt` at `n=2**15, r=8` needs exactly OpenSSL's default 32MB
  ceiling and refuses without an explicit `maxmem`
- An `async` endpoint with a sync DB dependency opens the connection in the
  threadpool and uses it on the event loop — `check_same_thread=False`, with one
  connection per request

### Not yet measured
**Extraction accuracy on real receipts.** No API key on the machine and no
photographs yet. The README's accuracy table is deliberately empty, and the
synthetic receipts in `make_fixture.py` are explicitly excluded from it — they
test wiring, not reading.

## 2026-08-20 — MAIOS Daily Brief v0.5 (in progress): stories, not emails

v0.4.1 documented the problem: keyword relevance scoring is wrong on roundup
newsletters. Fixing it turned out to need a structural change first, and
running against real mail found something worse than the scoring bug.

**A newsletter is not one item.** The pipeline now splits each email into its
individual stories before anything else runs, so relevance and summarization
both operate on a single story's own text.

### Added
- `stories.py` — splits an email into its stories. Four structures, each found
  by running real mail and watching the previous one fail: markdown headings,
  Techpresso's emoji-led headlines before `LINK`, TLDR's upper-case headlines
  before a `(3 MINUTE READ) [7]` marker, and Superhuman's bold-numbered leads.
  Boundaries from every pattern are pooled rather than competing, because one
  newsletter can use two at once
- `relevance.py` — model-assisted relevance using Jason's own criterion: an item
  matters when it changes what he would build or what he would say to a
  customer. The model picks one of five categories and **never emits a score**;
  the arithmetic is a dict in code
- `embeddings.py` — local `nomic-embed-text`, for duplicates that share no
  vocabulary
- `duplicates.py` — two-stage duplicate detection: embeddings narrow 11,026
  possible pairs to a handful of candidates, then the model answers one narrow
  question per candidate — same event, yes or no. It returns a boolean, never a
  score
- `compare_scoring.py` — runs keyword and model scoring over the same stories
  and prints the disagreements, so "the model is better" is a measurement
- `--per-issue` — keep at most N stories from each newsletter issue, default 4

### Changed
- **The reading-reduction baseline is now the whole newsletter as it arrived.**
  `ingest.py` capped every body at 4,000 characters, so the 3,903 words behind
  v0.4.1's 98% claim was 58% short of the mail that actually landed. Bounding
  the model prompt is now the splitter's job, per story
- Relevance defaults to `llama3.1:8b` rather than the 3B `llama3.2`. Measured on
  six stories whose correct category is not in dispute: 5 of 6 against 3 of 6,
  with no regression on the two the smaller model already had right
- The brief names its relevance scorer, as it already named its summarizer, and
  reports in bold how many items fell back to keyword scoring

### Fixed — the most serious thing found in this project so far
- **A summary was written from a headline whose article had been discarded.**
  The v0.4.1 brief led with "Apple may pay publishers for Siri news … *if a
  proposed deal is approved, potentially altering how AI-powered virtual
  assistants are monetized*". The Apple story began at character 4,054, past the
  body cap. The only Apple text the model received was the table-of-contents
  line. The real article — a pay-as-you-go model against a nine-figure budget,
  per a Wall Street Journal report — was never in the prompt. That is
  fabrication in published output, and splitting is what fixes it

### Fixed — three instances of one pattern
A story absorbing text that is not its own, with the absorbed vocabulary then
driving a decision. Each was invisible until something downstream produced an
absurd result:
- The 4,000-character body cap discarded 58% of every roundup
- The last story in an email ran to the end of the file, so it swallowed the
  sponsor block, quick links, and footer. A story about police misuse of licence
  plate data scored 4/5 on `anthropic`, a word appearing only in an unrelated
  quick link in its tail
- A TLDR headline whose hard wrap fell inside its own marker —
  `(3 MINUTE\nREAD)` — was never seen as a boundary, so an mRNA cancer vaccine
  story absorbed a story about humanoid robots

### Enforced in code rather than asked of a model
Every one of these was tried as a prompt first and failed:
- **Advertising is labelled from above, not inside.** `FROM OUR PARTNERS` sits
  on the line before the heading it labels, so searching inside the block could
  never find it. One advert was headed `Secondary ad here`
- **Bullet lists are not stories.** Every feature list, table of contents, and
  link roundup carried 5 or more list items; the most any real story carried
  was 3
- **House promotion names its own publication.** A recurring section names its
  own newsletter and a story about someone else does not
- **Scores are computed, never generated.** A 3B model does not hold a
  calibrated 1–5 scale
- **Furniture is detected structurally.** Asked as a yes/no beside the relevance
  questions, the model's answers moved together: one prompt made everything
  furniture and nothing relevant, the next made everything relevant and nothing
  furniture

### Measured
- Corpus: **28 emails from 13 newsletters, 39,276 words → 149 stories**. 10 of
  13 senders split
- Keyword scoring keeps 5 of 25 stories; model scoring keeps 10. The keyword
  five still include a user-count story scoring 4/5 on the word `openai`, and
  still miss both Grok launches, an autonomous agent intrusion, and a remote
  hijack vulnerability
- Splitting alone took the Apple/Siri item from 5/5 on borrowed keywords to 3/5
  on its own text, where it is correctly dropped

### Corrected
- **`temperature=0` is not reproducible.** Two identical runs disagreed on two
  of 25 stories, because Ollama seeds each request randomly unless told
  otherwise. Every count reported before a fixed seed was added should have
  carried a margin. A fixed seed makes a rerun comparable; it does not make the
  judgment correct
- **A model was accused of fabricating.** The two-stage deduplication run merged
  an mRNA cancer vaccine story with one about humanoid robots, justified as
  "Both articles report on Unitree's humanoid", and this was written up as the
  model inventing a shared event. It was not. The mRNA story body contained the
  entire Unitree story because of the wrapped-marker bug above. The model read
  what it was given and answered correctly

### Known state
- **Deduplication is not wired in.** The two-stage mechanism is built and
  validated on four hand-picked pairs, but its precision measurement was taken
  on contaminated story bodies and is void. Re-measuring on the 149 correctly
  split stories is in progress
- **`ben's bites` and `NVIDIA Developer Relations` do not split.** ben's bites
  is conversational prose with no heading structure; the NVIDIA digest is 4,974
  words and is currently one story
- Relevance judgment is the only part of the pipeline not enforced in code, and
  it is the only part that is still sometimes wrong

## 2026-08-14 — SE Demo Generator: demo flows per solution area

The original schema assumed one product per vendor. Trend Micro is endpoint,
email, cloud workload, network, and attack-surface risk — five solution areas,
and which demo you run depends on what discovery surfaced. A single "the demo
flow" could not represent that.

### Changed
- `demo_flows.md` now holds **one flow per solution area**, each declaring
  `**Triggered by:**` — the discovery signals that make it the right flow —
  plus audience, setup, numbered steps, the closing moment, and known failure
  modes
- The template shows the block to copy per area, and says to finish one area
  before starting a second

### Added
- `parse_demo_flows()` and `select_demo_flows()` in `packs.py`. The generator
  matches trigger phrases against the extracted profile's stated pains,
  environment, and compelling event, and injects **only the flows that fire**.
  For a five-area vendor this is the difference between a relevant flow and
  four irrelevant ones burying it
- `load_pack()` takes optional signals and reports which areas were selected;
  the run prints them
- Falls back to the whole file when nothing matches, so poorly chosen triggers
  degrade to previous behaviour rather than producing an empty plan

Selection runs in code rather than asking the model to choose — the same
reasoning as section membership and the completeness banner.

Verified against the sample discovery notes: alert/triage/SOC signals select
Endpoint and XDR alone; a phishing signal selects Email Security; both together
select both; no match returns everything.

## 2026-08-14 — MAIOS Daily Brief v0.4.1

**First run against real mail.** Six newsletters downloaded from Gmail as
`.eml`: 3,903 words in, 74 words out, **98% reading reduction** in 59 seconds.

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
