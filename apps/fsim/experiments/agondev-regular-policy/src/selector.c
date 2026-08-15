#include "regular_policy.h"

/*
 * This is deliberately the whole C policy surface.  Assembly has already
 * removed processed groups, mapped recipe ordinals through regional edges,
 * and counted the owners that actually retire or enter.  C neither sees nor
 * changes world, slot, mesh, MOS, VDP, or fixed-point state.
 *
 * The ordering is the accepted regular-LOD ordering:
 *
 *   1. feasible with the currently inactive slots;
 *   2. greatest retiring - entering (shrink first);
 *   3. fewer entering;
 *   4. more retiring; and
 *   5. earlier encoded source index.
 *
 * The audited production domain bounds each side at fourteen, so adding the
 * historical score bias cannot wrap an eight-bit value.  The marshaller's
 * descriptors must have unique, strictly increasing source indices.  Any ABI
 * violation returns FSIM_POLICY_INVALID; a valid list with no feasible group
 * returns FSIM_POLICY_NO_SELECTION.  Assembly still revalidates every result.
 */
__attribute__((noinline, used, section(".text.entry")))
fsim_policy_u8 fsim_regular_policy_select(
    const fsim_regular_policy_descriptor *descriptors,
    fsim_policy_u8 descriptor_count,
    fsim_policy_u8 free_slots) {
    const fsim_regular_policy_descriptor *descriptor = descriptors;
    fsim_policy_u8 remaining = descriptor_count;
    fsim_policy_u8 selected_source = FSIM_POLICY_NO_SELECTION;
    fsim_policy_u8 selected_score = 0;
    fsim_policy_u8 selected_entering = 0;
    fsim_policy_u8 selected_retiring = 0;
    fsim_policy_u8 previous_source = 0;
    fsim_policy_u8 have_previous = 0;

    if (descriptors == (const fsim_regular_policy_descriptor *)0 ||
        descriptor_count > FSIM_POLICY_MAX_DESCRIPTORS) {
        return FSIM_POLICY_INVALID;
    }

    while (remaining != 0) {
        const fsim_policy_u8 retiring = descriptor->retiring;
        const fsim_policy_u8 entering = descriptor->entering;
        const fsim_policy_u8 source_index = descriptor->source_index;

        if (entering > FSIM_POLICY_MAX_SIDE ||
            retiring > FSIM_POLICY_MAX_SIDE ||
            source_index >= FSIM_POLICY_MAX_DESCRIPTORS ||
            (have_previous != 0 && source_index <= previous_source)) {
            return FSIM_POLICY_INVALID;
        }
        previous_source = source_index;
        have_previous = 1;

        if (entering <= free_slots) {
            const fsim_policy_u8 score =
                (fsim_policy_u8)(16 + retiring - entering);
            fsim_policy_u8 choose = 0;

            if (selected_source == FSIM_POLICY_NO_SELECTION ||
                score > selected_score) {
                choose = 1;
            } else if (score == selected_score) {
                if (entering < selected_entering) {
                    choose = 1;
                } else if (entering == selected_entering) {
                    if (retiring > selected_retiring) {
                        choose = 1;
                    } else if (retiring == selected_retiring &&
                               source_index < selected_source) {
                        choose = 1;
                    }
                }
            }

            if (choose != 0) {
                selected_source = source_index;
                selected_score = score;
                selected_entering = entering;
                selected_retiring = retiring;
            }
        }

        ++descriptor;
        --remaining;
    }

    return selected_source;
}
