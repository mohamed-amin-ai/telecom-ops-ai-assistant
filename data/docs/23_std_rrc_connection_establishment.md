# Runbook 23 (STANDARDS-DERIVED): RRC connection establishment failures and what the counters mean

Operational thresholds in this file are example values. The protocol behaviour is taken from the
3GPP specifications named under "Standards references".

## Procedure in one paragraph
The UE sends RRCSetupRequest (NR) or RRCConnectionRequest (LTE) on the common control channel. The
network answers with RRCSetup (RRCConnectionSetup in LTE) or with RRCReject
(RRCConnectionReject), which can carry a wait time. The UE completes with RRCSetupComplete
(RRCConnectionSetupComplete), which carries the NAS message. The UE runs timer T300 from the request
and treats expiry as a failed attempt.

## Where each failure shows up
- Request never reaches the gNB/eNB (UL coverage, PRACH problems, uplink interference): the UE side
  sees T300 expiry; the base station sees no attempt, so the success rate may look fine while
  accessibility is poor. Compare attempts with the cell's usual attempts for that hour.
- Network answers RRCReject: congestion or admission control. The reject counters by cause separate
  overload from configuration. A rise together with high PRB utilization is a capacity problem.
- RRCSetup sent, RRCSetupComplete never received: downlink or uplink radio problem on SRB1, or UE lost
  during setup. Check radio quality (RSRP/SINR) distribution for the cell.
- RRCSetupComplete received but the core rejects the NAS request: this counts as RRC success but
  registration or attach fails. See Runbook 25.

## Checks
1. Pull attempts and successes for the cell, and compare attempts with the same hour on previous days.
2. Break failures down by cause: congestion, unspecified, no resource.
3. Correlate with PRB utilization (Runbook 01) and connected users.
4. Check PRACH-related alarms and uplink noise (Runbook 07).
5. Check parameter changes for admission control and access barring in the last 24 hours.

## Actions
- Congestion cause dominant: capacity actions in Runbook 01; confirm access barring is not active.
- Attempts collapsed while success rate is stable: suspect a coverage or hardware fault, not
  signalling. Escalate to RF.
- Recent parameter change: revert through the change process (Runbook 14).

## Standards references
- 3GPP TS 38.331, RRC connection establishment procedure (NR); TS 36.331 (LTE).
- 3GPP TS 28.552 (5G performance measurements) and TS 32.425 (LTE) define the RRC connection
  establishment attempt and success counters, with per-cause failure counters.
- 3GPP TS 28.554 (5G KPIs) and TS 32.450 (LTE KPIs) define accessibility KPIs built from them.
