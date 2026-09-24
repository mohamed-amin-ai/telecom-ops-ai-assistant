# Runbook 21 (SYNTHETIC): PCI and Neighbour Planning

## PCI rules
- Avoid equal PCI mod 3 between neighbouring cells, because it causes reference-signal
  and synchronization-signal interference.
- PCI collision: two neighbouring cells on the same frequency share a PCI.
- PCI confusion: one cell has two neighbours that share a PCI.
- Minimum reuse distance: 5 km in urban areas and 15 km in rural areas.

## Neighbour relations
A cell may have at most 32 neighbour relations. Relations discovered by ANR stay
unverified for 7 days before they are locked.
Changes to PCI or relations follow Runbook 14 and the freeze in Runbook 09.
