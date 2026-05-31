from __future__ import annotations

from typing import Any


def safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def close_all_analysis_windows(oss: Any) -> int:
    """Best-effort cleanup for OpticStudio analysis windows.

    ZOSPy wrappers can leave GUI analysis windows open when a script runs many
    Single Ray Trace / FFT MTF calls. This helper is intentionally defensive:
    it should never raise and should be safe to call after every analysis and
    again at script shutdown.
    """
    analyses = safe_get(oss, "Analyses")
    count = safe_get(analyses, "NumberOfAnalyses", 0) or 0
    try:
        number = int(count)
    except (TypeError, ValueError):
        return 0

    closed = 0
    # ZOS-API analysis indexing has varied across wrappers; try both common
    # ranges from high to low so closing one window does not shift the next.
    indexes = list(range(number, 0, -1)) + list(range(number - 1, -1, -1))
    seen: set[int] = set()
    for index in indexes:
        if index in seen:
            continue
        seen.add(index)
        try:
            analyses.CloseAnalysis(index)
            closed += 1
            continue
        except Exception:
            pass

        try:
            analysis = analyses.Get_AnalysisAtIndex(index)
        except Exception:
            continue
        for method_name in ("Close", "CloseAnalysis"):
            method = safe_get(analysis, method_name)
            if callable(method):
                try:
                    method()
                    closed += 1
                    break
                except Exception:
                    continue
    return closed
