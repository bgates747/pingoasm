# Pingo Terrain handoff

Read `~/Agon/mystuff/agon-dev-env/codex/AGENTS.md` first. The sole active
application is `application/`; everything under `deprecated/` is historical
and must not be used by the active build.

## Repository boundaries

- Keep FSIM-specific work inside `pingoasm/apps/fsim`; do not modify sibling
  applications or shared pingoasm code merely to support an experiment here.
- Treat shared `pingoasm` code as the reference for current eZ80 client
  architecture, assembly conventions, asset generation, and the
  one-render-in-flight model.
- Treat `agon-vdp` branch `pingowolf` as the reference firmware and renderer.
- Promote successful client work and firmware work through explicit,
  separately reviewed changes in their owning repositories.
- Preserve downloaded-source provenance, product identity, coverage, datum,
  license/public-domain status, and checksums. Ordinary builds should be
  offline and deterministic.
- Emulator-related changes require the Author's explicit human validation
  before commit or push.

## Session start

1. Read `application/TODO.md` and `application/README.md`.
2. Use `application/.venv`; never silently use
   system Python for project tools.
3. Inspect Git status before editing and preserve unrelated work.
4. Keep rejected or superseded work under `deprecated/` or in Git history, not
   in the active TODO or application dependency graph.

## Network access authority

For access between development machines, read the [canonical network instructions](https://github.com/bgates747/agon-dev-env/blob/feature/standardized-deployment/codex/environment.md#ssh-between-development-machines) in `~/Agon/mystuff/agon-dev-env/codex/environment.md` and its machine-local `.local/ssh-001/CONNECTIONS.md` guide. They own current hostnames, discovery, SSH identities, sudo, and LAN shares. Do not duplicate access recipes or revive old aliases, addresses, or share mappings in this project. Project-specific device/protocol and bench-safety instructions remain local.
