# Sales Engineering Playbook (vendor-agnostic)

Loaded alongside every vendor pack. This is method, not product knowledge —
how a good SE works, independent of what they sell.

---

## What a demo is for

A demo is not a product tour. It is an argument that this specific customer's
specific problem is solved, made visually so the room believes it.

The test for any demo step: **if I removed this step, would the customer be
less convinced?** If not, cut it. Time in a demo is the scarcest resource in
the deal.

## Sequencing

Open with the customer's pain on screen, not with your architecture. The first
three minutes decide whether the room is watching or reading email.

Order steps by the customer's priority, not by the product's structure. A
product's menu order reflects how it was built; the demo should reflect what
the customer said hurts.

End on the moment that makes the decision obvious — the screen you want them
to remember when they discuss it after you leave.

## Talking to two audiences at once

Most rooms hold both an economic buyer and a technical evaluator, and they need
different things.

- **Economic buyer** — outcomes, risk, time, cost. They are asking "does this
  make my problem smaller?" They do not care how it works.
- **Technical evaluator** — mechanics, integration, failure modes. They are
  asking "will this actually work in my environment, and what breaks?"

Losing either loses the deal. The executive kills it on value; the engineer
kills it on credibility.

## Honesty as technique

Concede real gaps. An SE who admits a limitation is believed on everything
else; an SE who claims the product does everything is believed on nothing.

Say "I don't know, let me find out" rather than guessing. Technical evaluators
test this deliberately, and a confident wrong answer ends your credibility for
the rest of the cycle.

Never demo something you cannot reproduce. A demo that worked once and fails in
the POC costs more than the demo won.

## Discovery discipline

No compelling event, no deal. If nothing forces a decision by a date, you have
an interested conversation rather than a deal, and it will stall in procurement.

Distinguish the stated problem from the underlying one. "We need better
reporting" is often "I cannot defend my budget to the board."

Find who can say yes. Champions cannot buy; they can only advocate. Many deals
die because nobody asked who signs.

Write down what you did **not** learn. Gaps in discovery are the most
actionable output of a call — they are the next call's agenda.

## Proof of concept

Scope a POC to success criteria the customer agrees to **in writing, before it
starts**. An unscoped POC never ends; it just gradually stops.

Criteria must be measurable. "Improve security posture" cannot be passed or
failed. "Reduce mean time to triage below 20 minutes on this alert class" can.

Agree what happens when it passes. A POC without a defined exit converts to
another POC.

## What generalizes and what does not

This playbook applies everywhere. Everything specific — which flows land, how a
competitor is really positioned, what a POC must prove for this product — lives
in the vendor pack, because that is the knowledge that is hard to reproduce and
worth maintaining.
