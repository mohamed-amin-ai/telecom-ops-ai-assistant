# Runbook 08 (SYNTHETIC): Attach and Registration Failure

## Trigger
Attach (4G) or registration (5G) success rate below 99% over 15 minutes.
Raise to P2 if below 95%.

## Checks
1. MME/AMF CPU load. CPU above 80% indicates overload.
2. HSS/UDM error rates (Diameter or SBI).
3. Authentication failure causes.
4. Changes or software upgrades in the last 24 hours.

## Actions
- Rollback rule: if the failures began within 30 minutes of a change, roll back under change
  management with Duty Manager approval.
- If the success rate is below 95%, escalate to Core Ops immediately and notify the Duty
  Manager.
