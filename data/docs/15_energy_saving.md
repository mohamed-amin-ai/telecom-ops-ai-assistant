# Runbook 15 (SYNTHETIC): Energy Saving Features

## When allowed
Carrier shutdown, symbol shutdown and deep sleep are allowed only between 00:00 and 05:00
local time.

## Exclusions
Do not enable energy saving on:
- cells that cover emergency services,
- cells in a region with an open P1 or P2 incident,
- cells that are the sole coverage layer.

## Wake-up
Capacity cells must wake up within 5 minutes when the PRB utilization of the coverage layer
above them exceeds 60%.

## Safeguard
Disable energy saving on a cell if its RRC SSR drops below 98.5% while the feature is
active. Report the energy saved alongside any KPI degradation each week.
