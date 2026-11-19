# SEED-01: on-time fine FINE-1001

PO 4471001 line 1, Canned tomatoes 12ct. Brightwell Foods (Houston, TX) -> DC 7012 (North Texas).
Freight: prepaid. Channel: stores. Opened by: supplier dispute.

| Key fact | Value |
| --- | --- |
| MABD | 2026-10-08 |
| Standard transit days | 2 |
| Fine says | PO version 1: ordered 800, received 800, non-compliant 800, arrival 2026-10-10 07:42 |

## Timeline (Walmart records)

| When | What |
| --- | --- |
| 2026-09-28 10:00 | PO version 1 issued: 800 cases (Walmart replenishment) |
| 2026-10-07 13:20 | Appointment created by supplier: slot 2026-10-10 08:00 - "first requested slot" [APT-9001-1] |
| 2026-10-08 09:10 | ASN ASN-55101: supplier shipped 800 cases |
| 2026-10-09 | Weather alert: WX-1009-NTX, North Texas, Severe thunderstorm watch |
| 2026-10-10 07:42 | Gate check-in, Gulf Line Freight [GATE-30011] |
| 2026-10-10 09:30 | Receipt: 800 cases [RCV-70011] |

## Supplier's claim (a claim, not a fact)

DSP-2001, submitted 2026-11-12, category: Outside supplier control

> Our truck was delayed by the severe storms across North Texas on October 9. This was outside our control and the fine should be waived in full.

Attachment ATT-2001-1 (BOL):

```
BILL OF LADING                         BOL# 77310-B
Ship from: Brightwell Foods, Houston, TX
Ship date: 2026-10-08
Ship to:   Walmart DC 7012
PO: 4471001
Carrier:   Gulf Line Freight
Cases: 800
Carrier signature: R. Salas   2026-10-08 09:05
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
