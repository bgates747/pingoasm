# Agon VDP UART transmit handoff

## Goal

The Agon VDP firmware already receives a byte stream from the eZ80 over UART and can transmit bytes back over the same UART. No new UART driver is required.

This note records the relevant implementation points for an agent adding a response or outbound message.

## Local repository reference

The following local repositories were discussed during this investigation:

| Purpose | Local path | Configured `origin` |
|---|---|---|
| Canonical Agon VDP firmware | `/home/smith/Agon/agon-vdp` | `https://github.com/AgonPlatform/agon-vdp` |
| TurboVega OTF/BDPP and experimental VDP fork | `/home/smith/Agon/TurboVega` | `https://github.com/TurboVega/agon-vdp-otf.git` |
| Canonical Agon MOS source | `/home/smith/Agon/agon-mos` | `https://github.com/AgonPlatform/agon-mos.git` |
| pingoasm application/project and documentation | `/home/smith/Agon/mystuff/pingoasm` | `https://github.com/bgates747/pingoasm.git` |

These URLs are the repositories' locally configured `origin` remotes. The TurboVega repository contains several experimental remote branches; BDPP is on `origin/bdpp`, the combined early OTF work is on `origin/otf-early-cut`, and the active checkout during this investigation was `pingo3D`.

## UART used by the VDP protocol

The protocol UART is `Serial2`, exposed through the macro:

```cpp
#define VDPSerial Serial2
```

It is configured by `setupVDPProtocol()` with:

- Baud rate: `1,152,000`
- Format: `8N1`
- ESP32 TX: GPIO 2
- ESP32 RX: GPIO 34
- ESP32 RTS: GPIO 13
- ESP32 CTS: GPIO 14
- RX buffer: 256 bytes

Source locations in the `agon-vdp` repository:

- `video/vdp_protocol.h`: `VDPSerial`, setup, and flow-control configuration
- `video/agon.h`: `UART_BR`, pin assignments, and buffer constants
- `video/video.ino`: constructs `VDUStreamProcessor` with `&VDPSerial`

Do not use `DBGSerial` for communication with the eZ80. `DBGSerial` is UART0, configured separately at 115200 baud for debugging.

## Simplest way to send one raw byte

Code with access to the global `processor` can call:

```cpp
processor->writeByte(0x42);
```

`VDUStreamProcessor::writeByte()` is public and writes through its current output stream:

```cpp
inline void writeByte(uint8_t b) {
    if (outputStream) {
        outputStream->write(b);
    }
}
```

The processor's original input and output streams both refer to `VDPSerial`, so this sends the byte back to the eZ80. Using `writeByte()` also respects any temporary output-stream redirection performed by the buffered-command system.

To send several raw bytes:

```cpp
const uint8_t response[] = { 0x12, 0x34, 0x56 };

for (uint8_t byte : response) {
    processor->writeByte(byte);
}
```

If stream redirection is intentionally irrelevant, code can technically write directly with `VDPSerial.write(...)`, but `processor->writeByte(...)` is the better integration point inside the VDU processor.

## Preferred protocol-framed response

Existing firmware responses normally use `VDUStreamProcessor::send_packet()`:

```cpp
uint8_t payload[] = { 0x12, 0x34, 0x56 };
processor->send_packet(packetCode, sizeof(payload), payload);
```

The bytes placed on the UART are:

```text
0x80 + packetCode
payloadLength
payload bytes...
```

The implementation is in `video/vdu_stream_processor.h`:

```cpp
void VDUStreamProcessor::send_packet(
    uint8_t code,
    uint16_t len,
    uint8_t data[]
) {
    writeByte(code + 0x80);
    writeByte(len);
    for (int i = 0; i < len; i++) {
        writeByte(data[i]);
    }
}
```

There is only one length byte on the wire even though the C++ parameter is `uint16_t`. Keep an individual packet payload at 255 bytes or less unless the protocol and receiver are deliberately extended.

Packet IDs are defined in `video/agon.h`. Existing examples include:

- `PACKET_GP` (`0x00`): general-poll response
- `PACKET_KEYCODE` (`0x01`): keyboard data
- `PACKET_MODE` (`0x06`): display-mode information
- `PACKET_ECHO` (`0x0A`): echoed input
- `PACKET_ECHO_END` (`0x0B`): echo completion

For a new message type, confirm that the chosen packet ID is unused and add matching receiver-side parsing in MOS/pingoasm. If compatibility with existing MOS packet parsing matters, follow the existing packet definitions and payload byte order.

## Concrete request/response example

The general-poll command is the clearest existing example. In `video/vdu_sys.h`, `sendGeneralPoll()` reads one byte from the incoming command and sends it back as a `PACKET_GP` payload:

```cpp
void VDUStreamProcessor::sendGeneralPoll() {
    auto b = readByte_t();
    if (b == -1) {
        return;
    }

    uint8_t packet[] = { static_cast<uint8_t>(b) };
    send_packet(PACKET_GP, sizeof(packet), packet);
}
```

The actual source also updates VDP variables and invokes buffer callbacks. A new protocol response may need equivalent callback/variable integration depending on its purpose.

## Flow-control caveat

Startup calls:

```cpp
setVDPProtocolDuplex(false);
```

In this codebase, the `duplex` setting selects hardware flow-control behavior:

```cpp
VDPSerial.setHwFlowCtrlMode(
    duplex ? HW_FLOWCTRL_CTS_RTS : HW_FLOWCTRL_RTS,
    64
);
```

Thus the default enables RTS receive-side throttling only. Calling:

```cpp
setVDPProtocolDuplex(true);
```

enables both CTS and RTS. This matters if the VDP must honor the eZ80's readiness signal while transmitting asynchronously or in larger bursts.

The feature can also be controlled through the `VDPVAR_FULL_DUPLEX` VDP variable; see `video/vdp_variables.h`.

Do not assume the name means the UART electrical data path is incapable of transmitting at startup. Existing startup responses, keyboard events, mouse events, and query replies already transmit using the default setting. The practical distinction here is RTS-only versus CTS+RTS hardware flow control.

## Implementation recommendation

For a small response to an incoming command:

1. Define or select a packet ID.
2. Assemble a payload no larger than the receiver supports. Although the VDP wire format has a one-byte length, stock MOS accepts at most 16 payload bytes.
3. Call `send_packet(packetCode, sizeof(payload), payload)`.
4. Add matching parsing on the eZ80/pingoasm side.
5. Use `writeByte()` only when the peer explicitly expects unframed raw bytes.
6. Test whether CTS+RTS mode is required for unsolicited or sustained outbound traffic.

Also avoid writing diagnostic text onto `VDPSerial`: it would be interpreted as protocol traffic. Debug messages should continue to use `DBGSerial`.

## Stock MOS receive constraints

The canonical MOS source inspected at `/home/smith/Agon/agon-mos` is version 3.0.2. Its UART0 interrupt handler feeds every byte received from the VDP into the fixed VDP protocol parser in `src/vdp_protocol.asm`.

The stock packet format is:

```text
0x80 + packetCode
payloadLength
payload bytes...
```

MOS uses a single internal staging buffer named `_vdp_protocol_data`. Its size is:

```asm
VDPP_BUFFERLEN: EQU 16
```

If the declared payload length exceeds 16, MOS discards the packet. For accepted packets, MOS copies the payload into this fixed buffer and dispatches through a hard-coded handler table. It normally translates the packet into fields in the MOS system-variable block.

The implemented stock packet types are:

- `0x00`: general poll
- `0x01`: keyboard
- `0x02`: cursor position
- `0x03`: screen character
- `0x04`: screen pixel
- `0x05`: audio acknowledgement
- `0x06`: mode information
- `0x07`: RTC
- `0x08`: keyboard state
- `0x09`: mouse

Packet types `0x0A` and above are outside the MOS dispatch table and are ignored after their payload has been received. Adding a new packet ID on the VDP alone therefore does not make its data visible to a stock-MOS application.

There is no stock API equivalent to:

```c
receive_vdp_packet(destination, capacity);
```

Applications can obtain a pointer to the MOS system-variable block, but cannot configure the normal VDP packet parser to copy arbitrary responses to an application-supplied address.

## Reserved and unused slots

The VDP variable namespace is deliberately sparse. Potential private-extension areas include:

- unused IDs within the `0x0200..0x02FF` system-settings range;
- gaps above `0x0300`;
- `0x0111`, currently commented as prospective echo settings; and
- `0x024C..0x024F`, explicitly reserved for the mouse area.

Those are ESP32-resident VDP variables. Stock MOS has no generic command for reading an arbitrary VDP variable, so allocating an ID does not itself provide a return channel.

On the MOS side:

- system-variable offsets `0x20..0x21` are explicitly spare;
- VDP protocol-completion flag bit 7 is unused;
- the source contains a commented-out `VDPP_FLAG_BUFFERED`/`vdp_pflag_buffered` definition for that bit.

These slots could support a small official extension, but using them through the normal packet dispatcher would require modifying and rebuilding MOS.

The current MOS build requires Zilog Developer Studio II for eZ80Acclaim! 5.3.5. It is a Windows application containing the proprietary compiler and assembler. The repository has no alternative open-source full build workflow, so avoiding a custom MOS build is a material design goal.

## Stock-MOS keyboard callback path

The most promising stock-MOS mechanism is the existing keyboard-packet callback registered through `mos_setkbvector` (MOS API `0x1D`).

When MOS receives packet type `PACKET_KEYCODE` (`0x01`) and a user callback is installed, it calls that callback with:

```text
DEU = address of MOS's 16-byte _vdp_protocol_data buffer
```

MOS then skips normal processing of that keyboard packet. Application callback code can immediately copy the payload from MOS's staging buffer to any application-owned eZ80 RAM address.

The resulting path is:

```text
ESP32 sends PACKET_KEYCODE with at most 16 payload bytes
    ↓
MOS UART0 ISR and fixed protocol parser
    ↓
MOS _vdp_protocol_data[16]
    ↓
application keyboard callback
    ↓
arbitrary application-owned eZ80 RAM buffer
```

This is not a general streaming API, but it provides arbitrary-buffer delivery without modifying or rebuilding MOS.

### Constraints

- The complete packet payload cannot exceed 16 bytes.
- MOS does not pass the received payload length to the callback.
- The callback intercepts genuine keyboard packets as well as custom packets.
- MOS owns only one staging buffer, so the callback must consume/copy a chunk before another packet overwrites it.
- Sequencing, total length, acknowledgements, checksums, timeout recovery, and cancellation must be implemented by the VDP and application.
- Callback code runs from the UART receive interrupt path and must be short, deterministic, and careful about register preservation and interrupt conventions.

### Suggested custom chunk

Use a fixed 16-byte payload so the callback does not need a length argument. One conservative layout is:

```text
byte 0    magic byte 1
byte 1    magic byte 2
byte 2    transfer/channel ID
byte 3    sequence number
byte 4    flags or valid-data length
bytes 5-15 data (11 bytes)
```

A smaller header could leave 12 or 13 data bytes. Two magic bytes reduce the chance of confusing a genuine keyboard event with transfer data. The exact balance should be selected after defining acknowledgement and end-of-transfer behavior.

The callback should:

1. Check the magic/header.
2. If it is a normal keyboard packet, either handle it normally or pass equivalent information to the application.
3. For a transfer packet, validate the transfer ID and expected sequence.
4. Copy the data bytes into the current destination pointer.
5. Advance the pointer and update received length/state.
6. Set a lightweight acknowledgement/ready flag for foreground code to transmit outside the ISR.

Avoid transmitting a substantial acknowledgement directly from the callback unless UART/interrupt reentrancy has been proven safe. A stop-and-wait protocol driven from foreground application code is slower but safer for the first implementation.

### Recommended proof of concept

1. Install an application callback using `mos_setkbvector`.
2. Send a new VDU request containing the requested VDP object/range and a transfer ID.
3. Have the VDP return one fixed-size custom `PACKET_KEYCODE`.
4. Verify that the callback recognizes and copies it into a caller-selected RAM buffer.
5. Add a foreground acknowledgement and send the next chunk only after acknowledgement.
6. Add sequence checking, final length, timeout, abort, and checksum handling.
7. Restore the previous keyboard callback when the transfer ends.

This is currently the safest and smallest path to proving VDP-to-arbitrary-eZ80-buffer transfer while retaining stock MOS.

## UART0 interrupt-vector alternative

MOS also exposes `mos_setintvector` (MOS API `0x14`). UART0 uses interrupt vector `0x18`, so an application can replace the UART0 handler and receives the previous handler address.

A custom handler could read UART0 and stream bytes directly into an arbitrary application buffer, removing the 16-byte protocol-payload limit. However, while installed it would take responsibility for all VDP-originated traffic:

- packet framing and error recovery;
- keyboard and mouse events;
- ordinary VDP query responses;
- UART FIFO handling;
- interrupt conventions and acknowledgement; and
- restoring or safely chaining to the original MOS handler.

This is possible without rebuilding MOS, but it amounts to implementing a temporary receive driver inside the application. It should remain the fallback if the keyboard callback's small chunks are demonstrably inadequate.

## Relationship to BDPP

TurboVega's experimental BDPP solves this problem more generally with application-owned packets. An eZ80 application registers an arbitrary destination address and capacity under one of 16 packet indexes; a VDP response carries the matching index, and the BDPP MOS driver writes the payload into that registered buffer.

That design supports 256-byte packets, logical streams, and DMA-backed ESP32 transport, but requires coordinated non-stock firmware on both MOS and VDP. The keyboard-callback design borrows its useful concepts—indexed transfers, sequencing, and explicit application ownership—while remaining inside the 16-byte stock MOS protocol.
