# Dual RGBA2222/RGBA8888 texture support proposal

Status: proposal, not implemented
Date: 2026-07-28

## Objective

Restore RGBA2222 as the preferred Pingo UV texture format without removing
RGBA8888 compatibility.

The VDP bitmap referenced when creating a Pingo object already records its
pixel format. Pingo should use that metadata automatically; no new Pingo VDU
command or application-side format declaration is required.

Initial supported combinations:

```text
RGBA2222 texture -> RGBA8888 render target
RGBA8888 texture -> RGBA8888 render target
```

Render-target format is deliberately outside this proposal.

## Rationale

For the same dimensions, RGBA2222 uses one byte per pixel rather than four.
It therefore offers:

1. One quarter of the serial transfer.
2. One quarter of stored texture size.
3. One quarter of texture memory traffic.
4. Better prospects for ESP32 cache behavior.
5. Direct reuse of the project's existing `.rgba2` assets.

RGBA8888 must remain supported because:

1. TurboVega and other legacy applications use it.
2. Existing applications must not break.
3. Some textures may genuinely benefit from greater color or alpha precision.
4. Compatibility fixtures must continue to exercise the historical path.

## Rejected approach: change Pingo's global `Pixel`

The older extended branch selected a one-byte packed Pingo pixel globally:

```c
#define RGBA2222P

typedef struct {
    uint8_t c;
} Pixel;
```

That reduced renderer storage but made `Pixel *` arithmetic advance one byte.
An RGBA8888 bitmap passed through that build was consequently sampled with the
wrong stride. This is consistent with the repeated, malformed output observed
when the older extended emulator received RGBA8888 fixtures.

Texture storage format and renderer working/output format are separate
concerns. Supporting one texture type must not redefine every Pingo pixel.

## Proposed representation

Retain Pingo's four-channel working/output pixel:

```c
typedef struct {
    uint8_t r;
    uint8_t g;
    uint8_t b;
    uint8_t a;
} Pixel;
```

Make a texture describe its source data explicitly:

```c
typedef enum {
    TEXTURE_RGBA2222,
    TEXTURE_RGBA8888
} TextureFormat;

typedef struct {
    Vec2i size;
    const void *data;
    TextureFormat format;
} Texture;
```

Exact names remain an implementation detail. The essential requirements are:

1. Texture data is not assumed to have `sizeof(Pixel)` stride.
2. Source format accompanies the data pointer and dimensions.
3. Sampling returns the common four-channel `Pixel`.
4. Render-target writes remain independent from source-texture reads.

If sharing one `Texture` structure between sampled textures and writable
framebuffers makes format handling ambiguous, introduce distinct source and
target types rather than adding unsafe casts.

## Bridge behavior

Pingo command `5` already creates an object from an object ID, mesh ID, and VDP
bitmap ID. The bridge obtains a `Bitmap` containing:

```cpp
bitmap->width
bitmap->height
bitmap->format
bitmap->data
```

The bridge should:

1. Accept `PixelFormat::RGBA2222`.
2. Accept `PixelFormat::RGBA8888`.
3. Translate the VDP format to Pingo's texture-format enum.
4. Bind the bitmap data without copying or expanding it.
5. Reject `Undefined`, `Native`, `Mask`, and other unsupported formats cleanly.
6. Log the rejected bitmap ID and format without corrupting the object.

The existing command envelope and object-creation payload remain unchanged.

## Sampler behavior

`texture_readF()` retains the Alpha 1 UV convention:

```text
x = clamp(u, 0, 1) * (width - 1)
y = (1 - clamp(v, 0, 1)) * (height - 1)
index = x + y * width
```

It then reads according to source format.

Conceptually:

```c
if (texture->format == TEXTURE_RGBA2222) {
    uint8_t packed = ((const uint8_t *)texture->data)[index];
    return expand_rgba2222(packed);
}

return ((const Pixel *)texture->data)[index];
```

The VDP/FabGL RGBA2222 byte layout is:

```text
AABBGGRR
```

Each two-bit channel expands to eight bits as:

```text
0 ->   0
1 ->  85
2 -> 170
3 -> 255
```

Alpha must be expanded by the same mapping rather than treated as merely
present/absent.

## Conversion performance

The first implementation may use shifts and the four-value expansion table.
Before optimization, benchmark this against the existing RGBA8888 path.

A likely optimization is a 256-entry packed-byte lookup:

```c
Pixel rgba2222_to_pixel[256];
```

This costs 1 KiB and converts an RGBA2222 texel with one indexed load. The
format branch is stable for an entire object and should be predictable.

Do not introduce a per-texel function pointer unless measurement shows it
outperforms the direct format branch on the ESP32.

The principal performance question is end-to-end frame time: conversion costs
may be outweighed by the fourfold reduction in source-memory bandwidth and
improved cache locality.

## Ownership and lifetime

The current bridge borrows VDP bitmap storage. Dual-format support must preserve
that ownership model:

1. Pingo does not free borrowed bitmap data.
2. A texture cannot outlive or silently retain a deleted/replaced bitmap.
3. Rebinding an object updates format, pointer, and dimensions together.
4. No temporary RGBA8888 expansion buffer is allocated for RGBA2222.

Expanding a complete RGBA2222 texture at object creation would preserve serial
bandwidth but discard most memory/cache advantages. It should remain a fallback
only if measured per-sample conversion is prohibitively expensive.

## Implementation sequence

1. Add an explicit source format and byte-addressable data pointer to sampled
   textures.
2. Keep the renderer's working `Pixel` and RGBA8888 render target unchanged.
3. Pass VDP bitmap format through command `5`.
4. Reject unsupported bitmap formats safely.
5. Implement correct RGBA2222 expansion in nearest-neighbor sampling.
6. Preserve the qualified U/V clamp and V-row conversion exactly.
7. Add host tests for all 256 RGBA2222 byte values and representative
   RGBA8888 pixels.
8. Add sampler tests for corners, `u/v = 1`, rectangular dimensions, and both
   formats.
9. Build and test hardware before refreshing the emulator.
10. Optimize conversion only after correctness and measurement.

## Regression fixtures

Create paired cube fixtures from the same `blenderaxes` source:

1. RGBA8888 cube using `blenderaxes.rgba8`.
2. RGBA2222 cube using `blenderaxes.rgba2`.

Use identical geometry, UVs, camera, transforms, and controls.

Hardware acceptance requires:

1. Both fixtures render visible, stable cubes.
2. Face selection and orientation remain identical.
3. Perspective-correct UV behavior remains identical.
4. Top and bottom faces retain their designed orientation.
5. RGBA2222 differs only through expected channel quantization.
6. Repeated switching between formats does not corrupt renderer state.
7. RGBA8888 HeavyTank continues to render correctly after RGBA2222 tests.
8. Ordinary non-Pingo VDP software still passes a smoke test.

After hardware passes:

1. Refresh the isolated Pingo emulator module.
2. Run the same canonical binaries through the live `apps` mapping.
3. Obtain explicit human validation before committing emulator-related state.

## Compatibility decision

RGBA2222 should become the preferred Pingo texture format. RGBA8888 remains a
first-class supported compatibility format rather than a deprecated or
best-effort path.

Applications continue to choose their VDP bitmap format using the existing
bitmap-creation protocol. Pingo discovers that format from the referenced
bitmap and requires no new command.
