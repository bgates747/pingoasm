# Flat-pattern dithering proposal

Status: **authorized experimental implementation; native tests passed, visual
qualification pending**. Firmware and emulator-coupled changes remain
uncommitted until Author review.

## Problem

Pingo's RGBA2222 target has four levels per color channel: 0, 85, 170, and
255. Scene illumination currently multiplies one flat-palette source color by
one diffuse-light scalar per triangle and then truncates each result back to a
two-bit channel. This creates large discontinuities. For example, a source
channel of 85 under 75 percent light becomes 63.75, truncates to 63, and then
quantizes to zero. Terrain colors built from the first nonzero channel level
therefore collapse to black across broad ranges of otherwise useful light.

Historical Pingo offered Bayer and Floyd--Steinberg dithering as full-frame
post-processes. Those paths revisited every output pixel and every RGB channel
after rendering, imposing substantial cost. The surviving implementation also
assumes four-byte RGBA pixels while modern Pingo uses packed one-byte RGBA2222,
so it is not a safe basis for renewed work.

Terrain needs intermediate apparent colors without restoring that full-frame
pass and without paying perspective-correct texture costs for a triangle whose
base color is already constant.

## Proposed model

Add an opt-in flat-pattern shading path. A triangle selects one material from a
small scene-defined color vocabulary. Pingo computes one illumination value for
the face, then uses the material ID and a quantized illumination band to select
a small precomputed repeating pattern. Rasterization indexes that pattern in
screen space.

```text
flat palette UV -> material ID -------------+
                                             -> pattern lookup -> pattern ID
face normal + scene light -> illumination --+

scanline Y -> pattern row
fragment X -> one RGBA2222 byte from that row
```

This is not perspective texture mapping. Pattern coordinates are output-pixel
coordinates; no UV interpolation, reciprocal-W recovery, texture-dimension
scaling, or perspective adjustment occurs.

## First pattern representation

The first experiment uses globally phased 4x4 ordered patterns:

```text
pattern pixel = patterns[pattern_id][y & 3][x & 3]
```

Each pattern contains sixteen native RGBA2222 output bytes. A scanline selects
one four-byte row once. Each depth-accepted fragment selects one of those four
bytes by its screen X phase.

Global screen-space phase is the baseline because it requires no interpolated
coordinate, aligns identical patterns across triangles and chunk boundaries,
remains deterministic for a stationary frame, and makes the first performance
result easy to interpret. World-, object-, or face-local phase may be studied
later, but can introduce interpolation cost, seams, or unstable clipping phase.

## Offline pattern generation

Patterns are generated offline, not searched or constructed during rendering.
The inputs are the scene's deliberately small set of natural material colors,
the illumination bands, the opaque RGBA2222 output palette, and a documented
ordered threshold matrix. The natural RGB material colors are the artistic
specification; they are not first reduced to single Agon colors.

Illumination primarily changes value rather than the identity of a surface.
For each material, the generator converts its selected RGB color to HSV, holds
hue and saturation constant, and varies value over the illumination bands:

```text
target(material, light) = HSV(Hbase, Sbase, Vbase * light)
```

Each HSV target is converted back to RGB. The generator then searches for a
spatially ordered mixture of native RGBA2222 pixels whose mean best represents
that target. HSV defines the desired color trajectory; the framebuffer and the
actual averaging performed by a dither remain RGB.

The objective must consider completed-pattern hue, saturation, and value error,
not minimize three channel errors independently. Independent channel
quantization can produce objectionable hue shifts such as the rose cast seen in
the first terrain palette. The search should normally prefer no more than two
native colors per pattern, with three permitted when two cannot adequately
preserve hue and saturation. The permitted native pair need not remain fixed
over the whole value ramp: useful palette neighbors can change near black.

The generator deduplicates identical 4x4 patterns. A lookup table maps
`material_id x illumination_band` to a compact pattern ID. The pattern library
stores each unique sixteen-byte pattern once.

The Berkeley scene currently uses 15 NLCD material colors. With 16 illumination
bands, its lookup therefore has 240 entries and no more than 240 unique
patterns. One-byte pattern IDs require 240 bytes for the lookup; the undeduped
4x4 pattern library requires at most 3,840 bytes, for a 4,080-byte raw maximum
before headers and alignment. Deduplication should reduce the pattern count,
especially at low values. This bounded scene vocabulary is intentional; this
experiment does not require patterns for all 64 opaque Agon colors. Alpha
behavior remains unchanged and is out of scope.

## Illumination bands

The first implementation uses 16 uniformly spaced illumination bands over
`0..1`. The selector fits in four bits, its lookup is small, and a 4x4 pattern
itself has only seventeen possible coverage counts including both endpoints.
Finer input bands would not necessarily produce finer visible luminance.

Band rounding, endpoint ownership, and unity behavior must be exact and tested.
Illumination `1.0` must resolve to the best pattern for the specified natural
material color; it need not be solid when that color is not native RGBA2222.
Self-illuminated meshes select that full-value band without further darkening.
Patterning at full value is an intentional part of the terrain's visual
aesthetic, not merely an error fallback. Optimizations must not force the unity
band to a single native color unless that material's authored color is itself
represented exactly and the solid result is visually accepted.

## Pattern resources and VDP ownership

The generated lookup and deduplicated pattern library are client resources,
loaded into VDP buffers before the mesh is rendered. They are not compiled into
the firmware and do not expand Pingo into a general runtime color search.

Experimental Pingo subcommand 49 binds:

1. the buffer containing packed 4x4 RGBA2222 patterns;
2. the buffer containing the material-by-illumination pattern-ID lookup;
3. the material count and illumination-band count; and
4. the mesh or render mode that consumes those resources.

Its fixed payload is `pattern_buffer:u16, lookup_buffer:u16,
pattern_count:u16, material_count:u8, band_count:u8`. The pattern source is one
exact block of `pattern_count * 16` opaque bytes; the material-major lookup is
one exact block of `material_count * band_count` one-byte pattern IDs. A valid
candidate is copied transactionally into private immutable Pingo storage. The
all-zero payload clears it; malformed, truncated, or allocation-failed
candidates preserve the preceding binding.

## Renderer integration

The flat-pattern path belongs beside current flat-palette face setup, not in a
post-render stage.

Per source triangle or clipped fan:

1. resolve the existing flat UV to a compact material ID;
2. retain the existing face-normal illumination calculation;
3. quantize illumination to one band;
4. resolve the pattern ID through the uploaded precomputed lookup; and
5. retain a pointer or compact reference to the selected pattern.

Per accepted scanline, select the four-byte row using `y & 3` and establish the
starting X phase. Per depth-accepted fragment, load one native pattern pixel
and write it directly to the RGBA2222 framebuffer.

The first implementation applies only to the direct RGBA2222 backend. Backend
callbacks must receive the selected native pixel or explicitly reject the
experimental mode; they must not apply illumination twice.

Clipped fan triangles derived from one source face must use the same base
color, illumination, pattern ID, and global phase. Clipping must not change the
apparent face color.

## Mode and protocol ownership

Do not silently change existing flat-palette mode. Its current solid output is
a regression oracle and fastest-path control.

The accepted experiment uses new mesh shading mode 2: textured mode 0,
flat-solid mode 1, and flat-pattern mode 2. This is explicit and keeps policy
mesh-owned. Flat-pattern mode interprets the clamped linear texel position of
the first face UV as a compact material ID; a 4x4 selector bitmap carries the
15 Berkeley materials. A future textured-dither policy is not implied by this
experiment.

## Performance hypothesis

Historical full-frame dithering performed work for every target pixel after
rendering. The proposed path visits only fragments that already pass coverage,
depth range, and depth testing.

Current illuminated flat shading performs channel extraction, three shade-LUT
lookups, shifts, and recomposition for every visible fragment. Flat-pattern
shading replaces that with a phase operation and one byte load from a pattern
chosen during face setup. It may approach or improve upon current solid
illuminated-flat performance, although physical hardware must decide.

Only after the clear implementation is qualified, possible refinements are a
carried `0..3` phase counter, a retained row pointer, packed 32-bit rows, and a
specialized solid-pattern path that preserves today's direct write.

## Visual risks

### Small and distant triangles

A triangle covering fewer than sixteen pixels may sample an unrepresentative
subset of a 4x4 pattern. As it moves through screen space, that subset can
shimmer or change apparent brightness. Inspect foreground, middle distance,
ridge, and the smallest far triangles separately.

Possible later remedies are 2x2 patterns, a solid fallback below a measured
projected-area threshold, or deterministic face-level stochastic selection for
far LODs. None belongs in the first implementation.

### Hue and chroma noise

Native palette mixtures can introduce colored speckles even when their mean RGB
is close to the target. The HSV value ramp and whole-pattern scoring are the
baseline defenses: hue and saturation error are explicit, and the optimizer is
penalized for unnecessary native colors. Candidate patterns still require
visual inspection because equal numerical error does not imply equal spatial
quality.

### Screen-door appearance

Large flat regions may expose the 4x4 matrix. The benchmark should compare one
standard Bayer arrangement with one rank rotation while preserving coverage.
Pattern choice must remain deterministic; random per-frame noise is forbidden.

## Initial qualification fixture

Use the accepted Berkeley terrain client because it supplies large dark
developed and vegetated regions, recognizable relief, flat-palette triangles,
encouraging hardware performance, and an existing solid-color baseline.

Keep its due-east sun at 30 degrees elevation. Capture ambient levels 25, 50,
and 75 percent for solid and patterned modes. The 75-percent case is especially
diagnostic because a native channel of 85 currently falls immediately below
the solid quantizer's first nonzero output.

For every candidate record:

1. executable, palette, pattern-library, and lookup sizes;
2. unique pattern count;
3. submitted and shaded fragments;
4. emulator deterministic target hash;
5. physical-hardware render cadence;
6. black-pixel and per-color histograms in selected terrain regions;
7. seams, screen-door structure, distant shimmer, and motion stability; and
8. exact firmware and client revisions.

The fixture must retain a solid-flat control so both paths use identical
geometry, camera, lighting, and source palette.

## Acceptance gates

The proposal succeeds only if:

1. dark terrain retains intermediate apparent brightness instead of broadly
   collapsing to black;
2. recognizable land-cover meaning and hill relief survive;
3. identical patterns cross chunk and triangle boundaries without seams;
4. ordinary camera motion produces no unacceptable shimmer;
5. clipping, depth, winding, and textured rendering are unchanged;
6. the mode is deterministic in native capture;
7. hardware performance is materially better than historical full-frame
   dithering and acceptable relative to solid flat shading; and
8. disabling the mode preserves the qualified solid path.

## Decisions required before implementation

Interactive design should resolve these in order:

1. new flat-pattern shading mode versus independent dither policy;
2. weights for hue, saturation, value, and native-color-count error;
3. whether two-color patterns suffice or the generator may use three;
4. one fixed Bayer matrix versus selectable ordered matrices;
5. exact VDP buffer layout and experimental calls; and
6. behavior for tiny projected triangles.

Recommended first answers are: an internal flat-pattern mode, 16 bands,
constant-hue-and-saturation HSV value ramps, whole-pattern optimization using
two native colors where possible and three where necessary, one fixed 4x4 Bayer
matrix, runtime-uploaded deduplicated tables, no tiny-triangle special case,
and experimental VDP calls until the hardware benchmark is understood.
