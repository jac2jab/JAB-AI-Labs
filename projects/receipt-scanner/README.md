# Receipt Scanner

**Photograph a receipt, throw the paper away, still have the receipt.**

A receipt is evidence of a purchase, and the evidence fades — thermal paper goes
blank in a drawer in about two years, which is roughly when you need it. This
photographs one, reads it with Claude, asks you to confirm what it read, and
keeps the image for as long as the purchase can still matter.

Runs on your own machine. Reachable from your phone on your own Wi-Fi.

```powershell
cd projects/receipt-scanner
pip install -r requirements.txt
python app.py
```

Then open `http://<this-machine's-lan-ip>:8000` on the phone.

---

## Status — honest version

| Part | State |
|---|---|
| Amount interpretation, retention policy, archive, accounts | **Verified.** 21 + 6 + 20 + 15 checks, all passing |
| The whole web loop — upload, queue, review, file, search, export, PDF, cleanup, access control | **Verified.** 55 end-to-end checks against real HTTP and real SQLite |
| **Extraction accuracy on real receipts** | **Not yet measured.** No API key on this machine and no photographs of real receipts. The table below is empty on purpose |

Everything except the model call has been run. The model call itself has been
exercised only against a stub. **Nothing here claims Claude reads receipts well,
because that has not been measured yet.**

```powershell
python amounts.py        # how a written amount is interpreted
python retention.py      # how long each receipt is kept
python db.py             # the archive
python auth.py           # accounts and sessions
python selftest_app.py   # the whole loop, end to end
```

### Extraction accuracy — to be filled in by measurement

| Receipt | Model | Fields correct | Wrong fields | Seconds | Cost |
|---|---|---|---|---|---|
| _pending real photographs_ | | | | | |

The method is fixed in advance so the result cannot be flattered: photograph a
thermal slip, a crumpled receipt, a restaurant slip with a handwritten tip, and
a big-box receipt with a warranty item; run each through `claude-opus-5` and
`claude-sonnet-5`; count fields correct out of fields present; name every field
that was wrong.

Synthetic receipts (`python make_fixture.py`) exist and are **not** used for
this number. They are crisp rendered text; the Daily Brief already learned what
fixtures miss — six real newsletters found four bugs that no amount of
fixture-writing had surfaced.

---

## The design decision that everything else follows from

**The model reports; the code decides.**

A restaurant tip box holds `10-`, or `-`, or `CASH`, or nothing. Those are not
numbers, they are conventions, and a model re-decides what they mean on every
call. So the model is asked for exactly one thing — the characters that are
physically in the box — and [`amounts.py`](amounts.py) decides what they mean:

```
10-      ->  $10.00     trailing dash read as .00
-        ->  $0.00      no tip charged to the card
CASH     ->  $0.00      tip left in cash
(blank)  ->  $0.00      nothing written
scribble ->  flagged    could not read
```

Then arithmetic checks the handwriting. If `subtotal + tax + tip` does not equal
`total` within a cent, the receipt is flagged and the review screen opens on the
offending field. A model that misreads `10-` as `100` is caught by the sum:

```
amounts do not add up: subtotal 42.00 + tax 3.36 + tip 100.00 = 145.36,
but total reads 55.36 (off by 90.00)
```

And when the tip box is genuinely illegible but the other three amounts are
readable, the tip is *derived* rather than guessed — `total - subtotal - tax`,
with the derivation stated on screen.

This is the repo's recurring lesson, applied on purpose rather than after being
burned: **enforce in code what you would otherwise ask a model to do.** The SE
Demo Generator relearned it four separate times.

---

## What the model is asked for, and what it is not

**Asked for:** the vendor, the date as printed, each amount *as characters*, the
last four card digits, a category from a closed list of 18, the line items, a
full transcript, whether the receipt contains a physical item that plausibly
carries a warranty — and which fields it could not read confidently.

**Not asked for:** how long to keep the receipt. That is policy, not perception,
and it lives in [`retention.py`](retention.py):

```
no warranty item  ->  2 years from the purchase date
warranty item     ->  the warranty term, plus 90 days
lifetime warranty ->  kept indefinitely
```

The 90 days exist because a claim filed on the last day of a warranty still
needs the receipt afterwards. Changing any of this is a one-line edit.

---

## Nothing is lost when the API is down

The order is **store, then read**:

1. The photograph is written to disk and a row is created, marked unread.
2. Extraction is attempted against a file that is already safe.
3. A failure records the real error and leaves the receipt queued.

So a missing key, a rate limit, and an outage all end in the same safe place —
the receipt is in the library marked `NEEDS EXTRACTION`, with `Process queue` to
retry when the API is back. **You can throw the paper away the moment the upload
completes**, regardless of whether the reading succeeded.

Away from the house, or with the PC switched off, the phone's own camera roll is
the queue: shoot receipts normally and upload several at once later. That is
more durable than a browser cache, which Android is free to evict.

---

## What the original did, and why this does it differently

Rebuilt from a React + Firebase + Gemini app written in Google AI Studio, which
never reached working state. Each row is a real defect in that `App.tsx`.

| In the original | Consequence | Here |
|---|---|---|
| Every failure became `setError("Failed to process document.")`; the exception was discarded | A Google outage and a bug in the app were indistinguishable — which is exactly where the project stalled | Each stage reports its own failure with the real error and status code |
| Extraction ran *before* storage | An API failure lost the photograph too | Store first, read second |
| Extracted data written straight to Firestore | A misread amount was only findable by opening the receipt | A review screen: the model proposes, you confirm |
| `purgeOldDocs` deleted everything older than 2 years, ignoring `retention` and `isWarranty` | Would delete a 10-year-warranty receipt — the document the app exists to keep | Cleanup offers only receipts past *their own* retention date |
| `doc.amount.toFixed(2)` on unvalidated model output | One null field blanks the library | Pydantic-validated at the API boundary; unread receipts render as `—` |
| `retention` was free text invented by the model | Unenforceable | A table in code |
| `handleShare` wrote an email into your own user document; documents were only ever read from `users/{uid}/documents` | Sharing did nothing | Accounts share one library; share = a PDF you can actually send |
| The file input's `value` was never reset | Picking the same photo twice did nothing | Server-side upload |

---

## Privacy

Receipt images, vendors, amounts, and card fragments stay on this machine —
MAIOS Principle 1. There is no cloud database and no third-party account.

**The one exception, stated plainly:** extraction sends the receipt image to the
Anthropic API. It carries the last four card digits, never a full card number,
and `_validate_last4()` truncates anything longer before it can reach the
database — a hard boundary, not a formatting preference.

The app binds to `0.0.0.0` so the phone can reach it, which means everything
else on the network can too. Hence the passcode. `data/` is gitignored; the
archive never goes near the public repo.

---

## Files

| | |
|---|---|
| [`amounts.py`](amounts.py) | Interpreting written amounts; reconciliation |
| [`retention.py`](retention.py) | How long each receipt is kept |
| [`extract.py`](extract.py) | Claude vision → validated fields. Also a CLI |
| [`db.py`](db.py) | SQLite archive; money as integer cents; FTS over transcripts |
| [`images.py`](images.py) | EXIF rotation, downscaling, JPEG, thumbnails |
| [`auth.py`](auth.py) | Local passcode accounts, scrypt, sessions |
| [`pdf.py`](pdf.py) | One receipt as a searchable PDF |
| [`app.py`](app.py) | Routes and pages |
| [`make_fixture.py`](make_fixture.py) | Synthetic receipts, for wiring only |
| [`selftest_app.py`](selftest_app.py) | The whole loop, end to end |

Read one receipt without starting the app:

```powershell
python extract.py samples/lowes.jpg
python extract.py "samples/*.jpg" --compare    # opus-5 against sonnet-5
```

---

## Setup

**An API key.** `ANTHROPIC_API_KEY`, or `ant auth login`. Without one the app
still runs — scans queue instead of failing, and Settings says so.

**A firewall rule**, or the phone cannot reach the server:

```powershell
New-NetFirewallRule -DisplayName "PixelScan Pro" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

**The machine's LAN address**, for the phone's browser:

```powershell
(Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp).IPAddress
```

`PIXELSCAN_DATA` moves the archive elsewhere — another disk, an encrypted
volume.

---

## Known limits

- **Extraction accuracy is unmeasured.** The table above is empty because no
  real receipt has been through it yet.
- **The PDF is searchable, not word-positioned.** True searchable scans place
  each word invisibly over its own spot in the image, which needs per-word
  bounding boxes a vision model does not return. Searching the PDF for a vendor
  or an amount works; clicking a word on the photograph does not select it.
- **Duplicate detection is exact-match** on vendor + date + total. Two identical
  coffees bought the same day will warn, wrongly.
- **HEIC needs `pillow-heif`.** Chrome's camera capture writes JPEG, but a photo
  picked from the gallery may not be. The error says so instead of failing
  obscurely.
- **No offline capture on the phone.** With the PC off, the camera roll is the
  queue. A service-worker queue is deliberately deferred until the simple answer
  proves insufficient.
- **Lockout state is in memory**, so restarting the app clears failed-attempt
  counters. Acceptable on a LAN; it avoids a disk write per failed guess.
- **Category is a closed list of 18.** A receipt that fits none becomes `Other`.
  Free-text categories from a model drift and make the column useless.
