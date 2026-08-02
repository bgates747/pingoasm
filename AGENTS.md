# Pingo Terrain handoff

Read `~/Agon/mystuff/agon-dev-env/codex/AGENTS.md` first. This repository owns
experimental Pingo terrain research, data-acquisition records, generators,
fixtures, benchmarks, and qualification evidence.

## Repository boundaries

- Do not modify `pingoasm` or `agon-vdp` merely to support an experiment here.
- Treat `pingoasm` as the reference for current eZ80 client architecture,
  assembly conventions, asset generation, and the one-render-in-flight model.
- Treat `agon-vdp` branch `pingowolf` as the reference firmware and renderer.
- Promote successful client work and firmware work through explicit,
  separately reviewed changes in their owning repositories.
- Preserve downloaded-source provenance, product identity, coverage, datum,
  license/public-domain status, and checksums. Ordinary builds should be
  offline and deterministic.
- Emulator-related changes require the Author's explicit human validation
  before commit or push.

## Session start

1. Read `docs/todo.md` and the latest pertinent development log.
2. Use this repository's `.venv` once one is established; never silently use
   system Python for project tools.
3. Inspect Git status before editing and preserve unrelated work.
4. Keep rejected experiments in dated logs or Git history, not in the active
   TODO.
