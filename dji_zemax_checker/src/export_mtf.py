from __future__ import annotations

import weakref
from pathlib import Path
from typing import Any

from pandas import DataFrame

from zospy.analyses.base import OnComplete
from zospy.analyses.mtf import FFTMTF

from analysis_debug import update_analysis_debug
from run_files import run_file, run_id_from_file
from zosapi_cleanup import close_all_analysis_windows


def _warnings_path(output_path: Path) -> Path:
    run_id = run_id_from_file(output_path, "mtf_fft")
    return run_file(output_path.parent, run_id, "warnings") if run_id else output_path.parent / "warnings.log"


def _append_warning(output_path: Path, message: str) -> None:
    with _warnings_path(output_path).open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def _fft_mtf_analysis() -> FFTMTF:
    return FFTMTF(
        sampling="32x32",
        surface="Image",
        wavelength="All",
        field="All",
        # Keep the exported FFT MTF curve dense and bounded. OpticStudio's default
        # maximum can return sparse/adaptive samples that flatten narrow tangential
        # notches to exact zero around 25-30 lp/mm. The diagnostic script confirmed
        # that a bounded 0-80 lp/mm curve does not show a true zero crossing.
        maximum_frequency=80.0,
        use_polarization=False,
        use_dashes=False,
        show_diffraction_limit=False,
    )


def _analysis_messages(analysis: Any) -> list[str]:
    try:
        return [f"{message.ErrorCode}: {message.Message}" for message in analysis.analysis.messages]
    except Exception:
        return []


def _analysis_header(analysis: Any) -> list[str]:
    try:
        return list(analysis.analysis.header_data)
    except Exception:
        return []


def _run_fft_mtf_data_only(oss: Any, output_path: Path) -> DataFrame | None:
    """Bypass AnalysisResult metadata construction when OpticStudio returns IA_ without metadata."""
    analysis = _fft_mtf_analysis()
    debug: dict[str, Any] = {}
    run_id = run_id_from_file(output_path, "mtf_fft")
    try:
        analysis._oss = weakref.proxy(oss)
        analysis._check_mode()
        try:
            analysis._create_analysis()
            debug["fftmtf_analysis_created"] = True
        except Exception as exc:
            debug["fftmtf_error_message"] = f"FFTMTF analysis creation failed: {type(exc).__name__}: {exc!r}"
            _append_warning(output_path, debug["fftmtf_error_message"])
            return None

        try:
            data = analysis.run_analysis()
            debug["fftmtf_analysis_ran"] = True
            debug["fftmtf_messages"] = _analysis_messages(analysis)
            debug["fftmtf_header"] = _analysis_header(analysis)
        except Exception as exc:
            debug["fftmtf_error_message"] = f"FFTMTF analysis run failed: {type(exc).__name__}: {exc!r}"
            _append_warning(output_path, debug["fftmtf_error_message"])
            return None

        try:
            results = analysis.analysis.Results
            debug["fftmtf_has_results"] = results is not None
            debug["fftmtf_num_datagrids"] = getattr(results, "NumberOfDataGrids", None)
            debug["fftmtf_num_dataseries"] = getattr(results, "NumberOfDataSeries", None)
            if results is not None and getattr(results, "NumberOfDataSeries", 0) == 0:
                _append_warning(output_path, "FFTMTF DataSeries empty.")
            if results is not None and getattr(results, "NumberOfDataGrids", 0) == 0:
                _append_warning(output_path, "FFTMTF DataGrids empty.")
        except Exception as exc:
            debug["fftmtf_has_results"] = False
            debug["fftmtf_error_message"] = f"FFTMTF GetResults failed: {type(exc).__name__}: {exc!r}"
            _append_warning(output_path, debug["fftmtf_error_message"])

        debug["fftmtf_dataframe_success"] = isinstance(data, DataFrame) and not data.empty
        if debug["fftmtf_dataframe_success"]:
            debug["fftmtf_error_message"] = None
        return data
    except Exception as exc:
        debug["fftmtf_error_message"] = f"FFTMTF data-only fallback failed: {type(exc).__name__}: {exc!r}"
        _append_warning(output_path, debug["fftmtf_error_message"])
        return None
    finally:
        if run_id:
            update_analysis_debug(output_path.parent, run_id, debug)
        try:
            analysis._complete(OnComplete.Close)
        except Exception:
            pass
        close_all_analysis_windows(oss)


def export_mtf(oss: Any, output_path: Path, run_metadata: dict[str, Any] | None = None) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = (run_metadata or {}).get("run_id") or run_id_from_file(output_path, "mtf_fft")
    debug: dict[str, Any] = {
        "fftmtf_analysis_created": False,
        "fftmtf_analysis_ran": False,
        "fftmtf_has_results": False,
        "fftmtf_num_datagrids": None,
        "fftmtf_num_dataseries": None,
        "fftmtf_dataframe_success": False,
        "fftmtf_error_message": None,
    }

    try:
        result = _fft_mtf_analysis().run(oss)
        debug["fftmtf_analysis_created"] = True
        debug["fftmtf_analysis_ran"] = True
        debug["fftmtf_has_results"] = True
        data = result.data
        close_all_analysis_windows(oss)
    except AttributeError as exc:
        close_all_analysis_windows(oss)
        message = str(exc)
        if "metadata" not in message:
            debug["fftmtf_error_message"] = (
                f"FFTMTF analysis run failed: {type(exc).__name__}: {exc!r}"
            )
            _append_warning(output_path, debug["fftmtf_error_message"])
            update_analysis_debug(output_path.parent, run_id, debug)
            return False

        _append_warning(
            output_path,
            "FFTMTF AnalysisResult metadata access failed; retrying data-only extraction. "
            f"Original error: {type(exc).__name__}: {exc!r}",
        )
        debug["fftmtf_error_message"] = f"FFTMTF metadata access failed: {type(exc).__name__}: {exc!r}"
        update_analysis_debug(output_path.parent, run_id, debug)
        data = _run_fft_mtf_data_only(oss, output_path)
    except Exception as exc:
        close_all_analysis_windows(oss)
        debug["fftmtf_error_message"] = f"FFTMTF analysis run failed: {type(exc).__name__}: {exc!r}"
        _append_warning(output_path, debug["fftmtf_error_message"])
        update_analysis_debug(output_path.parent, run_id, debug)
        return False

    try:
        if data is None:
            message = "FFTMTF DataFrame extraction failed: returned no data."
            _append_warning(output_path, message)
            update_analysis_debug(output_path.parent, run_id, {"fftmtf_dataframe_success": False, "fftmtf_error_message": message})
            return False

        if not isinstance(data, DataFrame):
            message = f"FFTMTF DataFrame extraction failed: unexpected data type {type(data).__name__}."
            _append_warning(output_path, message)
            update_analysis_debug(output_path.parent, run_id, {"fftmtf_dataframe_success": False, "fftmtf_error_message": message})
            return False

        if data.empty:
            message = "FFTMTF DataFrame extraction failed: empty DataFrame."
            _append_warning(output_path, message)
            update_analysis_debug(output_path.parent, run_id, {"fftmtf_dataframe_success": False, "fftmtf_error_message": message})
            return False

        debug["fftmtf_dataframe_success"] = True
        if run_metadata:
            data.insert(0, "current_lens_file", run_metadata.get("current_lens_file"))
            data.insert(0, "run_id", run_metadata.get("run_id"))

        data.to_csv(output_path, index=True, encoding="utf-8-sig")
        update_analysis_debug(output_path.parent, run_id, debug)
        return True
    except Exception as exc:
        debug["fftmtf_error_message"] = f"FFTMTF CSV write failed: {type(exc).__name__}: {exc!r}"
        _append_warning(output_path, debug["fftmtf_error_message"])
        update_analysis_debug(output_path.parent, run_id, debug)
        return False
