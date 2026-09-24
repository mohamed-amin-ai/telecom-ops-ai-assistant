# Runbook 19 (SYNTHETIC): Alarm Handling Rules

## Alarm storm
More than 100 alarms per minute from one site is an alarm storm. Suppress downstream
alarms and look for the root alarm.

## Flapping alarm
A flapping alarm is 5 raise and clear cycles within 10 minutes. Treat it as one fault,
not as separate alarms.

## Correlation order
Work from the bottom up: power, then transport, then baseband and radio, then cell, then
KPIs.

## Clearing
Never clear an alarm manually without noting the root cause in the ticket.

## Maintenance mode
Sites under planned work must be in maintenance mode so tickets are not raised. Maintenance
mode expires automatically after 8 hours.
