; DUAL_STRICT policy-client hooks.  Assembly controls every result; the C
; result must match or the transition stops before prepare/stage.

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
        jp regular_policy_prepare_cached_descriptors
    ENDMACRO

    MACRO REGULAR_POLICY_SELECT_ROUTINE
        jp regular_policy_select_dual_strict
    ENDMACRO
