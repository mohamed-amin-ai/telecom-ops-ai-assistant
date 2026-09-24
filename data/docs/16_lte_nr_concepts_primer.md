# Runbook 16 (SYNTHETIC): LTE and NR Concepts Primer

Educational summary written for operators. Verify details against the 3GPP specifications
(for example TS 36.211, TS 38.211, TS 23.203, TS 23.501) before relying on them.

## Resource blocks
- An LTE PRB is 12 subcarriers of 15 kHz, so it is 180 kHz wide.
- An LTE 20 MHz carrier has 100 PRBs. A 10 MHz carrier has 50 PRBs.
- NR supports subcarrier spacings of 15, 30, 60 and 120 kHz.
- An NR 100 MHz carrier with 30 kHz subcarrier spacing has 273 PRBs.

## Identifiers and ranges
- LTE has 504 physical cell identities (0 to 503). NR has 1008 (0 to 1007).
- The reported RSRP range is -140 dBm to -44 dBm.

## RRC states
LTE has RRC_IDLE and RRC_CONNECTED. NR adds RRC_INACTIVE.

## Frequency ranges
NR FR1 is sub-6 GHz (410 MHz to 7.125 GHz). FR2 is 24.25 GHz to 52.6 GHz.

## Bearer QoS
- QCI 1: guaranteed bit rate, conversational voice, 100 ms packet delay budget,
  packet error loss rate of 10^-2.
- QCI 5: non-GBR, IMS signalling, 100 ms delay budget, error loss rate 10^-6.
- QCI 9: non-GBR, default bearer, 300 ms delay budget, error loss rate 10^-6.
