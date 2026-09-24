# Runbook 09 (SYNTHETIC): Incident Severity, Escalation and Change Control

## Severity definitions
- P1 (Critical): total service loss at 10 or more sites, or any outage affecting
  emergency-service coverage.
- P2 (Major): a full site outage, or degradation across 3 or more cells.
- P3 (Minor): single-cell degradation or single-cell outage.
- P4 (Low): non-service-affecting alarms.

## Response targets
- P1: acknowledge within 5 minutes, engineer engaged within 15 minutes, updates every
  30 minutes.
- P2: acknowledge within 15 minutes, updates every 60 minutes.
- P3: acknowledge within 4 hours, daily updates.
- P4: next business day.

## P1 escalation
Notify the Duty Manager and the Head of Operations within 15 minutes. Send customer
communication within 30 minutes.

## Ticket contents
Every ticket records: cell or site ID, affected KPI, start time, suspected cause, actions
taken, and estimated impact.

## Change control
No non-emergency changes between 17:00 and 22:00 local time (change freeze). Standard
parameter changes need CAB approval. Emergency changes need Duty Manager approval.
