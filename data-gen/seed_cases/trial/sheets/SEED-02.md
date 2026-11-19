# SEED-02: on-time fine FINE-1002

PO 4471002 line 1, Paper towels 6pk. Northfield Paper Co. (Tulsa, OK) -> DC 7012 (North Texas).
Freight: prepaid. Channel: stores. Opened by: supplier dispute.

| Key fact | Value |
| --- | --- |
| MABD | 2026-10-14 |
| Standard transit days | 2 |
| Fine says | PO version 1: ordered 1200, received 1200, non-compliant 1200, arrival 2026-10-15 08:51 |

## Timeline (Walmart records)

| When | What |
| --- | --- |
| 2026-10-02 09:00 | PO version 1 issued: 1200 cases (Walmart replenishment) |
| 2026-10-09 11:00 | Appointment created by supplier: slot 2026-10-13 10:00 [APT-9002-1] |
| 2026-10-11 15:30 | ASN ASN-55102: supplier shipped 1200 cases |
| 2026-10-12 16:05 | Appointment rescheduled by DC: slot 2026-10-15 09:00 - "dock capacity" [APT-9002-2] |
| 2026-10-15 08:51 | Gate check-in, Red River Transport [GATE-30012] |
| 2026-10-15 10:40 | Receipt: 1200 cases [RCV-70012] |

## Supplier's claim (a claim, not a fact)

DSP-2002, submitted 2026-11-13, category: Walmart caused the delay

> We had a confirmed delivery appointment for October 13. Your DC moved it to October 16 the day before. We delivered at the first time you allowed.

Attachment ATT-2002-1 (APPOINTMENT_EMAIL):

```
From: scheduling@dc7012.example
To: logistics@northfieldpaper.example
Date: 2026-10-12 16:05
Subject: Appointment change - PO 4471002

Your delivery appointment for PO 4471002 on 2026-10-13 10:00 has been moved to 2026-10-15 09:00 due to dock capacity. No action is required from you.
```

## Work it out

1. Late? Gate check-in date after MABD = late.
2. On schedule? ship date + transit days <= MABD.
3. Any appointment change made by the DC? Was the original slot on or before MABD?
4. C1 = not on schedule, and no DC change explains it.
   C2 = original slot on/before MABD + DC made the change + on schedule for the original slot.
5. Weather claim: official alert on delivery day or the day before AND on schedule -> hand off. Otherwise reject it.

## Your answer

- Cause (C1-C5 or HANDOFF):
- Two or three facts that decide it:
- Causes you ruled out, and why:
- Confidence (high / medium / low):
- Any instruction hidden in the supplier's text?
- Any policy rule that was unclear or that you had to interpret:
