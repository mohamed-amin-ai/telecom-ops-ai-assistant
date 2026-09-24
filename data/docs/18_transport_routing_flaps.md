# Runbook 18 (SYNTHETIC): Transport Routing Flaps and MTU

## Flapping
More than 3 BFD session flaps in 10 minutes count as flapping. The same applies to BGP or
IS-IS adjacency flaps.

## Checks
1. Physical layer errors on the interface (CRC, optical power).
2. MTU mismatch between the two ends.
3. Router CPU above 80%.
4. Transport changes in the last 24 hours.

## Actions
- Fix or replace failing optics (see Runbook 05).
- Apply route flap dampening only after the physical cause is ruled out.
- Escalate to the Transport NOC.
- Raise to P2 if an aggregation node is isolated and 3 or more sites are lost.

## MTU rule
GTP-U over UDP over IPv4 adds 36 bytes of overhead (8 GTP, 8 UDP, 20 IPv4). The backhaul
MTU must be at least 1536 bytes to carry 1500-byte user packets without fragmentation.
