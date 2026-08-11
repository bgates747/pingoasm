#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/../.." && pwd)"
emulator_profile="${project_root}/emulator"
emulator_launcher="/home/smith/Agon/mystuff/agon-dev-env/scripts/run_emulator.sh"
obs_app="com.obsproject.Studio"
obs_collection="Untitled"
obs_profile="Untitled"
obs_scene="Scene"
obs_config="${HOME}/.var/app/${obs_app}/config/obs-studio/basic/scenes/${obs_collection}.json"
mode="record"

usage() {
    cat <<'EOF'
Usage: apps/anim/capture-emulator.sh [--setup]

With no option, launch the Lara emulator, start OBS recording with its saved
PipeWire window source, and stop OBS cleanly when the emulator exits.

Use --setup once to launch both applications interactively. In OBS, replace
the existing source with Window Capture (PipeWire), select the Fab Agon
Emulator in the Wayland portal, fit it to the canvas, then close both programs.
EOF
}

if [[ $# -gt 1 ]]; then
    usage >&2
    exit 2
fi
if [[ $# -eq 1 ]]; then
    case "$1" in
        --setup) mode="setup" ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
fi

for required in "$emulator_launcher" "$emulator_profile"; do
    if [[ ! -e "$required" ]]; then
        printf 'Missing required emulator input: %s\n' "$required" >&2
        exit 1
    fi
done
if ! flatpak info "$obs_app" >/dev/null 2>&1; then
    printf 'OBS Flatpak is not installed: %s\n' "$obs_app" >&2
    exit 1
fi
if flatpak ps --columns=application 2>/dev/null | grep -Fxq "$obs_app"; then
    printf 'OBS is already running; close it before using this script.\n' >&2
    exit 1
fi

has_window_source() {
    python3 - "$obs_config" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(1)
document = json.loads(path.read_text(encoding="utf-8"))
raise SystemExit(
    0 if any(
        source.get("id") == "pipewire-window-capture-source"
        and source.get("settings", {}).get("RestoreToken")
        for source in document.get("sources", [])
    ) else 1
)
PY
}

run_setup() {
    printf '%s\n' \
        'Starting one-time Wayland window-capture setup.' \
        'In OBS add Window Capture (PipeWire), select Fab Agon Emulator,' \
        'fit it to the canvas, then close OBS and the emulator.'
    "$emulator_launcher" "$emulator_profile" &
    emulator_pid=$!
    sleep 2
    flatpak run "$obs_app" \
        --collection "$obs_collection" \
        --profile "$obs_profile" \
        --scene "$obs_scene" || true
    if kill -0 "$emulator_pid" 2>/dev/null; then
        kill -INT "$emulator_pid" 2>/dev/null || true
    fi
    wait "$emulator_pid" 2>/dev/null || true
    if has_window_source; then
        printf 'Wayland emulator-window binding saved.\n'
    else
        printf '%s\n' \
            'No saved PipeWire window source was found; setup is incomplete.' >&2
        exit 1
    fi
}

if [[ "$mode" == "setup" ]]; then
    run_setup
    exit 0
fi

if ! has_window_source; then
    printf '%s\n' \
        'OBS does not yet have a saved PipeWire window source for the emulator.' \
        'Run apps/anim/capture-emulator.sh --setup first.' >&2
    exit 1
fi

run_root="$(mktemp -d /tmp/pingo-anim-capture.XXXXXX)"
emulator_log="${run_root}/emulator.log"
obs_log="${run_root}/obs.log"
emulator_pid=""
obs_pid=""

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [[ -n "$emulator_pid" ]] && kill -0 "$emulator_pid" 2>/dev/null; then
        kill -INT "$emulator_pid" 2>/dev/null || true
        wait "$emulator_pid" 2>/dev/null || true
    fi
    if [[ -n "$obs_pid" ]] && kill -0 "$obs_pid" 2>/dev/null; then
        kill -INT "$obs_pid" 2>/dev/null || true
        for _ in {1..100}; do
            kill -0 "$obs_pid" 2>/dev/null || break
            sleep 0.1
        done
        if kill -0 "$obs_pid" 2>/dev/null; then
            printf 'OBS did not exit; stop recording and close it manually.\n' >&2
        else
            wait "$obs_pid" 2>/dev/null || true
        fi
    fi
    if [[ $status -eq 0 ]]; then
        rm -r -- "$run_root"
    else
        printf 'Capture logs retained at %s\n' "$run_root" >&2
    fi
    exit "$status"
}
trap cleanup EXIT INT TERM

"$emulator_launcher" "$emulator_profile" >"$emulator_log" 2>&1 &
emulator_pid=$!
sleep 2
if ! kill -0 "$emulator_pid" 2>/dev/null; then
    printf 'Emulator exited during startup.\n' >&2
    exit 1
fi

flatpak run "$obs_app" \
    --collection "$obs_collection" \
    --profile "$obs_profile" \
    --scene "$obs_scene" \
    --startrecording \
    --minimize-to-tray >"$obs_log" 2>&1 &
obs_pid=$!

recording_started=false
for _ in {1..300}; do
    if grep -q '==== Recording Start' "$obs_log"; then
        recording_started=true
        break
    fi
    if ! kill -0 "$obs_pid" 2>/dev/null; then
        printf 'OBS exited during startup.\n' >&2
        exit 1
    fi
    sleep 0.1
done
if [[ "$recording_started" != true ]]; then
    printf '%s\n' \
        'OBS did not confirm recording within 30 seconds.' \
        'A Wayland portal may be waiting for renewed permission.' >&2
    exit 1
fi

printf 'Recording started. Exit the emulator to finish the capture.\n'
set +e
wait "$emulator_pid"
emulator_status=$?
set -e
emulator_pid=""

kill -INT "$obs_pid" 2>/dev/null || true
for _ in {1..300}; do
    kill -0 "$obs_pid" 2>/dev/null || break
    sleep 0.1
done
if kill -0 "$obs_pid" 2>/dev/null; then
    printf 'OBS did not finalize within 30 seconds; close it manually.\n' >&2
    exit 1
fi
wait "$obs_pid" 2>/dev/null || true
obs_pid=""

if [[ $emulator_status -ne 0 && $emulator_status -ne 130 ]]; then
    printf 'Emulator exited with status %d.\n' "$emulator_status" >&2
    exit "$emulator_status"
fi
printf 'Recording finalized by OBS.\n'
