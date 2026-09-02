"""Result-file discovery and EDDA-compatible naming helpers."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Optional


RESULT_FILE_SUFFIXES = {".tif", ".tiff", ".nc", ".csv"}
RESULT_TEXT_SUFFIXES = {".txt"}
KNOWN_OUTPUT_SUFFIXES = RESULT_FILE_SUFFIXES | RESULT_TEXT_SUFFIXES

KNOWN_RESULT_FAMILIES = (
    ("Max_flow_velocity", ("max_flow_velocity_", "max_flow_velocityedda", "max_flow_velocitytaichi")),
    ("Max_flow_depth", ("max_flow_depth_", "max_flow_depthedda", "max_flow_depthtaichi")),
    ("Flow_velocity", ("flow_velocity_", "flow_velocityedda", "flow_velocitytaichi")),
    ("Flow_depth", ("flow_depth_", "flow_depthedda", "flow_depthtaichi")),
    ("Erosion_depth", ("erosion_depth_", "erosion_depthedda", "erosion_depthtaichi")),
    ("Deposit_depth", ("deposit_depth_", "deposit_depthedda", "deposit_depthtaichi")),
    ("Total_depth", ("total_depth_", "total_depthedda", "total_depthtaichi")),
    (
        "Volumetric_sediment_conce",
        (
            "volumetric_sediment_conce",
            "volumetric_sediment_concentration_",
            "volumetric_sediment_concentrationedda",
            "volumetric_sediment_concentrationtaichi",
        ),
    ),
    ("Maxsoliddepth", ("maxsoliddepth", "maxsoliddepthedda", "maxsoliddeptaichi")),
    ("LS_Scar", ("ls_scar", "lsscar")),
    ("faildph", ("faildph",)),
    ("MaxSFdepth", ("maxsfdepth",)),
    ("MaxDFdepth", ("maxdfdepth",)),
    ("MaxFFdepth", ("maxffdepth",)),
    ("SFdepth", ("sfdepth",)),
    ("DFdepth", ("dfdepth",)),
    ("FFdepth", ("ffdepth",)),
    ("FS_min", ("fs_min_", "fs_minedda", "fs_mintaichi")),
    ("z_at_fs_min", ("z_at_fs_min_", "z_at_fs_minedda", "z_at_fs_mintaichi")),
    ("depth_at_fs_min", ("depth_at_fs_min_", "depth_at_fs_minedda", "depth_at_fs_mintaichi")),
    ("p_at_fs_min", ("p_at_fs_min_", "p_at_fs_minedda", "p_at_fs_mintaichi")),
    ("pf_at_fs_min", ("pf_at_fs_min",)),
    ("list_z_p_fs", ("list_z_p_fs_", "list_z_p_fsedda", "list_z_p_fstaichi")),
    ("OUTNQ", ("outnq_", "outnqedda", "outnqtaichi")),
    ("HYDROGRAPH", ("hydrograph_", "hydrographedda", "hydrographtaichi")),
)


def _as_posix_path(relative_path: str) -> PurePosixPath:
    return PurePosixPath(str(relative_path).replace("\\", "/"))


def _strip_known_suffix(filename: str) -> str:
    lower = filename.lower()
    for suffix in sorted(KNOWN_OUTPUT_SUFFIXES, key=len, reverse=True):
        if lower.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def _replace_marker_in_name(relative_path: str, old: str, new: str) -> str:
    path = _as_posix_path(relative_path)
    renamed = path.name.replace(old, new)
    parent = path.parent.as_posix()
    if parent in {"", "."}:
        return renamed
    return f"{parent}/{renamed}"


def taichi_result_name(relative_path: str) -> str:
    """Return the display/download name with only the EDDA marker replaced."""
    return _replace_marker_in_name(relative_path, "EDDA", "Taichi")


def edda_source_name(relative_path: str) -> str:
    """Return the physical-name fallback for a Taichi display/download alias."""
    return _replace_marker_in_name(relative_path, "Taichi", "EDDA")


def _family_before_marker(stem: str) -> Optional[str]:
    for marker in ("EDDA", "Taichi"):
        index = stem.find(marker)
        if index >= 0:
            family = stem[:index].rstrip("_")
            return family or None
    return None


def _known_family(stem: str) -> Optional[str]:
    lower = stem.lower()
    for family, prefixes in KNOWN_RESULT_FAMILIES:
        if any(lower.startswith(prefix) for prefix in prefixes):
            return family
    return None


def _strip_trailing_numeric_tokens(stem: str) -> str:
    parts = stem.rstrip("_").split("_")
    while len(parts) > 1:
        token = parts[-1]
        try:
            float(token)
        except ValueError:
            break
        parts.pop()
    return "_".join(parts)


def classify_result_family(relative_path: str) -> str:
    """Classify by the actual output filename, preserving EDDA-style families."""
    filename = _as_posix_path(relative_path).name
    stem = _strip_known_suffix(filename)
    marker_family = _family_before_marker(stem)
    if marker_family:
        return _known_family(marker_family) or marker_family
    known = _known_family(stem)
    if known:
        return known
    stripped = _strip_trailing_numeric_tokens(stem)
    return stripped or "other"


def is_result_file(path: Path, relative_path: str) -> bool:
    suffix = path.suffix.lower()
    if suffix in RESULT_FILE_SUFFIXES:
        return True
    if suffix not in RESULT_TEXT_SUFFIXES:
        return False
    filename = _as_posix_path(relative_path).name
    stem = _strip_known_suffix(filename)
    lower = stem.lower()
    if lower == "eddalog":
        return False
    if "edda" in lower or "taichi" in lower:
        return True
    return _known_family(stem) is not None
