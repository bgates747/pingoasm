#include "interop.h"

#include <agon/mos.h>

static volatile uint8_t zero_initialized_probe;
static volatile uint8_t initialized_probe = 0x3c;

static const interop_group_record policy_ab_none[] = {
    {.retiring = 1, .entering = 1, .processed = 0},
};

static const interop_group_record policy_ab_processed[] = {
    {.retiring = 14, .entering = 1, .processed = 1},
    {.retiring = 3, .entering = 2, .processed = 0},
};

static const interop_group_record policy_ab_infeasible[] = {
    {.retiring = 14, .entering = 5, .processed = 0},
    {.retiring = 3, .entering = 2, .processed = 0},
};

static const interop_group_record policy_ab_score[] = {
    {.retiring = 5, .entering = 4, .processed = 0},
    {.retiring = 4, .entering = 2, .processed = 0},
};

static const interop_group_record policy_ab_enter_tie[] = {
    {.retiring = 6, .entering = 4, .processed = 0},
    {.retiring = 4, .entering = 2, .processed = 0},
};

static const interop_group_record policy_ab_retiring[] = {
    {.retiring = 3, .entering = 2, .processed = 0},
    {.retiring = 4, .entering = 2, .processed = 0},
};

static const interop_group_record policy_ab_source_tie[] = {
    {.retiring = 4, .entering = 2, .processed = 0},
    {.retiring = 4, .entering = 2, .processed = 0},
};

static void emit(const char *text) {
    while (*text != '\0') {
        (void)putch((uint8_t)*text);
        ++text;
    }
}

__attribute__((noinline))
uint8_t interop_choose_action(const interop_probe_state *state) {
    if (state == NULL || state->guard_head != 0x6d ||
        state->guard_tail != 0xa6 || state->cookie_le[2] != 0xab) {
        return INTEROP_ACTION_CORRUPT;
    }
    if (state->entering == 0) {
        return INTEROP_ACTION_IDLE;
    }
    if (state->entering > state->free_slots) {
        return INTEROP_ACTION_BLOCKED;
    }
    if (state->retiring > state->entering) {
        return INTEROP_ACTION_COMMIT;
    }
    return INTEROP_ACTION_STAGE;
}

/*
 * Select in the same order as regular_transition_select_feasible_group:
 * skip processed and capacity-infeasible groups; maximize retiring-entering;
 * then prefer fewer entering, more retiring, and finally the first source
 * record.  The final criterion is implemented by replacing the selection only
 * for a strict improvement.  All arithmetic remains inside the proven 0..14
 * count domain, so the firmware's +16 score bias cannot wrap.
 */
__attribute__((noinline))
uint8_t interop_select_feasible_group(const interop_group_record *groups,
                                      uint8_t group_count,
                                      uint8_t free_slots) {
    const interop_group_record *group = groups;
    uint8_t remaining = group_count;
    uint8_t source_index = 0;
    uint8_t selected_index = INTEROP_GROUP_NONE;
    uint8_t selected_score = 0;
    uint8_t selected_entering = 0;
    uint8_t selected_retiring = 0;

    if (groups == NULL || group_count > INTEROP_GROUP_MAX_COUNT) {
        return INTEROP_GROUP_NONE;
    }

    while (remaining != 0) {
        const uint8_t entering = group->entering;
        const uint8_t retiring = group->retiring;

        if (group->processed == 0 && entering <= free_slots &&
            entering <= INTEROP_GROUP_MAX_SIDE &&
            retiring <= INTEROP_GROUP_MAX_SIDE) {
            const uint8_t score = (uint8_t)(INTEROP_GROUP_SCORE_BIAS +
                                            retiring - entering);
            uint8_t choose = 0;

            if (selected_index == INTEROP_GROUP_NONE ||
                score > selected_score) {
                choose = 1;
            } else if (score == selected_score) {
                if (entering < selected_entering) {
                    choose = 1;
                } else if (entering == selected_entering &&
                           retiring > selected_retiring) {
                    choose = 1;
                }
            }

            if (choose != 0) {
                selected_index = source_index;
                selected_score = score;
                selected_entering = entering;
                selected_retiring = retiring;
            }
        }

        ++group;
        ++source_index;
        --remaining;
    }

    return selected_index;
}

static void compare_policy_selectors(const interop_group_record *groups,
                                     uint8_t group_count,
                                     uint8_t free_slots,
                                     uint8_t expected,
                                     uint8_t *failed) {
    const uint8_t c_selected =
        interop_select_feasible_group(groups, group_count, free_slots);
    const uint8_t asm_selected =
        asm_select_feasible_group(groups, group_count, free_slots);

    if (c_selected != expected || asm_selected != expected ||
        c_selected != asm_selected) {
        *failed = 1;
    }
}

int main(void) {
    interop_probe_state state = {
        .guard_head = 0x6d,
        .phase = 17,
        .free_slots = 4,
        .entering = 2,
        .retiring = 1,
        .generation_le = {0x34, 0x12},
        .cookie_le = {0xef, 0xcd, 0xab},
        .asm_stamp = 0,
        .guard_tail = 0xa6,
    };
    uint8_t failed = 0;

    if (zero_initialized_probe != 0 || initialized_probe != 0x3c) {
        failed = 1;
    }

    asm_stamp_state(&state, 0x5a);
    if (state.asm_stamp != 0x5a || state.guard_head != 0x6d ||
        state.guard_tail != 0xa6) {
        failed = 1;
    }
    if (asm_policy_round_trip(&state) != INTEROP_ACTION_STAGE) {
        failed = 1;
    }
    if (asm_policy_round_trip(NULL) != INTEROP_ACTION_CORRUPT) {
        failed = 1;
    }
    state.cookie_le[2] = 0;
    if (asm_policy_round_trip(&state) != INTEROP_ACTION_CORRUPT) {
        failed = 1;
    }
    state.cookie_le[2] = 0xab;
    if (asm_return_u16() != 0xbeef || asm_return_u24() != 0xabcdef) {
        failed = 1;
    }

    state.entering = 0;
    if (asm_policy_round_trip(&state) != INTEROP_ACTION_IDLE) {
        failed = 1;
    }

    state.entering = 5;
    if (asm_policy_round_trip(&state) != INTEROP_ACTION_BLOCKED) {
        failed = 1;
    }

    state.entering = 2;
    state.retiring = 3;
    if (asm_policy_round_trip(&state) != INTEROP_ACTION_COMMIT) {
        failed = 1;
    }

    compare_policy_selectors(policy_ab_none, 0, 4, INTEROP_GROUP_NONE,
                             &failed);
    compare_policy_selectors(NULL, 1, 4, INTEROP_GROUP_NONE, &failed);
    compare_policy_selectors(policy_ab_none, 9, 4, INTEROP_GROUP_NONE,
                             &failed);
    compare_policy_selectors(policy_ab_processed, 2, 2, 1, &failed);
    compare_policy_selectors(policy_ab_infeasible, 2, 2, 1, &failed);
    compare_policy_selectors(policy_ab_score, 2, 4, 1, &failed);
    compare_policy_selectors(policy_ab_enter_tie, 2, 4, 1, &failed);
    compare_policy_selectors(policy_ab_retiring, 2, 2, 1, &failed);
    compare_policy_selectors(policy_ab_source_tie, 2, 2, 0, &failed);

    if (failed != 0) {
        emit("FSIM AGONDEV INTEROP FAIL\r\n");
        return 1;
    }

    emit("FSIM AGONDEV INTEROP PASS\r\n");
    return 0;
}
