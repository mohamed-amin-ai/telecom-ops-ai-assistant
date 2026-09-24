# Runbook 05 (SYNTHETIC): Backhaul Packet Loss and Congestion

## Trigger
Packet loss above 0.5% for 10 minutes on a backhaul link, or link utilization above 80%
sustained for 30 minutes.

## Checks
1. Check link utilization and interface error counters (CRC errors).
2. Optical links: raise an alarm when receive power is within 3 dB of the receiver
   sensitivity.
3. Microwave links: check for rain fade and adaptive modulation downshift.
4. Check for transport changes in the last 24 hours.

## Actions
- Rising CRC errors: clean or replace the fibre patch cord or SFP.
- Rain fade: monitor. If the modulation stays downshifted after the weather clears, check
  antenna alignment.
- Congestion: review QoS first, then request a capacity upgrade.
- Always escalate to the Transport team.

## Severity
Raise to P2 if 3 or more sites on the same aggregation node are affected.
