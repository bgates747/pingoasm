# Dual-input and one-byte Pingo pixel pipeline

Status: dual input and one-byte working/output paths qualified on hardware
Date: 2026-07-28

## Objective

Restore RGBA2222 as the preferred Pingo UV texture format without removing
RGBA8888 compatibility.

The VDP bitmap referenced when creating a Pingo object already records its
pixel format. Pingo should use that metadata automatically; no new Pingo VDU
command or application-side format declaration is required.

Supported combinations:

```text
RGBA2222 texture -> RGBA2222 render target (native fast path)
RGBA8888 texture -> RGBA2222 render target
RGBA2222 texture -> RGBA8888 render target (legacy output compatibility)
RGBA8888 texture -> RGBA8888 render target (legacy compatibility)
```

Texture and target formats are independent and are discovered from existing VDP
bitmap metadata. No Pingo wire-protocol change is required.

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

## Why the global `Pixel` change was staged

The older extended branch selected a one-byte packed Pingo pixel globally:

```c
#define RGBA2222P

typedef struct {
    uint8_t c;
} Pixel;
```

That reduced renderer storage, but the old code also assumed every texture had
`Pixel *` stride. An RGBA8888 bitmap was consequently sampled one byte at a
time, which explains the repeated malformed output from legacy fixtures.

Texture storage format and renderer working/output format are separate
concerns. The dual-input milestone first made texture stride explicit. With
that prerequisite in place, restoring a one-byte working `Pixel` is safe.

## Implemented representation

Pingo's working/output pixel is now the VDP-native packed format:

```c
typedef struct {
    uint8_t c;
} Pixel;
```

`sizeof(Pixel) == 1` is enforced at compile time. A texture independently
describes the stride of its borrowed source bitmap:

```c
typedef uint8_t TextureFormat;
enum {
    TEXTURE_FORMAT_RGBA8888,
    TEXTURE_FORMAT_RGBA2222
};

typedef struct {
    Vec2i size;
    Pixel *frameBuffer;
    TextureFormat format;
} Texture;
```

The implementation uses `TEXTURE_FORMAT_RGBA8888` and
`TEXTURE_FORMAT_RGBA2222`. The essential requirements are:

1. Sampled texture data is not assumed to have `sizeof(Pixel)` stride.
2. Source format accompanies the data pointer and dimensions.
3. Sampling always returns one packed working `Pixel`.
4. Writable renderer textures are initialized explicitly as RGBA2222.

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
    return (Pixel){((const uint8_t *)texture->data)[index]};
}

const uint8_t *rgba = ((const uint8_t *)texture->data) + index * 4;
return pixelFromRGBA(rgba[0], rgba[1], rgba[2], rgba[3]);
```

The VDP/FabGL RGBA2222 byte layout is:

```text
AABBGGRR
```

RGBA8888 input is quantized using the VDP/FabGL top-two-bit convention:

```text
  0 ..  63 -> 0
 64 .. 127 -> 1
128 .. 191 -> 2
192 .. 255 -> 3
```

Legacy RGBA8888 output expands each two-bit channel with `0, 85, 170, 255`.

## Conversion performance

The earlier 1 KiB RGBA2222-to-RGBA8888 lookup is no longer needed: RGBA2222 is
the working representation and therefore the source fast path is a direct byte
read. RGBA8888 sources are packed per sampled texel. RGBA8888 output is
expanded after the renderer timer solely for compatibility.

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
2. Renderer working pixels are one-byte RGBA2222.
3. Command `5` maps the referenced `Bitmap::format`; its wire payload is
   unchanged.
4. Unsupported formats are rejected with a diagnostic.
5. RGBA2222 sampling is a direct packed-byte read; RGBA8888 sampling uses its
   correct four-byte stride.
6. The qualified U/V clamp and image-row conversion are unchanged.
7. Command `38` renders directly to the requested RGBA2222 target and safely
   expands to RGBA8888 when a legacy client supplies that target format.
8. A native test checks all 256 packed values, quantization boundaries,
   RGBA8888 stride, target writes, and all four UV corners.
9. Native module and dual-target smoke tests pass.
10. ESP32 firmware builds successfully.
11. The established `23,27,&22` one-byte bitmap-creation command is restored.

Hardware qualification completed:

1. RGBA2222 and RGBA8888 Cube textures both rendered correctly.
2. The direct-expansion RGBA2222 path repeated within 0.015%.
3. The shared lookup reduced RGBA2222 mean render time from 239.969 ms to
   232.720 ms.
4. The qualified RGBA8888 mean was 232.631 ms.
5. The remaining 0.038% difference is below the useful resolution of this
   experiment.

One compatibility hardware run used the new packed renderer with the old
deployed RGBA8888 target. It completed all 44 frames at 203.729 ms mean
(4.908 FPS), proving legacy target output still completed normally.

The regenerated all-RGBA2222 fixture then completed repeated direct-target
hardware runs. The clean canonical capture measured 203.626 ms mean
(4.911 FPS), a 12.50% frame-time reduction and 14.29% effective-FPS increase
versus the 232.720 ms source-only lookup baseline. The repeat differed by only
approximately 1 µs in mean renderer time.

## Regression fixtures

Cube fixtures use the same geometry and workload:

1. `cube-rgba8888` uses an RGBA8888 texture and RGBA8888 targets.
2. `cube-rgba2222` uses an RGBA2222 texture and RGBA2222 targets.

Profiles declare `texture_format` and `target_format` independently. The
all-packed executable is 2,681 bytes; the legacy executable is 2,687 bytes.

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

The qualified implementation reproduces the useful part of that change without
its stride bug: working pixels and native targets are packed, while both source
texture formats and legacy RGBA8888 targets remain supported.

The qualified implementation is `agon-vdp:pingo-codex` commit `a382ede`.

## Compatibility decision

RGBA2222 should become the preferred Pingo texture format. RGBA8888 remains a
first-class supported compatibility format rather than a deprecated or
best-effort path.

Applications continue to choose their VDP bitmap format using the existing
bitmap-creation protocol. Pingo discovers that format from the referenced
bitmap and requires no new command.
