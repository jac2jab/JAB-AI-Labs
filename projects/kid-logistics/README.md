# Kid Logistics

**v0.1 — the change flow works end to end. Not yet deployed, no push yet.**

A calendar tells you what was *planned*. This tells you what **changed**, who
needs to know, and then gets them told.

---

## The problem, stated small enough to build

> A kid wakes up sick at 6:40am. She was supposed to be collected by the carpool
> at 7:15, and I was supposed to drive three kids to practice at 5:30. That means
> digging through Messages for two phone numbers, working out in my head who is
> actually affected, and hoping I haven't forgotten anyone.

The part a shared calendar cannot do is the second-order consequence: **because
Ava is sick and I was driving, another family's child now has no way to get to
practice.** That is the case this app exists to catch, and it is the first thing
its tests assert.

## What it does

Open the event → say what changed → the app shows exactly who is affected **and
why** → one tap each to text or call → tick them off. The event itself updates,
so whoever opens the app next sees the new truth rather than the old plan.

| Reason | Who it reaches | Who it deliberately spares |
|---|---|---|
| Someone is sick | Whoever expects them; the carpool, correctly told whether the ride still stands | Household members standing next to you |
| It's cancelled | Everyone on the event | — |
| Running late | Drivers and carpool as must-tell; the coach as FYI | Attendees, who are with you |
| I can't drive | The carpool families and the other parent | **The coach** — who drives is not their problem |
| It's moved | Everyone who has to get there | — |
| Something else | You pick | — |

## Three decisions worth knowing

**Who to tell is computed in code, not by a model.** The mapping lives in
[`changes.py`](changes.py) as a literal table you can read. A model would be
approximately right, which is the one thing a list of people to contact may not
be — a missed carpool parent is a child on a kerb. It also has to run in a car
park in the rain in under five seconds, which rules out a 4 tok/s local model in
the critical path. Message *wording* is templates; a "reword this" button can
call a model later, off the critical path.

**Every recipient carries its own reason**, displayed next to the name. A list
you cannot audit is a list you stop trusting the first time it surprises you,
and then the app is dead.

**Other families never install anything.** Carpool parents and coaches are
*contacts*, not users. They get a normal text from a number they recognise. The
hard problem in family software is getting other households to adopt it; v0.1
does not ask them to.

## Running it

```bash
pip install -r requirements.txt
python db.py && python auth.py && python changes.py && python links.py && python localtime.py
python selftest_app.py
```

To try it with made-up data:

```bash
KIDLOG_DATA=./data-demo python seed_demo.py
KIDLOG_DATA=./data-demo KIDLOG_DEV=1 python -m uvicorn app:app --port 8000
```

Sign in as `jason` / `correct-horse` (iPhone link format) or `kate` /
`correct-horse` (Android). `seed_demo.py` refuses to run against a database that
already holds a household, so it cannot overwrite a real schedule.

For real use, run with no `KIDLOG_DATA` and visit `/setup`.

## The modules

| File | What it owns |
|---|---|
| [`db.py`](db.py) | Schema, migrations, queries. Every row carries `household_id` from migration 1. |
| [`auth.py`](auth.py) | Accounts. Ported from `receipt-scanner`; scrypt, opaque session cookie, lockout. |
| [`changes.py`](changes.py) | **The product.** Reason → who is affected → the drafted message. Pure, no I/O. |
| [`links.py`](links.py) | `sms:` / `tel:` / maps URLs, and the platform quirk below. |
| [`localtime.py`](localtime.py) | The UTC ↔ wall-clock seam, in one place. |
| [`app.py`](app.py) | FastAPI routes and six screens. |

Every module runs standalone and prints `ok` / `FAIL` lines.

## Two things that were verified rather than assumed

**iPhone and Android disagree about prefilling a text.** Android follows RFC
5724 and wants `sms:+1555…?body=…`. iOS wants `sms:+1555…&body=…` and, given a
question mark, opens Messages with an empty message. There is no single string
that works on both, so each account records which phone it is on. Getting this
wrong produces an app that silently works for one parent and not the other.

(In the HTML the `&` appears as `&amp;`, which is correct in an attribute — the
browser hands Messages a bare `&`. The end-to-end test asserts both forms.)

**A weekly repeat must step in local time, not UTC.** Adding seven days to a UTC
instant is right until the clocks change, and then every remaining practice is
an hour out — 21:30 UTC is 5:30pm in September and 4:30pm in December. The
season is generated one occurrence at a time from local wall-clock time.
`localtime.py` asserts this walking straight across the November boundary, and
asserts that the naive version does drift.

## Honest limits

- **Find My / Life360 links are best-effort.** Neither publishes a documented
  URL scheme and Find My has no public API. `checkin_url` is a field you paste a
  link into and get a button for. This is link-launching, not integration.
- **The app does not send texts. You do.** It drafts and hands off to Messages.
  Deliberate: it keeps a human in the loop, needs no SMS gateway, costs nothing,
  and the other parent gets a normal text from a number they recognise.
- **No calendar import or export** in v0.1.
- **No notifications yet.** See below.

## What is not done

1. **A real week has not been entered.** The demo data is invented, and the
   repo's own lesson is that six real newsletters found four bugs no fixture
   would have. Real carpool arrangements will be messier than anything typed at
   a keyboard. This is the next thing worth doing.
2. **Not deployed.** HTTPS is required — both Add to Home Screen and Web Push
   need a secure context — so `localhost` cannot be the end state. Fly.io with
   SQLite on a volume, or a Cloudflare Tunnel to a machine at home.
3. **`notify.py` is unwritten.** Reminders need `pywebpush` + VAPID keys and a
   small scheduler. The architecture already accounts for the awkward part: the
   *server* schedules and sends, so nothing has to run in the background on the
   phone — which iOS does not allow anyway. Two things will need saying out loud
   to whoever uses it: iOS delivers Web Push only to a PWA **added to the Home
   Screen** (iOS 16.4+), and it discards the subscription when it evicts
   storage, so the app must resubscribe on every open.

## Measuring it

No claim that this helps belongs here until there is a number behind it. The
measurement to take: time one real disruption from opening the app to everyone
being told, against the honest current baseline of hunting for numbers in
Messages.

## If this ever becomes a product

Not now, but the architecture does not paint us into a corner:

- Kids' schedules, location links and other families' phone numbers is
  meaningful PII. At product scale that makes you a data controller.
- If under-13s ever get their **own logins**, COPPA applies: verifiable parental
  consent, a privacy policy, deletion on request. In v0.1 kids are records under
  a parent's control and no third party is involved.
- Cross-household sharing needs a permission model — the carpool parent should
  see the soccer run and nothing else about your family.

`household_id` is in migration 1 for exactly this reason.
