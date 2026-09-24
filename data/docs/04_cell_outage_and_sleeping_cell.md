# Runbook 04 (SYNTHETIC): Cell Outage and Sleeping Cell

## Cell outage
A cell-down alarm is active. Severity follows Runbook 09: a single-cell outage is P3 and a
full site outage (all cells down) is P2. Check power, transport and radio unit alarms first.

## Sleeping cell
A sleeping cell shows no alarm but carries almost no traffic.
Detection rule: traffic below 10% of the baseline (see Runbook 10) for 60 minutes while
neighbouring cells are normal and no alarms are active. Zero RRC attempts on the cell
confirms it.

## Recovery sequence
1. Confirm no active alarms and normal neighbours.
2. Check radio unit and baseband status.
3. With approval, soft block and then unblock the cell.
4. If there is no recovery, reset the radio unit.
5. If still unresolved 30 minutes after the first recovery action, dispatch the field team.

## Verification
Traffic must return above 80% of baseline within 15 minutes of the recovery action.

## Coverage compensation
For a prolonged outage, adjust tilt on neighbouring cells to compensate. This is allowed
only through an approved change.
