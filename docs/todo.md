# Pingo Terrain TODO

This is the sole authoritative queue for unfinished terrain work. Use stable
manual IDs. When work is accepted, rejected, or superseded, record its ID,
evidence, and rationale in the current dated development log, remove it from
this file, and update any affected specification.

- [ ] **D1 — Flat-pattern terrain dithering:** the pattern resource, firmware
  protocol, direct RGBA2222 path, triangular fixture, native tests, and
  visually accepted emulator proof exist. Retain solid-flat as a control and
  complete physical-hardware performance/presentation qualification before
  promotion; leave emulator-coupled changes uncommitted meanwhile.
- [ ] **R1 — Regional Bay Area terrain corpus:** the 42 pinned 3DEP and nine
  NLCD inputs, regional manifest, 201×252 grid, and deterministic three-level
  family prototype exist. A 20-family fixed-west slice now feeds the live KOAK
  coordinator. The complete 50,652-record loose-L0 corpus is generated, has a
  tracked WORLD receipt, and is fully size/hash-verified by the survey builder.
  Retain it reproducibly and qualify mixed-LOD seams and relief at regional
  landmarks.
- [ ] **J1 — Position-driven terrain streaming:** the multi-record AGNB family,
  bounded host selector, eZ80 `ffs_flseek` selected-record loader, two-bank
  render-idle publication, floating-origin rebase, and a natural
  `(23,36)`-to-`(22,36)` westbound flight now pass together in the sibling KOAK
  family fixture. An arbitrary-position 8×4 loose-L0 window now follows the
  regional direct camera across the complete grid and has a qualified
  cell-crossing trace. Consolidate the regional-camera, KOAK loose, and KOAK
  family coordinators into the one fixture-independent terrain manager required
  by the scene design before adding another topology or expanding the practical
  object working set. Then add arbitrary-family/mixed-LOD planning, measure
  complete SD
  seek/read/validate/upload latency rather than only VDP publication time,
  surface persistent load failures, and retain safe object/buffer lifetime.
  Human seam/pop review and physical-hardware range, depth, and performance
  qualification remain open.
- [ ] **A1 — Bay Area airports:** pinned and generated SFO, OAK, Hayward
  Executive, San Carlos, and Concord/Buchanan components exist, and KOAK 28L
  is the qualified canonical start. Replace the proof overlays with pinned
  property-outline patches that conformingly cut the terrain, grade and
  partition residual ground/pavement/markings without coincident faces, and
  publish atomically with every superseded terrain component. Apply the
  accepted solid self-lit airport palette; derive sparse-gray simplified
  structures only from attributable mapping footprints. Add regional
  activation/publication and visually qualify seams, colors, structures,
  secondary fields, and transitions.
- [ ] **F2 — Cockpit light-flight fixture:** the panel, reduced viewport,
  attitude backdrop, chase view, fixed-point force/inertia model, and silent
  KOAK takeoff proof exist; a natural chase flight also crosses the fixed-west
  regional family boundary. Qualify physical control feel and deterministic
  flight with the generalized position-driven streamer on real hardware.
- [ ] **C1 — Layered terrain collision:** the host broad/narrow reference and
  conservative envelopes exist. Implement the swept aircraft proxy,
  transactional eZ80 candidate step, contact response, and integrated
  emulator/hardware qualification without destabilizing the proven dynamics.
- [ ] **L1 — Flat-shaded Bay Area landmarks:** original procedural Campanile,
  Mount Diablo, Salesforce, and Transamerica P3DM components now have pinned
  controls, DEM drape, restrained solid-flat materials, and quantization tests.
  Add position-driven activation, scene-budget integration, render-idle
  publication, and human silhouette/range qualification.
- [ ] **M1 — FSIM fixture launcher:** the resident MOSlet, bounded absolute-root
  config, ten-entry menu, common `0x040000` call, key-release boundaries,
  caller-CWD restoration, scene teardown, build audit, profile installation,
  host regressions, and a private headless menu-fixture-menu-MOS lifecycle
  witness exist. Human-qualify number selection, fixture Escape-to-menu,
  second Escape-to-MOS, direct LOAD/RUN return, original-CWD restoration, and
  repeated cross-fixture launches; keep emulator-coupled changes uncommitted
  meanwhile.
- [ ] **K1 — Berkeley camera-survey fixture:** a sibling binary now shares the
  exact meshes, dither resources, scene lighting, full viewport, Campanile
  start, and initial attitude of FSIM entry 3, but contains no aircraft,
  cockpit, flight dynamics, collision, or streaming state. Its absolute
  no-roll camera has clamped pitch, constant-rate arrow look, yaw-only WASD,
  world-Y Page Up/Down, and an edge-triggered bounded minus/equal speed ladder;
  it is retained as a fixed direct-RUN oracle. Its initial-frame and
  clamp/reversal trace passes, and the Author has accepted the corrected
  interactive controls. FSIM entry 0 is now the regional camera-survey
  appliance. Preserve Berkeley as the fixed visual oracle; complete
  direct/manual return and regional presentation qualification before
  accepting or committing the work.
