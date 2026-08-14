# Vendor Packs

**This is the moat.**

The generation layer is a commodity. Any sales engineer can paste discovery
notes into a chatbot and get a competent summary — and a technical, curious SE
absolutely will. Prompts are not defensible.

What an individual SE will *not* do is curate, maintain, and standardize the
knowledge below across a team. That is organizational work, it decays without
an owner, and it is exactly what walks out the door when a senior SE leaves.

A vendor pack is that knowledge, written down.

---

## What goes in one

```
vendor_packs/
├── generic/
│   └── se_playbook.md          # vendor-agnostic method, loaded with every pack
└── <vendor>/
    ├── metadata.json
    ├── product_capabilities.md
    ├── demo_flows.md            <- start here
    ├── competitor_positioning.md
    ├── discovery_questions.md
    ├── common_use_cases.md
    ├── objection_handling.md
    ├── customer_personas.md
    ├── poc_playbooks.md
    ├── deployment_patterns.md
    ├── implementation_gotchas.md
    └── api_examples.md
```

Create one:

```powershell
python new_pack.py fortinet
```

Every section is scaffolded with **the question it exists to answer**, not as a
blank file. Answer the questions, delete the `<!-- UNWRITTEN -->` marker, and
that section starts being used.

Sections still carrying the marker are **not sent to the model** — template
questions in a prompt get answered as though they were content, which produces
confident nonsense. An unwritten section is skipped and reported instead.

---

## What makes a pack good

**Write what wins deals, not what the documentation says.** Product docs
already exist and the vendor maintains them better than you will. The value
here is the part that is not written down anywhere:

- The demo sequence you actually run, and why each step earns its place
- Where a competitor is genuinely strong — an SE who claims a rival is weak
  everywhere gets caught out in the room
- The pain a customer says out loud, mapped to the capability that answers it
- What a POC has to prove, stated so it can be passed or failed
- What bites people after the deal closes

**`demo_flows.md` is the highest-value file.** Write it first. It is the
hardest for anyone else to reproduce and the most useful to the generator.

**Thin and true beats thick and padded.** An honest gap tells the SE what to go
find out. Filler tells them nothing and costs tokens on every run.

---

## Maintenance

Packs rot. Products ship, competitors reposition, and a battlecard from two
years ago is worse than none because it is believed.

Set `last_reviewed` in `metadata.json` when you revise a pack. A pack nobody
owns will quietly become misinformation.
