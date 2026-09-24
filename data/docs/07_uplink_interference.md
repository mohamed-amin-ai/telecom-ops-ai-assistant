# Runbook 07 (SYNTHETIC): Uplink Interference

## Symptoms
Average uplink RSSI above -100 dBm over 15 minutes on a cell with low traffic, falling
uplink throughput, and RACH failures.

## Common causes
External interference, passive intermodulation (PIM), faulty feeder or connector, wideband
repeaters.

## Checks
1. Compare RSSI per receive branch. An imbalance above 3 dB between branches points to a
   feeder or connector fault.
2. A pattern that recurs at fixed times of day suggests an external source.
3. Correlate with traffic. PIM-related interference rises with load.

## Actions
- Field inspection and a PIM test.
- Run a spectrum scan.
- If an external interferer is suspected, engage the Spectrum team, who liaise with the
  regulator.
