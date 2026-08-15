; ASM_ONLY policy-client hooks.  The fixed module is loaded and validated at
; startup, but transition selection remains the accepted assembly routine and
; pays no descriptor-cache or C-call cost.

    MACRO REGULAR_POLICY_MODULE_INITIALIZE
        .align 1
    ENDMACRO

    MACRO REGULAR_POLICY_C_GUARDED_LATCH_CHECK
        .align 1
    ENDMACRO

    MACRO REGULAR_POLICY_ASM_CACHED_PREPARE_ROUTINE
        .align 1
    ENDMACRO
    MACRO REGULAR_POLICY_ASM_CACHED_SELECT_ROUTINE
        .align 1
    ENDMACRO
    MACRO REGULAR_POLICY_ASM_CACHED_CALL_ROUTINE
        .align 1
    ENDMACRO
    MACRO REGULAR_POLICY_ASM_CACHED_NATIVE_ROUTINE
        .align 1
    ENDMACRO

    MACRO REGULAR_POLICY_BEGIN_TRANSITION
        call regular_policy_begin_transition
        jr c,regular_transition_begin_failed
    ENDMACRO

    MACRO REGULAR_POLICY_SELECT_DISPATCH
        jp regular_policy_select_feasible_group
    ENDMACRO

    MACRO REGULAR_POLICY_BEGIN_ROUTINE
        xor a
        ret
    ENDMACRO

    MACRO REGULAR_POLICY_SELECT_ROUTINE
        jp regular_transition_select_feasible_group_asm
    ENDMACRO
