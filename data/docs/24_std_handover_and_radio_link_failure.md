# Runbook 24 (STANDARDS-DERIVED): Handover failure, radio link failure and re-establishment

Thresholds are examples; protocol behaviour follows the 3GPP specifications under "Standards references".

## How a handover fails
The source cell sends RRCReconfiguration (RRCConnectionReconfiguration in LTE) with reconfiguration-with-sync
(mobilityControlInfo in LTE) after a measurement report. The UE starts timer T304 and tries the target cell.
- T304 expires: the handover failed. The UE starts RRC connection re-establishment.
- Radio link failure (RLF) before or during the handover: the UE detects it with T310, which starts after
  N310 consecutive out-of-sync indications from lower layers and stops after N311 in-sync indications.
  On T310 expiry the UE declares RLF and starts re-establishment (timer T311 for cell selection).
- Re-establishment succeeds only if the selected cell holds the UE context (prepared cell). Otherwise the
  UE falls back to idle and the call or session drops.

## Classifying failures (mobility robustness)
- Too late: RLF in the source cell shortly before or during the handover, UE re-establishes in the target.
  Typical cause: time-to-trigger or offset too large, or fast-moving UEs.
- Too early: RLF shortly after a successful handover to the target, UE re-establishes in the source.
  Typical cause: handover triggered too soon, weak target.
- Wrong cell: RLF after handover, UE re-establishes in a third cell. Typical cause: missing or wrong
  neighbour relation or overlapping PCI problems (Runbook 21).

## Checks
1. Split handover failures into preparation failures (target rejected, no resources, X2/Xn problem) and
   execution failures (T304 expiry, RLF).
2. For execution failures, classify as too late / too early / wrong cell using RLF reports where available.
3. Check target cell load and alarms, and the Xn/X2 link and SCTP status (Runbook 18).
4. Look for recent changes to handover offsets, time-to-trigger, or neighbour lists.
5. Check PCI collisions or confusions on the failing source-target pair (Runbook 21).

## Actions
- Preparation failures dominate: fix target capacity or the inter-node link first.
- Too late: reduce offset or time-to-trigger for the pair; too early: increase them.
- Wrong cell: correct neighbour relations; resolve PCI conflict.
- Make parameter changes on the pair, not network-wide, and re-measure for a full busy hour.

## Standards references
- 3GPP TS 38.331 and TS 36.331: RRC reconfiguration with sync, RLF detection (T310, N310, N311) and
  re-establishment (T311).
- 3GPP TS 36.300 and TS 38.300: mobility and mobility robustness optimisation; TS 38.423 (XnAP) and
  TS 36.423 (X2AP) for inter-node preparation.
- 3GPP TS 28.552 / TS 32.425: handover preparation and execution attempt/success counters.
