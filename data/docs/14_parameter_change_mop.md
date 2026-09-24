# Runbook 14 (SYNTHETIC): Parameter Change Method of Procedure

## Change classes
- Standard: pre-approved template, still needs CAB approval.
- Normal: reviewed by the CAB.
- Emergency: approved by the Duty Manager.
Change freeze rules are in Runbook 09.

## Required in every change request
Change ID, scope (list of cells), rollback plan, expected KPI impact, and monitoring plan.

## Batching
A single batch is limited to 20 cells. Wait 1 hour before starting the next batch.

## Monitoring and rollback
Monitor the affected KPIs for 60 minutes after each batch. Roll back automatically if any
monitored KPI degrades by more than 2 percentage points.

## Backups
Back up the configuration before the change and keep the backup for 30 days.
