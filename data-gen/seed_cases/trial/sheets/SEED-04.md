# SEED-04: in-full fine FINE-1004

PO 4471004 line 1, Laundry detergent 4ct. Clearwater Home Products (Shreveport, LA) -> DC 7012 (North Texas).
Freight: prepaid. Channel: stores. Opened by: pre invoice scan.

| Key fact | Value |
| --- | --- |
| MABD | 2026-10-21 |
| Standard transit days | 1 |
| Fine says | PO version 1: ordered 1500, received 1380, non-compliant 120, arrival 2026-10-20 10:44 |

## Timeline (Walmart records)

| When | What |
| --- | --- |
| 2026-10-08 14:00 | PO version 1 issued: 1500 cases (Walmart replenishment) |
| 2026-10-16 09:40 | Appointment created by supplier: slot 2026-10-20 11:00 [APT-9004-1] |
| 2026-10-19 16:20 | ASN ASN-55104: supplier shipped 1500 cases |
| 2026-10-20 | Weather alert: WX-1020-NTX, North Texas, Dense fog advisory |
| 2026-10-20 10:44 | Gate check-in, Bayou Freightways [GATE-30014] |
| 2026-10-20 14:10 | Receipt: 1380 cases [RCV-70014] |
| 2026-10-22 09:30 | Receipt: 120 cases - Pallet located in staging lane 4. Same delivery, trailer BF-1182, 2026-10-20. [RCV-70019] |

## Supplier's claim (a claim, not a fact)

No dispute. This line was flagged by the pre-invoice scan.

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
