# Runbook 03 (SYNTHETIC): Handover Failure

## Trigger
Intra-frequency handover success rate below 97% for 1 hour on a cell pair, or inter-RAT
handover success rate below 95%.

## Common causes
Missing neighbour relations, PCI collision or confusion, X2/Xn link down, target cell
congestion, poorly tuned time-to-trigger or hysteresis, target cell outage.

## Checks
1. Check the neighbour relation table for missing neighbours.
2. Check for PCI collision or confusion alarms.
3. Check X2/Xn link state between the two sites.
4. Check target cell PRB utilization and RRC SSR (Runbooks 01 and 02).
5. Review handover parameter changes from the last 24 hours.

## Actions
- Missing neighbour: add the relation through ANR or manually.
- PCI conflict: raise a change request to re-plan the PCI. Never change PCIs outside an
  approved change.
- X2/Xn down: escalate to the Transport team.

## Ping-pong handovers
If the ping-pong handover ratio exceeds 5%, raise the A3 hysteresis in 0.5 dB steps.
The total change without CAB approval is limited to 2 dB.
