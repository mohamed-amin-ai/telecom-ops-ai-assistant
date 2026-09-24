# Runbook 02 (SYNTHETIC): RRC Setup Failure

## Trigger
RRC setup success rate (RRC SSR) below 98.5% over 1 hour on a cell.
Raise to P2 if RRC SSR is below 95% for 15 minutes.

## Common causes
Cell overload (PRB or PDCCH congestion), signalling link problems on S1 (4G) or N2 (5G),
admission control thresholds set too low, MME or AMF overload.

## Checks
1. Correlate with PRB utilization and connected users. If PRB utilization is above 85%,
   treat it as a capacity problem and follow Runbook 01.
2. Check the RRC reject counters by cause. A dominant "congestion" cause points to
   admission control limits.
3. Check S1/N2 link status and SCTP alarms.
4. Check MME/AMF load and throttling.
5. Check for admission control parameter changes in the last 24 hours.

## Actions
- Admission control change found: revert it through the change process.
- SCTP alarms present: escalate to the Transport team.
- MME/AMF overload: escalate to Core Ops (see Runbook 08).
