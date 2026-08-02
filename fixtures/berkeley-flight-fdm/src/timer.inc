; =============================================================================
; MOS elapsed-time sampler used by moveobj-local.
;
; Curated from tests/apps/_common/timer.inc. Simulation accumulates full 24-bit
; elapsed values from the 120 Hz MOS clock; render cadence is independent.
; =============================================================================

timestamp_now: dl 0
timestamp_old: dl 0
timestamp_chg: dl 0

; Update the global timestamp from the MOS 120 Hz system clock.
; returns: HL=elapsed ticks, DE=previous timestamp
; destroys: AF,HL,DE,IX
timestamp_tick:
    ld de,(timestamp_now)
    ld (timestamp_old),de
    MOSCALL mos_sysvars
    ld hl,(ix+sysvar_time)
    ld (timestamp_now),hl
    xor a
    sbc hl,de
    ld (timestamp_chg),hl
    ret
