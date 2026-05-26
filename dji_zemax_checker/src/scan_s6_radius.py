from __future__ import annotations

import argparse
from pathlib import Path

from scan_radius import parse_radius_value, scan_radius


DEFAULT_S6_RADIUS_VALUES = (-80.0, -50.0, -30.0, 80.0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compatibility wrapper for S6 radius scan.")
    parser.add_argument(
        "--values",
        nargs="+",
        type=parse_radius_value,
        default=DEFAULT_S6_RADIUS_VALUES,
        help="S6 radius values to scan. Example: --values -80 -50 -30 80",
    )
    parser.add_argument("--quick-focus", action="store_true", help="Run OpticStudio Quick Focus after setting S6 radius.")
    parser.add_argument("--base-lens", type=Path, help="Optional base lens path to reload before each scan point.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    scan_radius(
        Path(__file__).resolve().parents[1],
        tuple(args.values),
        label="s6_radius_scan",
        surface=6,
        quick_focus=args.quick_focus,
        base_lens=args.base_lens,
    )
