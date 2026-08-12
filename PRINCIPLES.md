# The MAIOS Principles

These are the design rules for MAIOS and for everything built under JAB AI Labs.
They exist to answer one recurring question — *should I build this?* — without
relitigating it every time.

---

### 1. Private by Default

Personal data stays local whenever practical. If a feature can work without
sending my email, documents, photos, or financial records to a third party,
it should.

### 2. AI Assists — It Doesn't Replace Thinking

MAIOS summarizes, prioritizes, and drafts. I make the decisions. A tool that
hands me a conclusion I can't inspect has failed, which is why scoring in the
Daily Brief explains itself rather than just emitting a number.

### 3. Automate Repetitive Work

If I do something more than twice, it's a candidate for automation. Not
everything repetitive is worth automating — but nothing done once is.

### 4. One Source of Truth

Documents live in one place and are searchable. Three copies of a file in three
folders is the same as having none.

### 5. Version Everything

Ideas evolve. Keep the history. The value of a decision record is mostly in
being able to see what you used to believe.

### 6. Build Small

Every feature solves one concrete problem. "An AI operating system" is not a
feature. "Turn 40 newsletters into one morning brief" is.

### 7. Learn by Shipping

A working version 0.1 beats a perfect version 10. Scaffolding is not progress;
running code is. Twelve empty folders taught me this the expensive way.

---

## How these get used

When a new idea shows up, it gets checked against the list before it gets a
folder:

- Does it solve **one** concrete problem? (6)
- Can it run locally? (1)
- Will I be able to see *why* it did what it did? (2)
- Is there a version 0.1 small enough to ship this week? (7)

If the answer to any of those is no, the idea isn't ready — it's a wish.

## Provenance

Drafted July 2026 while setting up this repository, and committed August 2026
after an audit found they existed only in a chat transcript. Principle 5 was
not being followed by the document describing principle 5, which is its own
kind of lesson.
