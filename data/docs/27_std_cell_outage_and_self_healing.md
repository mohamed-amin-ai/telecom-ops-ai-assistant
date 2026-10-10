# Runbook 27 (STANDARDS-DERIVED): Cell outage, sleeping cell and self-healing

## Distinguish three states
- Declared outage: the node reports the cell as down or locked. Alarms exist, availability counters
  show unavailable time.
- Sleeping cell: the cell reports as up with no alarms but carries almost no traffic. Only KPI
  behaviour reveals it: users and attempts collapse relative to the usual level while neighbour load
  rises.
- Degraded cell: up and carrying traffic, but with poor accessibility or retainability.

## Checks
1. Is there an active alarm on the cell or its site? If yes, follow Runbook 19 (alarm handling).
2. No alarm but attempts and users dropped sharply versus the same hour on previous days: treat as a
   suspected sleeping cell. Check neighbours' load for a matching rise.
3. Check the transport link and site power (Runbooks 12 and 18) before blaming the radio unit.
4. Check whether a software or parameter change was applied near the start of the drop (Runbooks 13, 14).
5. Check that energy saving has not switched the cell off outside its planned window (Runbook 15).

## Actions
- Declared outage with site-wide cause (power, transport): escalate to the owning team; incident
  severity per Runbook 09.
- Suspected sleeping cell: request a remote cell restart or unlock/lock cycle through the change
  process; if traffic does not return, dispatch field support.
- Record the downtime window for the availability budget (Runbook 22).

## Self-healing background
3GPP self-organizing networks define self-healing, including detection of cell outage and
compensation by adjusting neighbouring cells. Where an operator has this enabled, confirm what the
automation already did before acting, so actions do not fight each other.

## Standards references
- 3GPP TS 32.541: self-organizing networks, self-healing (cell outage detection and compensation).
- 3GPP TS 28.552 / TS 32.425: cell availability and unavailable-time measurements.
