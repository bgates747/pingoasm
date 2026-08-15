; C_GUARDED policy-client hooks.  A healthy C result controls selection after
; independent bounds/capacity validation.  Assembly runs only as a latched
; fault fallback.

    MACRO REGULAR_POLICY_MODULE_INITIALIZE
        .align 1
    ENDMACRO

    MACRO REGULAR_POLICY_C_GUARDED_LATCH_CHECK
        ld a,(regular_policy_qualification_failure)
        or a
        jp nz,regular_transition_select_feasible_group_asm
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
        jp regular_policy_select_c_guarded
    ENDMACRO
