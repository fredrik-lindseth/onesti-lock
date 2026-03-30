# Archived Plans

Design and implementation plans from the v2 rewrite phase (March 2026).

These documents reference the old `nimly_pro` domain, the `zha_event`-based event listener approach, and a 10-slot (0-9) data model. All of these were revised during implementation:

- Domain became `onesti_lock` (supports all Onesti brands, not just Nimly PRO)
- Event listener uses `cluster.on_event("attribute_report")` (zha_event didn't work)
- Slot model uses ZCL range 0-199 with UI sensors for slots 3-12
- Source map values were revised based on actual Zigbee captures

Kept for historical reference. See `AGENTS.md` and `docs/technical.md` for current documentation.
