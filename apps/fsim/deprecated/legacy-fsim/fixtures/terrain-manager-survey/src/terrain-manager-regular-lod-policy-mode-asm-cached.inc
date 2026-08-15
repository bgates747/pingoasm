; ASM_CACHED policy-client hooks.  The accepted edge filter is cached once per
; transition and the native selector consumes the same pending 3-byte records
; as C_GUARDED, but this mode never loads or calls CPOLICY.  Any internal
; contract fault is visible through the qualification latch and uses the
; accepted recomputing assembly selector for that selection.

    MACRO REGULAR_POLICY_MODULE_INITIALIZE
        xor a
        ret
    ENDMACRO

    MACRO REGULAR_POLICY_C_GUARDED_LATCH_CHECK
        .align 1
    ENDMACRO

    include "terrain-manager-regular-lod-policy-asm-cached-routines.inc"

    MACRO REGULAR_POLICY_BEGIN_TRANSITION
        call regular_policy_begin_transition
        jr c,regular_transition_begin_failed
    ENDMACRO

    MACRO REGULAR_POLICY_SELECT_DISPATCH
        jp regular_policy_select_feasible_group
    ENDMACRO

    MACRO REGULAR_POLICY_BEGIN_ROUTINE
        jp regular_policy_prepare_cached_descriptors_asm_cached
    ENDMACRO

    MACRO REGULAR_POLICY_SELECT_ROUTINE
        jp regular_policy_select_asm_cached
    ENDMACRO
