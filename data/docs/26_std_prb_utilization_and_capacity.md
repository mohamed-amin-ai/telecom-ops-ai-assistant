# Runbook 26 (STANDARDS-DERIVED): PRB utilization, what it measures, and when it is a capacity problem

## Definition
Physical resource block (PRB) usage is the share of a cell's PRBs used over a measurement period. In the
5G performance measurement spec the counters are the used and total PRBs for downlink and uplink
(RRU.PrbUsedDl and RRU.PrbTotDl, and the uplink pair); the ratio is the utilization. Averages hide
busy-hour peaks, so compare the same hour across days and look at the peak sample, not just the mean.

## Reading it correctly
- High utilization with healthy throughput per user and low RRC rejects: busy but coping.
- High utilization with falling user throughput, rising RRC rejects or rising handover preparation failures:
  capacity problem.
- A sudden step to near 100% on one cell with flat neighbours: suspect a stuck user, interference
  loop, or a neighbour that went down and pushed traffic here (check neighbours first).
- Utilization falling to near zero while the cell stays up: possible sleeping cell (Runbook 04) or
  energy-saving state (Runbook 15).

## Checks
1. Compare with the same hours on the previous 7 days; flag only deviations from that baseline.
2. Check neighbour cells for outage or sudden load drop.
3. Check connected users and per-user throughput.
4. Check for recent carrier, bandwidth or energy-saving configuration changes.
5. Confirm uplink and downlink separately; an uplink-only problem points to interference (Runbook 07).

## Actions
- Sustained utilization above the planning threshold on the busy hour: raise to capacity planning;
  short-term load balancing via mobility offsets towards less loaded layers.
- Neighbour outage: handle the outage first (Runbook 04), capacity will relax once it is back.
- Energy-saving side effect: restore the carrier during the busy hours and retest.

## Standards references
- 3GPP TS 28.552: 5G performance measurements, PRB usage counters. TS 36.314: LTE layer-2 measurements
  (radio resource utilization). TS 28.554 / TS 32.450 for KPI definitions built on them.
