# Discovery call — ABC Corp — 14 May 2026

Deliberately messy. Real discovery notes are written during the call, not after,
and the extraction stage has to cope with that. This is the constructed
enterprise-security scenario the extraction stage was validated against.

---

Call w/ ABC Corp, 45 min, 4 people on. Manufacturing, ~6,500 employees, HQ
Midwest + 3 plants + a lot of field techs.

Attendees:
- Dana R — Dir. Infrastructure Security (ran the call, most engaged)
- Marcus — SOC lead, quiet until we got to alert volume then had a lot to say
- Priya — Compliance / audit, joined late
- "Tom" — VP something, dropped after 15 min, didn't say much

Current state:
- Trend Micro on endpoint, been in ~5 yrs. Dana says "it works, nobody loves it"
- Renewal is Nov. THIS is the reason we're talking.
- Splunk for SIEM, some homegrown scripts gluing things together
- No EDR on the OT/plant side at all — this came up twice, seems sore

Pain (their words):
- "We get 400 alerts a day and triage maybe 40" — Marcus
- Onboarding a new SOC analyst takes ~3 months before they're useful
- Dana: "I can't tell my board whether we're better off than last year"
- Field techs' laptops go weeks without checking in. Nobody has a good answer.

Competitive:
- Evaluating CrowdStrike. Dana used it at a previous employer, liked it,
  flagged cost. Marcus seemed lukewarm.
- SentinelOne came up once, I don't think it's serious. Someone on Dana's team
  "did a POC a while back."

New thing — worth flagging:
Priya asked about AI agents. Not the usual "do you use AI" question. Their dev
group has started running coding agents with repo access, and she wants to know
who is accountable when an agent does something. She used the phrase "non-human
identity." No policy for this yet. Dana clearly hadn't thought about it and
asked her to send something after the call.

Compliance:
- Priya: annual audit, findings last year around access review evidence
- Something about a customer contract requiring 72-hr breach notification —
  didn't get details, need to follow up

Budget:
- Dana said budget is "approved for the renewal cycle" — did NOT give a number
- Implied they'd need a business case to go above renewal spend

Timeline:
- Nov renewal is the wall. Dana wants a decision by end of Sept to leave
  procurement time.

Next steps agreed:
- Send a technical overview to Marcus
- Dana wants to see the board-level reporting
- Priya sending over the AI agent question in writing

Open questions I didn't get to:
- Who actually signs? Tom? Dana's boss?
- What does the OT environment look like — is EDR even deployable there?
- Are they measuring MTTR today or is that aspirational?
