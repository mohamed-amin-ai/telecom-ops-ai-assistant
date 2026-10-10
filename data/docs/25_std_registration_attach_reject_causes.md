# Runbook 25 (STANDARDS-DERIVED): Core registration and attach rejects by cause

Radio access succeeds but the user cannot get service. The reject cause tells you which team owns it.

## 5G registration (NAS, 5GMM)
The UE sends a Registration Request; the AMF answers Registration Accept or Registration Reject with a
5GMM cause. Timer T3510 supervises the UE side of the procedure.
- Cause 3 (illegal UE) or 6 (illegal ME): subscriber or device problem, not a network fault.
- Cause 7 (5GS services not allowed): subscription does not allow 5G service; check provisioning.
- Cause 11 (PLMN not allowed), 12 (tracking area not allowed), 13 (roaming not allowed in this tracking
  area), 15 (no suitable cells in tracking area): provisioning or tracking area configuration.
- Cause 22 (congestion): AMF overload or throttling; the reject can carry a back-off timer (T3346).
  Treat a rise as a core capacity incident.

## 4G attach (EMM)
Same idea in TS 24.301: Attach Reject with EMM cause. Cause 11, 12, 13, 15 mirror the above; cause 17
(network failure) and 22 (congestion) point to MME or downstream (HSS, SGW) trouble.

## Checks
1. Group reject counts by cause for the last hour and compare with the last 7 days.
2. A single cause jumping while others are flat is a provisioning or configuration change. A broad rise,
   especially congestion, is capacity or a dependency failure.
3. For congestion or network failure: check AMF/MME load, N2/S1 SCTP association state, and the
   subscriber database or authentication server reachability.
4. Check for a new tracking area or PLMN configuration pushed in the last 24 hours.
5. If RRC setup success is also falling, start at Runbook 23 instead.

## Actions
- Provisioning causes (3, 7, 11, 12, 13, 15): route to the core provisioning team with example IMSI-free
  counters (cell, time, cause); do not touch radio parameters.
- Congestion or network failure: escalate to Core Ops (Runbook 08) and consider load balancing across AMFs.
- Always record cause, window and affected cells in the ticket.

## Standards references
- 3GPP TS 24.501: 5GS NAS, registration procedure and 5GMM cause values, T3510, T3346.
- 3GPP TS 24.301: EPS NAS, attach procedure and EMM cause values.
- 3GPP TS 38.413 (NGAP) and TS 36.413 (S1AP) for the AMF/MME to RAN interfaces; TS 38.412 / TS 36.412
  for SCTP transport.
