# Deprecated FSIM material

`legacy-fsim/` contains all FSIM work that is not on the critical path for the
approved combined C/assembly client. It is retained for history, provenance,
and selective recovery only.

Nothing below this directory may be imported, included, or invoked by the
active `application/` build. A useful implementation must be deliberately
promoted into `application/` with an explicit dependency and regression test;
deprecated paths are never implicit fallbacks.

The former emulator-notification convention is retained here as
`emulator_notifications.md` and was not edited during quarantine.
