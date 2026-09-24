# Runbook 11 (SYNTHETIC): 5G NR Access and Dual Connectivity Issues

## Trigger
- NSA (EN-DC): SgNB addition success rate below 95% over 1 hour.
- NR RACH success rate below 97% over 1 hour.
Default severity is P3. Apply Runbook 09 for escalation.

## Checks
1. NSA only: check the X2 link between the LTE anchor and the NR node.
2. Check NR cell availability and SSB transmit power alarms.
3. Check PRACH configuration. A PRACH root sequence conflict with a neighbouring NR cell
   causes RACH failures.
4. Check NR uplink interference (Runbook 07) and NR PRB utilization (Runbook 01).
5. Review NR parameter changes from the last 24 hours.

## Actions
- PRACH root sequence conflict: raise a change request to re-plan the root sequence.
- X2 link down: escalate to the Transport team.
- Low SgNB addition success with a congested NR cell: follow Runbook 01 on the NR cell.
