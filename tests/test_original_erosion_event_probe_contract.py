from __future__ import annotations

from pathlib import Path


SANDBOX = Path(r"C:\Users\Administrator\EDDA-Taichi\tests\_fortran_toolchain_sandbox")


def test_original_erosion_event_probe_patch_and_scripts_have_non_destructive_contract():
    patch = SANDBOX / "patches" / "instrument_original_erosion_event_probe.patch"
    build_script = SANDBOX / "scripts" / "build_instrumented_edda.ps1"
    run_script = SANDBOX / "scripts" / "run_instrumented_original_cases.ps1"

    assert patch.exists()
    patch_text = patch.read_text(encoding="utf-8")
    assert "first accepted step with any erorate > 0" in patch_text
    assert "Do not alter EDDA physical formulas" in patch_text
    assert "original_erosion_event_probe.csv" in patch_text

    build_text = build_script.read_text(encoding="utf-8")
    assert "Apply-OriginalErosionEventProbeInstrumentation" in build_text
    assert "erosion_event_probe" in build_text
    assert "debug_stop_after_first_event" in build_text

    run_text = run_script.read_text(encoding="utf-8")
    assert "original_erosion_event_probe.csv" in run_text
    assert "original_erosion_event_probe_meta.json" in run_text
    assert "original_erosion_event_probe_progress.txt" in run_text

