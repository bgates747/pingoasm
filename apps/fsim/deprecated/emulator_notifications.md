# Emulator stopping-point notifications

This project uses a visible Fab Agon emulator session as an optional operator
notification. The emulator boots directly into a small BBC BASIC application
whose screen explains that an agent reached a stopping point. The emulator's
startup sound is the audible notification.

Do not launch this notification merely because work reaches a natural stopping
point. Launch it only when the user explicitly requests an emulator ping or
notification. It is a final stopping-point alert, not an intermediate progress
indicator.

## Authoritative references

Read these before constructing or changing an alert profile:

1. `~/Agon/mystuff/agon-dev-env/codex/AGENTS.md` — canonical Agon-development
   policy, especially the explicit human-validation gate for every
   emulator-related change.
2. `~/Agon/mystuff/agon-dev-env/codex/emulator.md` — shared Fab installation,
   isolated profiles, launch scripts, CRLF autoexec files, and BBC BASIC
   interpreter inventory.
3. `~/Agon/mystuff/agon-hardware/AGENTS.md` — the complete proven
   stopping-point alert contract and the AgonWolf3D MapMaker boot arrangement.
4. `~/Agon/mystuff/agon-dev-env/scripts/setup_emulator.py` and
   `~/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh` — canonical profile
   construction and launch behavior. Reuse these mechanisms rather than
   inventing another Fab launcher.

The alert profile must be isolated and temporary. Never alter the tracked Fab
`sdcard` submodule, the normal Pingo emulator profile, a user-maintained
profile, the physical Agon SD card, or powered bench hardware just to display a
message.

## Required emulated SD layout

Keep the alert application outside `/bin`, for example:

```text
<temporary-profile>/
├── autoexec.txt
└── sdcard/
    ├── bin/
    │   └── bbcbasic.bin
    └── alert/
        └── ALERT.BAS
```

The normal profile setup may represent `sdcard` differently through links and
mappings; the requirements are that the emulated paths `/bin/bbcbasic.bin` and
`/alert/ALERT.BAS` resolve inside the isolated profile and that the profile
itself is not placed inside a mapped application directory.

## Proven boot sequence

Use this sequence in `autoexec.txt`, with CRLF line endings:

```text
cd /bin
load bbcbasic.bin
cd /alert
RUN . ALERT.BAS
```

`load bbcbasic.bin` stages the non-ADL BBC BASIC 3.0 interpreter while allowing
MOS to continue processing the remaining autoexec commands. Do not invoke bare
`bbcbasic`: that transfers control immediately and leaves the later `cd` and
`RUN` lines unprocessed. Do not substitute `basic.bin`; it is a different ADL
BBC BASIC build.

`ALERT.BAS` is plain ASCII BBC BASIC source, despite the `.BAS` extension. A
`.BBC` entry would ordinarily imply the tokenized format used by existing BBC
BASIC applications. Both `autoexec.txt` and `ALERT.BAS` must use CRLF endings;
LF-only BASIC source can fail at startup with `Bad program`.

## Alert screen contract

Use video mode 3 unless the message genuinely needs another mode. The visible
screen must state all four facts:

1. The agent has reached a stopping point.
2. What work just finished.
3. Whether the operator must do anything.
4. The exact requested action, or the next proposed gate when no immediate
   action is required.

Use ordinary sentence case and keep the wording short enough to remain legible.
End the program with a plain numbered `GOTO` self-loop so the final display
stays visible. Do not use `WAIT` or `REPEAT`; those constructs can produce
`Mistake` with the pinned non-ADL interpreter.

A minimal source shape is:

```basic
10 MODE 3
20 CLS
30 PRINT "Agent stopping point reached."
40 PRINT "Finished: <short description>."
50 PRINT "Operator action: <none or exact action>."
60 PRINT "Next gate: <short description>."
70 GOTO 70
```

Write this file with CRLF endings rather than copying the example verbatim with
the host editor's default newline mode.

## Launch and validation boundary

Launch through the canonical wrapper, passing the isolated profile path:

```bash
cd ~/Agon/mystuff/agon-dev-env
scripts/run_emulator.sh /absolute/path/to/the/temporary-alert-profile
```

Launch immediately before yielding the final response when the user requested
the notification. If the graphical emulator cannot be launched, state that
failure explicitly in the final response; do not claim the ping occurred.

Every emulator-related change—including this documentation, profiles,
autoexec content, mapped SD contents, launchers, firmware modules, and
snapshots—requires the Author's explicit human validation before commit or
push. Leave such changes uncommitted until that approval is given.

