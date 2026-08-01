# TurboVega OTF session notes

## Active repository

- Local path: `/home/smith/Agon/TurboVega`
- Remote: `https://github.com/TurboVega/agon-vdp-otf.git`
- Current branch: `pingo3D`
- Upstream: `origin/pingo3D`

## Session state

- The branch was initially dirty:
  - Modified: `platformio.ini`
  - Untracked: `video/pingo/assets/triangle/`
- All tracked and untracked changes were saved in:
  - `stash@{0}: On pingo3D: test fixtures`
- The working tree was verified clean after creating the stash.

## Related UART research

The upstream-derived firmware uses `Serial2` as `VDPSerial` for communication between the ESP32 VDP and eZ80. Existing transmit paths include `VDUStreamProcessor::writeByte()` for individual raw bytes and `VDUStreamProcessor::send_packet()` for framed VDP protocol responses.

A fuller handoff is available at:

`/home/smith/Agon/mystuff/pingoasm/docs/agon-vdp-uart-transmit-handoff.md`

---

## Technical précis: BDPP and Off The Cuff

### Executive summary

Curtis Whitley's work comprises at least two distinct but complementary ideas:

1. **BDPP (Bidirectional Packet Protocol)** is a replacement transport mode for the serial link between the eZ80/MOS and ESP32/VDP. It makes both directions packet-oriented, makes eZ80 transmission interrupt-driven, uses ESP32 UART DMA, exposes larger packets to applications, and multiplexes up to 16 independent logical streams.
2. **OTF (On-the-Fly, also called Off The Cuff)** is principally a new graphics architecture. Instead of storing a complete framebuffer, it retains a scene made of graphics primitives in ESP32 memory and generates each VGA scanline just ahead of display. This makes high-resolution 64-colour modes such as 800x600 possible within the ESP32's limited DMA-capable RAM.

The two ideas are related but not synonymous. BDPP improves and generalizes the eZ80↔ESP32 data path. OTF reduces how much scene data needs to cross that path and gives the ESP32 persistent, manipulable display objects. The `otf-early-cut` branch merges BDPP because the two designs reinforce each other, but OTF is not merely a nickname for bidirectional communication.

### Baseline: what canonical Agon VDP already does

The normal Agon arrangement is already electrically and logically bidirectional:

- The eZ80 sends an unframed stream of printable bytes and BBC-style VDU commands to the ESP32 at 1,152,000 baud.
- The ESP32 sends small legacy VDP packets back for keyboard and mouse events and replies such as cursor position, screen-pixel colour, RTC data, and mode information.
- On the eZ80 side, MOS receives those replies and generally turns them into MOS/system-variable updates. Applications do not normally own the reply packets directly.
- The normal outgoing eZ80 path is synchronous: each application output byte is written through the UART in sequence rather than assembled into application-visible packets.

Canonical upstream later added a `VDPVAR_FULL_DUPLEX` feature. Despite its name, that primarily selects ESP32 hardware flow control (`RTS` alone versus `CTS+RTS`). It does not provide BDPP's framing, DMA packet engine, logical streams, application-owned receive buffers, or eZ80 packet API.

Thus “BDPP adds bidirectionality” is useful shorthand, but technically incomplete. The baseline link already carries bytes in both directions. BDPP makes large, structured, application-controlled, asynchronous transfers in both directions a first-class facility.

### What BDPP changes

#### Symmetric framing

After BDPP is enabled, traffic in both directions is enclosed in packets rather than sending raw VDU bytes from the eZ80 and only legacy reply packets from the ESP32.

A packet consists of:

```text
0x89
flags
stream-index:packet-index
payload-size
payload (1..256 bytes)
0x89
```

A zero size byte represents 256 payload bytes. Reserved marker bytes are escaped:

- `0x89` becomes `0x8B 0x8A`
- `0x8B` becomes `0x8B 0x8D`

The flags distinguish print/command/response traffic, first/middle/last message portions, driver-owned versus application-owned packets, and processing state.

#### Two packet ownership models

**Driver-owned packets** hold up to 32 payload bytes. Ordinary `PRINT`, `VDU`, `PLOT`, `RST &10`, `RST &18`, `printf()`, and `putch()` output is automatically accumulated into them. Full packets are queued automatically; partially filled packets must be flushed at suitable semantic boundaries.

**Application-owned packets** hold up to 256 payload bytes. An application allocates the eZ80 memory and explicitly:

- prepares a packet slot for reception,
- queues a packet for transmission,
- polls for completion,
- retrieves received flags and actual size, and
- releases the packet slot.

Up to 16 application packet indexes are supported. Requests include a packet index so that the ESP32 can put a response into the matching prepared eZ80 buffer.

#### Logical stream multiplexing

The upper nibble of the indexes byte selects one of 16 streams. On the ESP32, each stream has its own `BdppStream` and `VDUStreamProcessor`.

The intended benefit is interleaving independent jobs without confusing their byte streams. For example, one stream could feed a large image or command buffer while another updates a progress display. Packet ordering is preserved within the selected stream processor rather than forcing all activity through one undifferentiated VDU parser.

The branch implementation iterates over all 16 stream processors and processes available data for each one.

#### Less CPU intervention during transport

On the eZ80, BDPP is designed to use both UART receive and transmit interrupts and the hardware FIFOs. Packet state machines still run in eZ80 software, so the CPU is interrupted as bytes move.

On the ESP32, BDPP stops Arduino `Serial2` and reattaches UART2 to the UHCI0 DMA controller. UHCI performs framing/escaping and moves a packet before interrupting the CPU. This is meant to replace frequent byte-oriented UART servicing with packet-level completion work.

This is one of the most consequential parts of BDPP: it is not just a new byte format layered over the existing `Stream`; it introduces a different ESP32 UART driver path.

#### Application API on MOS

The BDPP document specifies a MOS API reached through `RST &20`, including:

- capability/enabled/busy queries,
- enable and disable calls,
- preparing application-owned receive packets,
- queueing application-owned transmit packets,
- polling transmit/receive completion,
- retrieving received flags and sizes,
- stopping use of a packet slot,
- writing bytes into driver-owned packets, and
- flushing partial driver packets.

It describes foreground and ISR/background versions with explicit interrupt-state requirements. The ESP32 repository does not contain the complete MOS implementation; corresponding BDPP-capable MOS firmware is required for the feature to operate.

#### Negotiation and activation

BDPP is disabled at boot for compatibility. During the general-poll startup handshake, a protocol/version byte in the range `0x04..0x0F` is echoed with its high bit set to advertise ESP32 BDPP support. The code then enables CTS as well as RTS.

If both firmwares support BDPP, MOS's `bdpp`/`*bdpp` command sends:

```text
VDU 23,0,&A2,0
```

That tells the VDP to replace the legacy serial path with the BDPP/UHCI path. The documents warn that invoking only the VDU command, without switching MOS too, desynchronizes the two CPUs.

The documentation says BDPP cannot be left once enabled except by rebooting, even though the proposed MOS API lists a disable function. Treat reset-only operation as the tested/design constraint of this branch.

### Concrete ESP32-side BDPP capabilities

The `bdpp` branch implements these `VDU 23,0,&A2` operations:

- `0`: initialize/enter BDPP mode
- `1`: echo one byte into a designated application-owned response packet
- `2`: query free ESP32 memory for requested heap capability masks
- `3`: return bytes from an ESP32 address
- `4`: return 16-bit words from an ESP32 address
- `5`: return 32-bit words from an ESP32 address
- `6`: return VDP version metadata

It also adds buffered-command operation `&1B`, which copies a range from a VDP buffer back to the eZ80. The documented intent is to return as many as 4096 bytes across 16 application-owned packets of 256 bytes each. This is the clearest user-facing example of the capability missing from normal Agon communications: bulk VDP→application data rather than one-pixel-at-a-time queries routed through MOS variables.

Sample BBC BASIC programs exercise echo, transfer, and VDP-buffer retrieval.

### What Off The Cuff actually is

OTF is a retained-mode, scanline-rendered graphics engine.

Canonical VDP-GL/FabGL draws into one or two complete framebuffers and lets I2S DMA read those stored pixels. A full 800x600 framebuffer at one byte per pixel is too large for the ESP32's limited internal DMA-capable memory, especially if double buffering is wanted.

OTF instead allocates only eight scanline buffers. A highest-priority ESP32 task continually paints upcoming scanlines while I2S DMA displays other scanlines. At 800x600@60 Hz and a 40 MHz pixel clock, the documentation estimates about 6,336 ESP32 CPU cycles to prepare a scanline.

That design enables 64 colours at resolutions beyond the normal framebuffer limit, with 800x600x64 as the headline mode. It also includes experimental modes from 320x200 through 1368x768.

### OTF's retained scene model

The eZ80 sends commands to create persistent primitives on the ESP32. The ESP32 keeps those objects and redraws them every frame until told to change or delete them.

Supported or designed primitive types include:

- points,
- horizontal, vertical, and general lines,
- rectangles and solid rectangles,
- triangles and quadrilaterals,
- solid, masked, blended, referenced, and duplicated bitmaps,
- groups,
- tile arrays and planned tile maps,
- text areas with their own cursor, and
- planned 3D render primitives.

Primitives form a parent/child tree. Parent movement can move a whole group; parents can clip children; visibility can be changed for one object or a subtree. Primitive ID determines Z order.

This is a major bandwidth optimization as well as a graphics feature. After a ship, cursor, tile layer, or group is created, the eZ80 can move, hide, show, slice, or delete it with a compact command instead of resending all its pixels or redrawing the full frame.

### Dynamic code generation

OTF goes beyond a conventional retained display list. It generates Xtensa instructions at runtime for the specific primitives being drawn, reducing branches and decisions in the scanline critical path. Handwritten ESP32 assembly supplies common drawing routines.

For example, a horizontal span may generate a tailored sequence for its unaligned leading pixels, four-pixel groups, and trailing pixels. Bitmap data may be stored in several pre-shifted forms to support fast horizontal movement at different alignments.

The result trades memory and setup time for deterministic scanline speed.

### OTF command and mode integration

OTF uses `VDU 23,30,...` for primitive commands. Experimental mode numbers are grouped as:

- `32..47`: enter an OTF resolution with no initial primitive
- `48..63`: enter it with a full-screen black rectangle
- `64..79`: enter it with a full-screen text area

The OTF manager runs pinned to ESP32 core 1 at the maximum FreeRTOS task priority. Existing stream functions are wrapped so OTF can consume VDU input and send keyboard/mode responses through whichever stream is active—including BDPP when enabled.

### Important limitations of the early cut

The repository repeatedly labels OTF an early release. Its own issue list says:

- circles/ellipses, 3D rendering, and tile maps were incomplete,
- mouse-pointer support was absent,
- sound was untested and might be starved by the high-priority drawing task,
- some modes/timings cut off columns or otherwise misbehaved,
- large PSRAM-backed bitmaps could be too slow at high pixel clocks,
- partial transparency had sync-polarity limitations,
- normal `PLOT` and other legacy VDU integration was incomplete, and
- once an OTF mode was entered, reset was required to leave it.

OTF also requires every displayed pixel to be painted on every frame. Applications need a full-screen background primitive or equivalent coverage. Too many overlapping primitives on one scanline, interrupts, or slow PSRAM access can miss the scanline deadline and produce flickering or displaced lines.

Therefore OTF is best suited to scenes composed of persistent objects that move or toggle, not applications that intentionally regenerate a complete framebuffer every frame.

### Code-review cautions

The branch should be treated as experimental source, not as a fully verified protocol specification. Two static-review discrepancies are especially notable:

- BDPP command `2` computes `heap_caps_get_free_size(caps)` into a local `size`, but the following code takes a pointer to `caps` and transmits those bytes. The documentation says the response contains free-memory sizes, so this looks like an implementation bug.
- `bufferGetDataBytes()` documents responses up to 4096 bytes split among successive application packet indexes. In the inspected code, `pkt_idx` is not incremented and `start_app_response_packet()` is called only once. After the first 256-byte packet auto-flushes, subsequent writes appear able to fall back to an ordinary driver-owned packet. The documented multi-packet behavior therefore needs testing and likely correction.

These are static findings from the branch tip, not results of an ESP32/eZ80 hardware test.

### Branch map and status

As inspected on 2026-07-28:

| Branch | Head date | Role |
|---|---:|---|
| `origin/bdpp` | 2024-03-22 | BDPP transport, ESP32 UHCI driver, docs, and BASIC tests |
| `origin/otf-early-cut` | 2024-03-28 | Merges `bdpp`, compression, and the early OTF scanline/primitive engine |
| `origin/main` | 2025-04-26 | Upstream-oriented line at AgonPlatform v2.14.1-era code; contains neither BDPP nor OTF |
| `origin/pingo3D` | 2024-06-28 | Separate main-based Pingo 3D integration; does not descend from `otf-early-cut` |
| local canonical `/home/smith/Agon/agon-vdp` | 2026-04-19 | AgonPlatform v2.16.0, newer than TurboVega `main` |

`otf-early-cut` is about 31,000 added lines across 189 changed files relative to its main-line merge base. `bdpp` alone is about 3,000 added lines across 24 changed files.

The history supports this interpretation:

- BDPP began as a distinct transport branch.
- A placeholder for OTF appeared in BDPP.
- `otf-early-cut` later merged `bdpp` and added the rendering system.
- Neither experimental line was merged into the fork's present `main`.
- Subsequent experimental branches explore Pingo 3D, hardware/software sprites, shaders, drawing to bitmaps, and class rework, but should not automatically be described as part of the original BDPP/OTF implementation.

### Practical interpretation

The most accurate one-sentence description is:

> TurboVega's early OTF work combines an experimental, DMA-backed bidirectional packet transport with a retained-mode ESP32 graphics engine that renders VGA scanlines on demand, allowing applications to exchange bulk data and manipulate persistent high-resolution graphics objects without continuously pushing a framebuffer across the eZ80 serial link.

For pingoasm, BDPP's most relevant promise is direct, indexed application packet buffers and bulk VDP→eZ80 transfers. OTF's most relevant promise is compact scene updates after one-time asset/object upload. They solve different halves of the same system problem: transport overhead and rendering/memory overhead.

### Sources inspected

All findings above come from local Git objects; no branch checkout was performed:

- `origin/bdpp:video/bdpp/bdpp.md`
- `origin/bdpp:video/bdpp/packet.h`
- `origin/bdpp:video/bdpp/bdp_stream.h`
- `origin/bdpp:video/bdpp/bdp_protocol.cpp`
- BDPP changes to `video/video.ino`, `video/vdu_sys.h`, `video/vdu_buffered.h`, and `video/vdp_protocol.h`
- `origin/otf-early-cut:video/src/docs/otf_mode.md`
- `origin/otf-early-cut:video/src/docs/otf_strategy.md`
- `origin/otf-early-cut:video/src/docs/otf_critical.md`
- `origin/otf-early-cut:video/src/docs/otf_code_gen.md`
- `origin/otf-early-cut:video/src/docs/otf_issues.md`
- `origin/otf-early-cut:video/on_the_fly.h`
- local canonical upstream at `/home/smith/Agon/agon-vdp`
