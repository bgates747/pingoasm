OUTPUT_FORMAT("elf32-z80")
OUTPUT_ARCH(z80)
ENTRY(_fsim_regular_policy_select)

MEMORY
{
    POLICY (rx) : ORIGIN = 0x070000, LENGTH = 0x010000
}

SECTIONS
{
    .policy ORIGIN(POLICY) :
    {
        __fsim_regular_policy_image_start = .;

        /* 0x00: eight-byte signature, then the byte-sized ABI contract. */
        BYTE(0x46) BYTE(0x53) BYTE(0x49) BYTE(0x4d)
        BYTE(0x43) BYTE(0x50) BYTE(0x4f) BYTE(0x4c)
        BYTE(1)       /* format version */
        BYTE(1)       /* selector ABI version */
        BYTE(32)      /* header bytes */
        BYTE(3)       /* descriptor bytes */
        BYTE(38)      /* maximum descriptors */
        BYTE(14)      /* maximum owners on either side */
        BYTE(0xff)    /* no-selection return */
        BYTE(0xfe)    /* malformed-input return */

        /* 0x10: little-endian u32 fields, high byte zero for u24 values. */
        LONG(0x00070020)
        LONG(__fsim_regular_policy_image_end -
             __fsim_regular_policy_image_start)
        LONG(0x00070000)
        LONG(0x00080000)

        __fsim_regular_policy_header_end = .;
        KEEP(*(.text.entry))
        *(.text)
        *(.text.*)
        __fsim_regular_policy_image_end = .;
    } > POLICY

    .forbidden :
    {
        *(.rodata .rodata.*)
        *(.data .data.*)
        *(.bss .bss.*)
        *(COMMON)
        *(.init .init.* .init_array .init_array.*)
        *(.fini .fini.* .fini_array .fini_array.*)
        *(.ctors .ctors.* .dtors .dtors.*)
        *(.eh_frame .eh_frame.*)
    } > POLICY

    /DISCARD/ :
    {
        *(.comment)
        *(.note .note.*)
        *(.debug .debug.*)
        *(.gnu.attributes)
    }
}

ASSERT(__fsim_regular_policy_header_end == 0x070020,
       "regular-policy header is not exactly 32 bytes")
ASSERT(_fsim_regular_policy_select == 0x070020,
       "regular-policy entry moved from 0x070020")
ASSERT(SIZEOF(.forbidden) == 0,
       "regular-policy acquired forbidden data/CRT sections")
ASSERT(__fsim_regular_policy_image_end < 0x080000,
       "regular-policy image reaches or exceeds 0x080000")
