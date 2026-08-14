# JAB AI Labs Roadmap

## Vision

JAB AI Labs develops MAIOS — My AI Operating System — as a practical framework for reducing information overload, automating repetitive work, organizing private knowledge, and building useful personal AI applications.

## First User

Jason is the first MAIOS user and test case.

## MAIOS v0.1 — AI Newsletter Brief

### Problem

AI newsletter overload makes it difficult to identify the most relevant news without spending significant time reading overlapping content.

### Outcome

Generate an automated, prioritized summary focused on:

- AI agents
- RAG
- MCP
- enterprise AI
- AI infrastructure
- local AI
- technical evangelism
- useful open-source tools

### Initial Tools

- Gmail
- Gemini
- GitHub
- VS Code

### Success Criteria

Status as of **v0.4, 13 August 2026** — measured, not asserted. See
[`projects/maios-daily-brief`](projects/maios-daily-brief).

| Criterion | Status |
|---|---|
| Relevant newsletters are identified automatically | Met — keyword categorization and scoring |
| Duplicate stories are consolidated | Met — overlap-coefficient clustering, each merge explained |
| Marketing noise is removed | Met — 9 of 18 fixture items filtered below the relevance floor |
| Important stories are prioritized | Met — 1–5 scoring, sorted, every score explains itself |
| **Daily reading time is reduced by at least 80%** | **Met — 92% measured (1,589 words in, 130 out)** |
| A concise morning briefing is produced | Met — model-generated summaries, dated Markdown output |

Open: input is a synthetic fixture rather than a live mailbox, and
deduplication is lexical rather than semantic.

## SE Demo Generator

A second line of work, from Jason's own domain rather than his inbox.

### Problem

Sales engineers spend 30–60 minutes preparing for each demo, and the quality
varies by who prepares it. The knowledge that makes a demo land — which flows
win, how a competitor is really positioned, what a POC must prove — lives in
senior SEs' heads and leaves when they do.

### Outcome

Discovery notes in, deal-ready demo plan out: recommended flow, executive and
technical talk tracks, competitive positioning, and the questions that advance
the deal.

### Position

The generation layer is a commodity — any SE can paste notes into a chatbot.
The defensible part is the **vendor pack**: curated, maintained SE knowledge
that an individual will not build and a team cannot afford to lose.

### Success Criteria

- Discovery notes are converted to a structured opportunity profile. **Met.**
- Facts stated by the customer are separated from inferences. **Met.**
- A demo plan is generated and grounded in vendor knowledge. **Met**, though
  bounded by pack content, which is not yet written.
- Vendor packs can be created, validated, and reported on for completeness. **Met.**
- At least one vendor pack is written well enough to produce a plan an SE would
  actually take into a meeting. **Not met — this is the next milestone.**
- Output quality is evaluated against real discovery notes. **Not started.**

## Future MAIOS Capabilities

- Local LLM through Ollama
- Open WebUI interface
- Private document knowledge base
- RAGFlow
- n8n automation
- Claude Code or Codex app development
- Digital document library
- Family photo archive
- Custom workout application