# Runbook 13 (SYNTHETIC): Software Upgrade Method of Procedure

## Window and approvals
Upgrades run only in the maintenance window from 00:00 to 05:00 local time. Starting an
upgrade needs CAB approval and Duty Manager sign-off.

## Pre-checks
1. Back up the configuration.
2. Record the alarm baseline and the pre-upgrade KPI baseline.
3. Stage the rollback package on the node.
4. Confirm there is no open P1 or P2 incident in the region.

## Canary
Upgrade 5% of sites first, with a minimum of 3 sites, and observe them for 24 hours.
Continue the rollout only if no KPI degrades by more than 1 percentage point from the
pre-upgrade baseline and there are no new critical alarms.

## Rollback triggers
- Any canary KPI degrades by more than 1 percentage point from its baseline.
- A site is unavailable for more than 15 minutes after its reboot.

## After the upgrade
Run 24 hours of hypercare with the NOC watching the upgraded sites.
