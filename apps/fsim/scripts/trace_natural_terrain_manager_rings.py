#!/usr/bin/env python3
"""Qualify natural-terrain radius 2 -> 5 -> 0 publication and retirement."""

from __future__ import annotations

import capture_natural_terrain_manager_survey as natural
import trace_terrain_manager_rings as trace


def configure_shared_trace() -> None:
    """Bind the proven generic ring trace to the bounded NAT provider."""

    natural.configure_shared_capture()
    trace.TRACE_SCHEMA = "pingo-terrain-natural-manager-ring-trace-v1"
    trace.TRACE_REPORT_NAME = "natural-terrain-manager-ring-trace.json"
    trace.TRACE_LABEL = "natural terrain-manager ring trace"


def main() -> int:
    configure_shared_trace()
    return trace.main()


if __name__ == "__main__":
    raise SystemExit(main())
