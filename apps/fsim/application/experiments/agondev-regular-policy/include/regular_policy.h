#ifndef FSIM_AGONDEV_REGULAR_POLICY_H
#define FSIM_AGONDEV_REGULAR_POLICY_H

typedef unsigned char fsim_policy_u8;

enum {
    FSIM_POLICY_DESCRIPTOR_RETIRING_OFFSET = 0,
    FSIM_POLICY_DESCRIPTOR_ENTERING_OFFSET = 1,
    FSIM_POLICY_DESCRIPTOR_SOURCE_INDEX_OFFSET = 2,
    FSIM_POLICY_DESCRIPTOR_BYTES = 3,
    FSIM_POLICY_MAX_DESCRIPTORS = 38,
    FSIM_POLICY_MAX_SIDE = 14,
    FSIM_POLICY_INVALID = 0xfe,
    FSIM_POLICY_NO_SELECTION = 0xff,
};

/*
 * Assembly performs identity/edge filtering and supplies only this bounded
 * byte-only policy view.  Records are ordered by unique, strictly increasing
 * source_index values in the range 0..37.  Assembly independently revalidates
 * the returned encoded transition-group index before using the result.
 */
typedef struct fsim_regular_policy_descriptor {
    fsim_policy_u8 retiring;
    fsim_policy_u8 entering;
    fsim_policy_u8 source_index;
} fsim_regular_policy_descriptor;

_Static_assert(sizeof(unsigned char) == 1, "AgonDev byte width changed");
_Static_assert(sizeof(int) == 3, "AgonDev int width changed");
_Static_assert(sizeof(void *) == 3, "AgonDev pointer width changed");
_Static_assert(
    __builtin_offsetof(fsim_regular_policy_descriptor, retiring) ==
        FSIM_POLICY_DESCRIPTOR_RETIRING_OFFSET,
    "retiring offset changed");
_Static_assert(
    __builtin_offsetof(fsim_regular_policy_descriptor, entering) ==
        FSIM_POLICY_DESCRIPTOR_ENTERING_OFFSET,
    "entering offset changed");
_Static_assert(
    __builtin_offsetof(fsim_regular_policy_descriptor, source_index) ==
        FSIM_POLICY_DESCRIPTOR_SOURCE_INDEX_OFFSET,
    "source-index offset changed");
_Static_assert(sizeof(fsim_regular_policy_descriptor) ==
                   FSIM_POLICY_DESCRIPTOR_BYTES,
               "descriptor size changed");

fsim_policy_u8 fsim_regular_policy_select(
    const fsim_regular_policy_descriptor *descriptors,
    fsim_policy_u8 descriptor_count,
    fsim_policy_u8 free_slots);

#endif
