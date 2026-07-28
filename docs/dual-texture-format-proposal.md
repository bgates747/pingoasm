# Dual RGBA2222/RGBA8888 texture support proposal

Status: implemented and qualified on hardware
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

## Implemented representation

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
typedef uint8_t TextureFormat;
enum {
    TEXTURE_FORMAT_RGBA8888,
    TEXTURE_FORMAT_RGBA2222
};

typedef struct {
    Vec2i size;
    const void *data;
    TextureFormat format;
} Texture;
```

The implementation uses `TEXTURE_FORMAT_RGBA8888` and
`TEXTURE_FORMAT_RGBA2222`. The essential requirements are:

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

The initial shifts-and-masks implementation was measured before introducing a
256-entry packed-byte lookup:

```c
Pixel rgba2222_to_pixel[256];
```

The implemented table costs 1 KiB of shared firmware read-only storage and
converts an RGBA2222 texel with one indexed load. It is not duplicated per
texture. The format branch is stable for an entire object.

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

## Implementation and verification

Completed:

1. Textures carry an explicit source format while retaining the borrowed VDP
   bitmap pointer.
2. Renderer working pixels and render targets remain RGBA8888.
3. Command `5` maps the referenced `Bitmap::format`; its wire payload is
   unchanged.
4. Unsupported formats are rejected with a diagnostic.
5. RGBA2222 is expanded per sampled texel without another texture buffer.
6. The qualified U/V clamp and image-row conversion are unchanged.
7. A native test exhaustively checks all 256 RGBA2222 values, representative
   RGBA8888 values, and all four UV corners.
8. Native module build and smoke tests pass.
9. Both paired Cube fixtures assemble.
10. ESP32 firmware builds successfully.

Hardware qualification completed:

1. RGBA2222 and RGBA8888 Cube textures both rendered correctly.
2. The direct-expansion RGBA2222 path repeated within 0.015%.
3. The shared lookup reduced RGBA2222 mean render time from 239.969 ms to
   232.720 ms.
4. The qualified RGBA8888 mean was 232.631 ms.
5. The remaining 0.038% difference is below the useful resolution of this
   experiment.

Still required:

1. Run the existing non-Pingo smoke application.
2. Refresh and validate the emulator before committing emulator-related state.

## Regression fixtures

Paired Cube fixtures now use the same geometry and workload:

1. `cube-rgba8888` using `blenderaxes.rgba8`.
2. `cube-rgba2222` using `blenderaxes.rgba2`.

Their generated assembly differs only in provenance, texture filename, texture
byte count, and bitmap format byte. The RGBA2222 upload is 1,156 bytes; the
RGBA8888 upload is 4,624 bytes.

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

## Historical whole-pipeline result

The older benchmark notes in `docs/benchmarks/fpscomparisons.txt` confirm the
remembered larger gain:

```text
Earth RGBA8888 pipeline: 323–324 ms, approximately 3.10 FPS
Global RGBA2222P Pixel:  276–277 ms, approximately 3.62 FPS
```

That experiment changed Pingo's global working `Pixel` to one byte, affecting
framebuffer clearing, raster writes, and other working/output traffic as well
as source textures. It reduced frame time by roughly 14.5% and increased FPS
by roughly 17%.

The present milestone deliberately does not reproduce that invasive change.
It supports compact source textures while retaining the established RGBA8888
working framebuffer and render target. A subsequent milestone may restore a
one-byte working pipeline while preserving this dual-input compatibility.

## Compatibility decision

RGBA2222 should become the preferred Pingo texture format. RGBA8888 remains a
first-class supported compatibility format rather than a deprecated or
best-effort path.

Applications continue to choose their VDP bitmap format using the existing
bitmap-creation protocol. Pingo discovers that format from the referenced
bitmap and requires no new command.
