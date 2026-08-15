#ifndef FSIM_AGONDEV_INTEROP_H
#define FSIM_AGONDEV_INTEROP_H

#include <limits.h>
#include <stddef.h>
#include <stdint.h>

enum interop_action {
    INTEROP_ACTION_IDLE = 0,
    INTEROP_ACTION_STAGE = 1,
    INTEROP_ACTION_COMMIT = 2,
    INTEROP_ACTION_CORRUPT = 0xfe,
    INTEROP_ACTION_BLOCKED = 0xff,
};

/*
 * One edge-filtered coverage group as consumed by the bounded policy A/B.
 * The accepted terrain implementation stores processed state separately;
 * this probe carries it beside the two counts so both selectors receive the
 * same byte-only, pointer-stable input.  Counts above the proven firmware
 * bound are invalid and are skipped rather than entering score arithmetic.
 */
typedef struct interop_group_record {
    uint8_t retiring;
    uint8_t entering;
    uint8_t processed;
} interop_group_record;

enum {
    INTEROP_GROUP_RETIRING_OFFSET = 0,
    INTEROP_GROUP_ENTERING_OFFSET = 1,
    INTEROP_GROUP_PROCESSED_OFFSET = 2,
    INTEROP_GROUP_BYTES = 3,
    INTEROP_GROUP_MAX_COUNT = 8,
    INTEROP_GROUP_MAX_SIDE = 14,
    INTEROP_GROUP_SCORE_BIAS = 16,
    INTEROP_GROUP_NONE = 0xff,
};

/*
 * This structure is a wire contract, not a compiler-native numeric model.
 * Multibyte values are byte arrays so both sides must perform explicit-width
 * access. Assembly writes only asm_stamp at the audited offset below.
 */
typedef struct interop_probe_state {
    uint8_t guard_head;
    uint8_t phase;
    uint8_t free_slots;
    uint8_t entering;
    uint8_t retiring;
    uint8_t generation_le[2];
    uint8_t cookie_le[3];
    uint8_t asm_stamp;
    uint8_t guard_tail;
} interop_probe_state;

enum {
    INTEROP_ASM_STAMP_OFFSET = 10,
    INTEROP_STATE_BYTES = 12,
};

_Static_assert(CHAR_BIT == 8, "AgonDev byte width changed");
_Static_assert(sizeof(uint8_t) == 1, "AgonDev uint8_t width changed");
_Static_assert(sizeof(uint16_t) == 2, "AgonDev uint16_t width changed");
_Static_assert(sizeof(int) == 3, "AgonDev int width changed");
_Static_assert(sizeof(uint24_t) == 3, "AgonDev uint24_t width changed");
_Static_assert(sizeof(void *) == 3, "AgonDev pointer width changed");
_Static_assert(sizeof(size_t) == 3, "AgonDev size_t width changed");
_Static_assert(sizeof(uint32_t) == 4, "AgonDev uint32_t width changed");
_Static_assert(offsetof(interop_group_record, retiring) ==
                   INTEROP_GROUP_RETIRING_OFFSET,
               "group retiring offset changed");
_Static_assert(offsetof(interop_group_record, entering) ==
                   INTEROP_GROUP_ENTERING_OFFSET,
               "group entering offset changed");
_Static_assert(offsetof(interop_group_record, processed) ==
                   INTEROP_GROUP_PROCESSED_OFFSET,
               "group processed offset changed");
_Static_assert(sizeof(interop_group_record) == INTEROP_GROUP_BYTES,
               "group record size changed");
_Static_assert(offsetof(interop_probe_state, guard_head) == 0,
               "guard_head offset changed");
_Static_assert(offsetof(interop_probe_state, phase) == 1,
               "phase offset changed");
_Static_assert(offsetof(interop_probe_state, free_slots) == 2,
               "free_slots offset changed");
_Static_assert(offsetof(interop_probe_state, entering) == 3,
               "entering offset changed");
_Static_assert(offsetof(interop_probe_state, retiring) == 4,
               "retiring offset changed");
_Static_assert(offsetof(interop_probe_state, generation_le) == 5,
               "generation offset changed");
_Static_assert(offsetof(interop_probe_state, cookie_le) == 7,
               "cookie offset changed");
_Static_assert(offsetof(interop_probe_state, asm_stamp) ==
                   INTEROP_ASM_STAMP_OFFSET,
               "assembly stamp offset changed");
_Static_assert(offsetof(interop_probe_state, guard_tail) == 11,
               "guard_tail offset changed");
_Static_assert(sizeof(interop_probe_state) == INTEROP_STATE_BYTES,
               "shared state size changed");

uint8_t interop_choose_action(const interop_probe_state *state);
uint8_t interop_select_feasible_group(const interop_group_record *groups,
                                      uint8_t group_count,
                                      uint8_t free_slots);
void asm_stamp_state(interop_probe_state *state, uint8_t stamp);
uint8_t asm_policy_round_trip(const interop_probe_state *state);
uint8_t asm_select_feasible_group(const interop_group_record *groups,
                                  uint8_t group_count,
                                  uint8_t free_slots);
uint16_t asm_return_u16(void);
uint24_t asm_return_u24(void);

#endif
