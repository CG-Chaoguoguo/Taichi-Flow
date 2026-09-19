from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.portable.verify_runtime_lock import read_lock, verify_runtime_lock


@dataclass
class _Distribution:
    name: str
    version: str
    source: str

    @property
    def metadata(self) -> dict[str, str]:
        return {"Name": self.name}

    @property
    def _path(self) -> Path:
        return Path(self.source)


def _lock(tmp_path: Path, text: str = "python==3.11.9\nDemo_Pkg==2.0\n") -> Path:
    path = tmp_path / "portable-runtime.lock.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_runtime_lock_accepts_exact_interpreter_and_distribution_versions(tmp_path: Path) -> None:
    report = verify_runtime_lock(
        _lock(tmp_path),
        python_version="3.11.9",
        distributions=[_Distribution("demo-pkg", "2.0", "demo_pkg-2.0.dist-info")],
    )

    assert report["valid"] is True
    assert {entry["status"] for entry in report["entries"]} == {"ok"}


def test_runtime_lock_reports_missing_mismatched_and_duplicate_metadata(tmp_path: Path) -> None:
    lock = _lock(tmp_path, "python==3.11.9\ndemo-pkg==2.0\nmissing-pkg==1.0\n")
    report = verify_runtime_lock(
        lock,
        python_version="3.11.8",
        distributions=[
            _Distribution("demo_pkg", "2.0", "first.dist-info"),
            _Distribution("Demo-Pkg", "2.1", "second.dist-info"),
        ],
    )

    assert report["valid"] is False
    status = {entry["name"]: entry["status"] for entry in report["entries"]}
    assert status == {
        "python": "version_mismatch",
        "demo-pkg": "conflict",
        "missing-pkg": "missing",
    }
    assert any("3.11.9" in error and "3.11.8" in error for error in report["errors"])


def test_runtime_lock_rejects_duplicate_or_unpinned_entries(tmp_path: Path) -> None:
    duplicate = _lock(tmp_path, "python==3.11.9\nPyYAML==6.0.3\npyyaml==6.0.3\n")
    try:
        read_lock(duplicate)
    except ValueError as exc:
        assert "Duplicate runtime lock entry" in str(exc)
    else:
        raise AssertionError("duplicate normalized distribution names must be rejected")

    malformed = _lock(tmp_path, "python==3.11.9\nnumpy>=2.4.6\n")
    try:
        read_lock(malformed)
    except ValueError as exc:
        assert "Invalid runtime lock entry" in str(exc)
    else:
        raise AssertionError("non-exact runtime requirements must be rejected")


def test_portable_build_and_verifier_both_enforce_shared_lock_helper() -> None:
    root = Path(__file__).parent.parent
    build = (root / "scripts" / "portable" / "Build-Portable.ps1").read_text(encoding="utf-8")
    verify = (root / "scripts" / "portable" / "Verify-Taichi-Flow-Portable.ps1").read_text(encoding="utf-8")

    for script in (build, verify):
        assert "verify_runtime_lock.py" in script
        assert "TAICHI_FLOW_RUNTIME_LOCK=" in script
        assert "portable-runtime.lock.txt" in script
