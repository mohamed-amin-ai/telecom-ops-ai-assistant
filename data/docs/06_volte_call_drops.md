# Runbook 06 (SYNTHETIC): VoLTE Call Drops

## Trigger
VoLTE call drop rate above 1.0% over 1 hour is P3. Above 2.0% is P2.

## Common causes
Poor uplink coverage, handover or SRVCC failures, packet loss on the QCI 1 bearer, IMS core
problems.

## Checks
1. Check QCI 1 packet loss in uplink and downlink. The target is below 1%.
2. Check the SRVCC success rate.
3. Check the RSRP and SINR distribution (thresholds in Runbook 10).
4. Check the IMS P-CSCF SIP 5xx error rate.

## Actions
- Weak uplink: coverage optimisation.
- Check RLC and ROHC configuration on the affected cells.
- If the SIP 5xx rate is above 1%, escalate to IMS Ops.
