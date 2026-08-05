"""Local-only directory discovery for the browser project-root and file picker."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence
import ctypes
import os

from api.services.workbench_store import WorkbenchError


def _is_unc_path(value: str) -> bool:
    normalized = value.strip().replace("/", "\\")
    return normalized.startswith("\\\\")


def discover_local_roots() -> list[Path]:
    """Return mounted local volumes, excluding network and optical drives."""
    if os.name != "nt":
        return [Path("/")]

    roots: list[Path] = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    get_drive_type = ctypes.windll.kernel32.GetDriveTypeW  # type: ignore[attr-defined]
    for index in range(26):
        if not bitmask & (1 << index):
            continue
        root = f"{chr(ord('A') + index)}:\\"
        drive_type = int(get_drive_type(root))
        if drive_type in {2, 3, 6}:  # removable, fixed, RAM disk
            roots.append(Path(root).resolve())
    return roots


class DirectoryPickerService:
    def __init__(self, roots: Optional[Sequence[Path]] = None):
        discovered = list(roots) if roots is not None else discover_local_roots()
        self.allowed_roots = self._normalize_roots(discovered)

    @staticmethod
    def _normalize_roots(roots: Iterable[Path]) -> list[Path]:
        normalized: list[Path] = []
        for root in roots:
            resolved = Path(root).expanduser().resolve()
            if resolved.exists() and resolved.is_dir() and resolved not in normalized:
                normalized.append(resolved)
        return sorted(normalized, key=lambda item: str(item).casefold())

    @staticmethod
    def _entry(path: Path, *, kind: str = "directory") -> dict[str, object]:
        return {
            "name": path.name or str(path),
            "path": str(path),
            "writable": os.access(path, os.W_OK),
            "kind": kind,
            "size": path.stat().st_size if kind == "file" and path.is_file() else None,
        }

    def _containing_root(self, path: Path) -> Optional[Path]:
        for root in self.allowed_roots:
            try:
                path.relative_to(root)
                return root
            except ValueError:
                continue
        return None

    def resolve_local_path(self, raw_path: str, *, expect_file: bool = False) -> Path:
        if _is_unc_path(raw_path):
            raise WorkbenchError(
                "network_path_not_supported",
                "仅支持本机路径，不支持 UNC 或网络共享。",
                status_code=422,
                details={"path": raw_path},
            )
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            raise WorkbenchError(
                "directory_path_not_absolute",
                "路径必须是绝对路径。",
                status_code=422,
                details={"path": raw_path},
            )
        resolved = candidate.resolve()
        if self._containing_root(resolved) is None:
            raise WorkbenchError(
                "directory_path_not_local",
                "路径不在本机可选择卷中。",
                status_code=422,
                details={"path": str(resolved)},
            )
        if not resolved.exists():
            raise WorkbenchError(
                "path_not_found",
                "路径不存在。",
                status_code=404,
                details={"path": str(resolved)},
            )
        if expect_file and not resolved.is_file():
            raise WorkbenchError(
                "path_not_file",
                "所选路径不是文件。",
                status_code=409,
                details={"path": str(resolved)},
            )
        if not expect_file and not resolved.is_dir():
            raise WorkbenchError(
                "directory_not_directory",
                "所选路径不是目录。",
                status_code=409,
                details={"path": str(resolved)},
            )
        return resolved

    def list_directories(self, raw_path: Optional[str]) -> dict[str, object]:
        roots = [self._entry(root) for root in self.allowed_roots]
        if raw_path is None or not raw_path.strip():
            return {
                "current_path": None,
                "parent_path": None,
                "roots": roots,
                "directories": [],
                "files": [],
                "can_select": False,
            }

        resolved = self.resolve_local_path(raw_path, expect_file=False)
        containing_root = self._containing_root(resolved)
        assert containing_root is not None

        directories: list[Path] = []
        files: list[Path] = []
        try:
            for child in resolved.iterdir():
                try:
                    child_resolved = child.resolve()
                    if self._containing_root(child_resolved) is None:
                        continue
                    if child.is_dir():
                        directories.append(child_resolved)
                    elif child.is_file():
                        files.append(child_resolved)
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError) as exc:
            raise WorkbenchError(
                "directory_access_denied",
                "无法读取该目录。",
                status_code=403,
                details={"path": str(resolved)},
            ) from exc

        directories = sorted(set(directories), key=lambda item: item.name.casefold())
        files = sorted(set(files), key=lambda item: item.name.casefold())
        parent = None if resolved == containing_root else resolved.parent
        return {
            "current_path": str(resolved),
            "parent_path": str(parent) if parent is not None else None,
            "roots": roots,
            "directories": [self._entry(child) for child in directories],
            "files": [self._entry(child, kind="file") for child in files],
            "can_select": os.access(resolved, os.W_OK),
        }
