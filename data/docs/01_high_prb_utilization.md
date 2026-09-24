# Runbook 01 (SYNTHETIC): High PRB Utilization

## Trigger
PRB utilization above 85% for 30 minutes or more on a single cell (downlink or uplink).
Default severity is P3. Raise to P2 if utilization exceeds 95% for 30 minutes.

## Symptoms
Rising RRC setup failures, falling per-user throughput, growing connected-user count.

## Checks
1. Compare with neighbouring cells. A lone spike points to a local cause (event crowd,
   neighbour outage). A region-wide rise points to a core or transport issue.
2. Look for a neighbour outage or a parameter change in the last 24 hours.
3. Check backhaul utilization and packet loss on the serving site (see Runbook 05).

## Actions
- Enable or tune load balancing towards underused neighbours. Adjust idle-mode
  reselection offsets first, then connected-mode load balancing.
- If a neighbour is down, follow Runbook 04 and consider a temporary tilt change on
  surrounding cells through an approved change.
- If utilization stays above 85% for more than 4 hours, escalate to capacity planning.

## Capacity planning trigger
Busy-hour PRB utilization above 70% on 7 consecutive days opens a capacity expansion review.
