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

## Solution areas, and how a flow gets chosen

A vendor is rarely one product, so `demo_flows.md` holds one flow per solution
area and the generator injects only the ones this opportunity calls for.
Injecting all eight buries the relevant one.

The labels are defined once, in `SOLUTION_AREAS` in `packs.py`. Use them
verbatim — they are also the vocabulary for `competitor_positioning.md`, so a
competitor written under `## CSPM` is loaded exactly when the CSPM flow is.

| Label | Mode | Posture/response counterpart |
|---|---|---|
| `EDR/XDR` | response | ASRM |
| `ASRM` | posture | EDR/XDR |
| `CSPM` | posture | Workload Security |
| `Workload Security` | response | CSPM |
| `Email Security` | response | _not decided_ |
| `Network Security` | response | _not decided_ |
| `DSPM` | posture | _not decided_ |
| `ISPM` | posture | _not decided_ |

**Mode** is the proactive/reactive split. Posture answers *"how do I stop being
surprised"*; response answers *"what happens when it lands"*. A plan carrying
only one of a pair leaves the customer's other question open, so the run names
a counterpart that was not selected rather than silently omitting it. It does
not add it — whether the demo should cover both is your call.

### Two mechanisms, because they fail differently

Each flow declares both:

```markdown
## Endpoint, server, EDR or XDR

**Solution area:** EDR/XDR
**Triggered by:** alert, endpoint, edr, triage, soc analyst, soc lead
```

**`Solution area`** is matched against a classifier that reads the whole
profile — pains, environment, who was in the room, the compelling event — and
picks from the eight labels above. That carries **recall**. A customer who says
*"our field techs' laptops go weeks without checking in"* never types a trigger
phrase, and the classifier still reaches EDR/XDR.

**`Triggered by`** is plain lowercased substring matching. That carries the
**floor**: an unambiguous string selects the flow whatever the classifier
decided, so a model having an off day cannot silently drop a flow the customer
explicitly asked for.

A flow is selected if **either** fires. Nothing matching falls back to the
whole file, so a poorly-labelled pack degrades to previous behaviour rather
than going silent.

### Writing triggers now that the classifier exists

They no longer have to be exhaustive. That was never achievable — the set of
things a customer might say does not close, and the first seven triggers
written for the Endpoint flow scored **0 of 7** against real notes, because
they were written the way an SE summarises a pain (*"too many alerts"*) and the
customer had said *"We get 400 alerts a day and triage maybe 40"*.

So triggers only have to be **correct**:

- **Short and unambiguous.** Matching is substring, so a bare `soc` fires on
  "social engineering", "SOC 2" and "associate". It was replaced with
  `soc analyst` and `soc lead`.
- **Long phrases essentially never match.** Anything approaching a sentence is
  the classifier's job now.
- **One unwrapped line.** The regex captures a single line, so a wrapped list
  silently truncates. Commas separate, so a quoted phrase containing a comma
  shreds.
- **Leave the rest to the classifier.** A trigger you are unsure about is
  better deleted than guessed — a wrong one fires whatever the classifier says.

---

## Maintenance

Packs rot. Products ship, competitors reposition, and a battlecard from two
years ago is worse than none because it is believed.

Set `last_reviewed` in `metadata.json` when you revise a pack. A pack nobody
owns will quietly become misinformation.
