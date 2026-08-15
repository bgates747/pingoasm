# Pingo Terrain TODO

This is the sole authoritative queue for unfinished terrain work. Use stable
manual IDs. When work is accepted, rejected, or superseded, record its ID,
evidence, and rationale in the current dated development log, remove it from
this file, and update any affected specification.

- [ ] **E1 — AgonDev C/assembly interoperability experiment:** retain the
  qualified assembly fixed-point, vector, matrix, coordinate-transform, MOS,
  and VDP mechanisms. Establish an isolated `experiments/agondev-interop`
  application that uses the canonical `~/Agon/agondev` toolchain and the
  `mos-agondev` port as its ABI reference. Prove C-to-assembly and
  assembly-to-C calls, three-byte argument slots, 8/16/24-bit return values,
  explicit shared-state layout, deterministic linking, and a normal CMake
  configure that remains inert unless the experiment is explicitly enabled.
  Keep C limited to policy/state-machine work and reject compiler runtime
  arithmetic helpers from the probe. The isolated MOS application, generated-
  only CMake wrapper, pinned provenance, C-to-assembly-to-C round trip,
  8/16/24-bit return witnesses, deterministic binary/ELF rebuild, and static
  helper/symbol/layout gates now pass. A pinned isolated headless Agon run also
  proves one PASS and a clean return to MOS. The first bounded terrain-policy
  A/B now compares C and assembly coverage-group selection across processed,
  infeasible, score, tie, and source-order cases without moving fixed-point
  mathematics. A separate fixed-address 301-byte AgonDev module and sibling
  fixture now pass assembly-oracle, guarded-C, missing-module, corrupt-module,
  four-north, all-six-direction, and first clipped-edge semantic gates without
  changing the accepted binary. An architecture-matched cached-assembly
  control shows that most of the apparent C speedup came from caching topology:
  cached assembly used about 9.5 percent fewer selector-call guest cycles than
  guarded C and about 40.5 percent fewer than the accepted recomputing selector
  in this emulator profile. A complete 227-record guest-cycle profile now
  attributes about 67.7 percent of the measured cold-load spans to
  validation/index/CRC and 31.1 percent to upload/staging. A hash-isolated
  register-held CRC sibling now preserves all 227 records and loader error
  precedence while reducing validation by 56.4 percent and the five measured
  cold phases by 38.2 percent in one exhaustive emulator pair; repeat its
  timing and qualify it on hardware before promotion. Human-qualify the
  standalone probe on physical hardware. The bounded DATA-only CTS/THRE
  sibling also preserves all 227 records and reduces its completion-equivalent
  upload span by 19.3 percent and the five cold phases by 5.6 percent, but it
  relies on private state and CTS wiring from one exact Console8 MOS image;
  prefer a MOS-side THRE correction before promotion. An exact one-byte MOS
  binary proof now preserves all 227 publications while reducing the stricter
  publication-complete upload-to-submit interval by 12.4 percent and the
  read-to-submit interval by 4.0 percent. Rebuild that change normally in the
  MOS-owning repository, repeat its timing, and qualify CTS/FIFO behavior on
  hardware rather than installing the derived blob. Combining the exact
  qualified register CRC and THRE siblings reduced the stricter all-227
  publication-complete read-to-submit interval by 41.0 percent. A 16-entry RRD
  nibble CRC now reduces direct CRC another 37.5 percent, preserves all 227
  CRC/IX/publication witnesses, and proves guest errors 9/no-publication and
  10/before-CRC. Retain BUILD receipt
  `build/evidence/regular-lod-crc-nibble-sibling-build-v2/BUILD.json`
  (`81158c512d31cfd0c7cd85af30e747953d7e4e8d73f9665f439a7cf56cb481d1`),
  recovered V3 report
  `build/evidence/regular-lod-crc-nibble-thre-sibling-profile-v3/regular-lod-crc-nibble-thre-sibling-profile.json`
  (`fab87d454970f4ee8dccd9124af261c0c92cd927e896770ef3e2471dff706829`),
  and cumulative accepted+TEMT-to-nibble+THRE receipt
  `build/evidence/regular-lod-crc-nibble-cumulative-analysis-v1/regular-lod-crc-nibble-cumulative-analysis.json`
  (`5ca055ea0194102bd1a8d46464c08c5122c0de0ba030c45a70113dc4e11687e7`),
  which reparses both raw logs and records -51.9510 percent all-227 / -51.9977
  percent loop read-to-published-own-submit. V1's record-8 publication race and
  V2's corrected `out`-timing analyzer stop remain disclosed. Repeat the pair,
  validate five-cycle hardware `RRD` timing and IRQ register preservation,
  rebuild MOS THRE from source, and qualify CTS/FIFO/UART and presentation on
  hardware before promotion. Complete the regional
  boundary witnesses, end-to-end handoff and physical-SD/native-VDP/render
  timing, and sibling hardware presentation before deciding whether any
  runtime policy or just the cache architecture should be promoted. The
  injected bad-result live latch gate is complete: only the first C call ran,
  all later groups used assembly, and exact ownership was retained.

- [ ] **D1 — Flat-pattern terrain dithering:** the pattern resource, firmware
  protocol, direct RGBA2222 path, triangular fixture, native tests, and
  visually accepted emulator proof exist. Retain solid-flat as a control and
  complete physical-hardware performance/presentation qualification before
  promotion; leave emulator-coupled changes uncommitted meanwhile.
- [ ] **R1 — Regional Bay Area terrain corpus:** the 42 pinned 3DEP and nine
  NLCD inputs, regional manifest, historical 201×252 grid, and deterministic
  three-level family prototype exist. The superseding equal-area N=5 hex
  profile now has all 50,183 loose-L0 cells, a checksum-bound WORLD receipt,
  six exact straight shared boundaries per cell, and a mandatory full-region
  Blender review artifact accepted by the Author. The fixture build now parses
  and validates every indexed container, including distant cells. Retain both
  reproducibly; implement and qualify hex-native mixed LOD using the accepted
  mathematical silhouette-error and seam contract. Named regional features
  remain human review witnesses rather than compiler inputs. First run the
  isolated Lake Anza control/candidate experiment specified by that contract:
  compare regular material voting with topology-preserving constrained water
  contours and multiple distance tiers in a dedicated Blender artifact, then
  profile the NumPy-first host implementation before considering native code.
  A separately accepted experiment now generates a natural adaptive master
  surface before routing bounded roughly hex-addressed partitions through its
  existing edges. Its checksum-verified complete-region Blender artifact now
  proves a deterministic 497,767-vertex/992,477-face surface and nonempty,
  connected, sub-1,024 m physical components. The former bounded Campanile
  proof is now joined by a compact checksum-bound complete-master source and
  all 50,183 surface-only natural P3DM records. The full build proves 294,948
  exact internal seams after quantization and maps the retained semantics onto
  the accepted three-class native palette (water/developed/other land) plus
  scene illumination. A derived full-region Blender review artifact is
  mandatory and present. Human near-field seam/presentation review remains
  open.
  The visually rejected natural-near/regular-far control remains negative
  evidence. Its replacement is now a complete, algorithmic regular-only
  hierarchy: N=5 rings 0--5 plus N=1 `8x4 -> 4x2 -> 2x1 -> 1x1` nodes through
  ring 30, with no coarse ownership inside the near disk. The whole-region
  build has 83,293 validated records / 57,521,020 logical bytes, generated
  phase plans, protected dynamic slots, transforms, skirts, receipts, and the
  mandatory Blender review. The proven bound remains 91 detailed plus at most
  159 coarse objects. A 227-object Marina cold run passes. The regular binding
  now treats detailed and coarse owners as one slot domain and consumes the
  generated full-owner coverage recipes. Entering meshes stage only in inactive
  slots; complete overlap components swap atomically at render idle. Four live
  north crossings and a subsequent radius-four cold restart match the host
  owner sets with no active mesh overwrite, coverage hole, or render inside a
  commit. Its loader also converts the legacy reflected `Z=-east` corpus to a
  right-handed `Z=+east` published world, with matching placement, camera, and
  rebase signs. The C-policy sibling has now exercised all six live directions
  and the clipped western `(0,117) -> (1,117)` edge with exact final ownership
  and transforms. Next capture the remaining regional boundaries, longer
  full-region routes, and SD seek/read/upload cost. Adjacent movement is
  currently qualified only at radius five; decide whether smaller review radii
  need their own recipes or a cold-crossing policy.
  Next decide whether full runtime promotion requires exact canonical
  six-neighbor combinatorics or accepts the artifact's explicit physical
  graph; repair 0.180-degree constraint slivers and implement nested LOD seams
  either way. Do not replace the accepted straight-sided runtime corpus until
  partition, containment, LOD, collision, culling, and hardware gates pass.
- [ ] **J1 — Position-driven terrain streaming:** the multi-record AGNB family,
  bounded host selector, eZ80 `ffs_flseek` selected-record loader, two-bank
  render-idle publication, floating-origin rebase, and a natural
  `(23,36)`-to-`(22,36)` westbound flight now pass together in the sibling KOAK
  family fixture. An arbitrary-position 8×4 loose-L0 window now follows the
  regional direct camera across the complete grid and has a qualified
  cell-crossing trace.
  The topology-neutral `runtime/ez80/terrain-manager.inc` now consolidates the
  authoritative lifecycle, status ABI, stable residency, bounded publication,
  retries, activation, rebase, and teardown contracts. Its first thin hex
  provider streams the complete corpus, exposes live radius 0..5 disks, and
  passes a silent 19-cell cold view plus 2→5→0 expansion/contraction through
  all 91 exact command-52 transforms. Its fixed 16 m six-side retention band
  passes edge/corner no-chatter regressions. The `NAT` provider now reuses the
  same manager and planning rules across the complete 50,183-record natural
  corpus, starts at the 91-cell radius-five maximum over the Berkeley Marina,
  and passes a silent cold publication with all 91 objects traversed and the
  command-53 far plane at 65,535. The rejected mixed-topology ring-30 control
  proved that the manager can own 183 multi-LOD objects, but it remains only
  historical evidence. The position-driven regular-only hierarchy provider
  and its 227-object Marina cold run now exist. Its continuity-first transition
  has been superseded by full-owner component staging and atomic commits. The
  corrected cardinal orientation is human-approved; four live moving-origin
  handoffs and the render-idle radius-four cold restart now pass deterministic
  debugger capture. The sibling now qualifies all six adjacent directions and
  the first clipped western edge. Remaining regional boundaries, extended
  routes, and physical-hardware qualification remain open. Measure physical SD
  seek/read latency plus complete end-to-end/native-VDP/render timing; use the
  guest-cycle profile to optimize validation/CRC and upload staging, and expose
  persistent runtime failures in clients. Physical-hardware range, depth, and
  performance qualification remain open.
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
  regional family boundary. A provisional backend-neutral reconstruction of
  the static panel now produces corrected circular gauges, a blank GPS bay,
  arbitrary exact-size previews, and named future instrument repaint bounds;
  its presentation is awaiting Author review before it supersedes the bitmap.
  Qualify physical control feel and deterministic flight with the generalized
  position-driven streamer on real hardware.
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
  config, thirteen-entry menu, common `0x040000` call, key-release boundaries,
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
  interactive controls. FSIM entry 0 now exercises the universal hex-manager
  survey. Preserve Berkeley and the rectangular regional viewer as direct
  historical oracles; complete direct/manual return and regional presentation
  qualification before accepting or committing the work.
