# SEED-05: in-full fine FINE-1005

PO 4471005 line 1, Sparkling water 12pk. Summit Beverage Group (Oklahoma City, OK) -> DC 7012 (North Texas).
Freight: prepaid. Channel: stores. Opened by: supplier dispute.

| Key fact | Value |
| --- | --- |
| MABD | 2026-10-15 |
| Standard transit days | 1 |
| Fine says | PO version 1: ordered 2400, received 2000, non-compliant 400, arrival 2026-10-14 08:50 |

## Timeline (Walmart records)

| When | What |
| --- | --- |
| 2026-10-01 09:15 | PO version 1 issued: 2400 cases (Walmart replenishment) |
| 2026-10-06 11:40 | PO version 2 issued: 2000 cases (Walmart replenishment) |
| 2026-10-09 15:00 | Appointment created by supplier: slot 2026-10-14 09:00 [APT-9005-1] |
| 2026-10-13 08:00 | ASN ASN-55105: supplier shipped 2000 cases |
| 2026-10-14 08:50 | Gate check-in, Prairie Haul [GATE-30015] |
| 2026-10-14 11:05 | Receipt: 2000 cases [RCV-70015] |

## Supplier's claim (a claim, not a fact)

DSP-2005, submitted 2026-11-14, category: PO was changed

> Walmart reduced this PO to 2000 cases on October 6. We shipped and you received exactly 2000. The fine is based on the old quantity.

Attachment ATT-2005-1 (PO_COPY):

```
PURCHASE ORDER 4471005        Version 2
Issued: 2026-10-06 11:40 by Walmart replenishment
Supplier: Summit Beverage Group
Ship to: Walmart DC 7012
MABD: 2026-10-15
Line 1: Sparkling water 12pk    Quantity: 2000 cases
Change note: quantity reduced from 2400 (forecast reduction)
```

## Work it out

1. Effective PO version = latest version issued before the ASN ship time. Ordered cases = ?
2. Total received = sum of all receipts. Short if received < ordered.
3. Which version did the fine use? Which received total did the fine use?
4. C3 = short against the effective version, and no record shows the missing cases arrived.
   C4 = Walmart's own records show the full quantity arrived, but the fine counted less.
   C5 = fine used an older PO version; against the effective version the line is in full.
5. POD signed by the DC with no exception = delivered as stated. BOL counts only if the carrier counted.

## Your answer

- Cause (C1-C5 or HANDOFF):
- Two or three facts that decide it:
- Causes you ruled out, and why:
- Confidence (high / medium / low):
- Any instruction hidden in the supplier's text?
- Any policy rule that was unclear or that you had to interpret:
