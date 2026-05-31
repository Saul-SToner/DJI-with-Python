from __future__ import annotations

import argparse

import zospy as zp

from zosapi_cleanup import close_all_analysis_windows


def main() -> None:
    parser = argparse.ArgumentParser(description="Close all currently open OpticStudio analysis windows.")
    parser.parse_args()

    print("Connecting to OpticStudio via ZOSPy extension...", flush=True)
    try:
        zos = zp.ZOS()
        oss = zos.connect("extension")
    except Exception as exc:
        print("[ERROR] Failed to connect to OpticStudio through ZOSPy extension.", flush=True)
        print("[ERROR] Make sure OpticStudio is open and Programming > Interactive Extension is active.", flush=True)
        print(f"[ERROR] Original error: {type(exc).__name__}: {exc!r}", flush=True)
        raise SystemExit(1) from exc

    closed = close_all_analysis_windows(oss)
    print(f"closed_analysis_windows: {closed}", flush=True)


if __name__ == "__main__":
    main()
