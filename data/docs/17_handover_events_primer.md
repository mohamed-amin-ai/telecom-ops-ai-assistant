# Runbook 17 (SYNTHETIC): Handover Events and Mobility Failures Primer

Educational summary. Verify against 3GPP TS 36.331 and TS 38.331.

## Measurement events
- A2: the serving cell becomes worse than a threshold.
- A3: a neighbour becomes offset better than the serving cell.
- A4: a neighbour becomes better than a threshold.
- A5: the serving cell becomes worse than threshold1 and a neighbour becomes better than
  threshold2.
- B1: an inter-RAT neighbour becomes better than a threshold.
- B2: the serving cell becomes worse than threshold1 and an inter-RAT neighbour becomes
  better than threshold2.

## Timers and steps
Time-to-trigger ranges from 0 ms to 5120 ms. LTE hysteresis is set in 0.5 dB steps.

## Mobility failure categories
- Too-late handover: radio link failure occurs before the handover completes.
- Too-early handover: radio link failure shortly after handover to the target, and the UE
  reconnects to the source cell.
- Handover to the wrong cell: radio link failure shortly after handover, and the UE
  reconnects to a third cell.
Tune time-to-trigger and hysteresis within the limits of Runbook 03.
