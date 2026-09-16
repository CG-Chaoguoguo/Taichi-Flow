"""Temporary migration used only by the isolated audit workflow; removed after use."""
from pathlib import Path
import hashlib

p=Path('tests/test_time_integration_consistency.py');s=p.read_text().replace('from edda.solver.edda_solver import EDDASolver','from edda.solver.edda_solver import EDDASolver\nfrom edda.config.sim_config import SimulationConfig')
s=s.replace('        self.fields = object()','''        # A time-loop double still satisfies the real output lifecycle contract.
        # No file is read: physics and output callbacks are the deliberate doubles.
        super().__init__(SimulationConfig(dem_file="time-loop-test-double.asc", compute={"async_output": False}))
        self.fields = object()''');s=s.replace('    def _use_fortran_dfs(self) -> bool:', '\n'.join([
'    def write_erosion_probe_csv(self):',
'        # This harness deliberately has no raster/output workspace. Keep the',
'        # real run() finalization and completion checks, but double probe I/O.',
'        return None', '',
'    def _use_fortran_dfs(self) -> bool:']))
p.write_text(s)
p=Path('tests/test_solver.py');s=p.read_text().replace("assert stats['t_current'] == 1.0", "assert stats['t_current'] == pytest.approx(1.0, rel=0.0, abs=1e-15)");p.write_text(s)
p=Path('tests/test_system_directories.py');s=p.read_text().replace('test_directory_picker_lists_local_directories_without_files','test_directory_picker_separates_typed_directories_and_files')
s=s.replace('{"name": "drive-c", "path": str(root.resolve()), "writable": True}', '{"name": "drive-c", "path": str(root.resolve()), "writable": True, "kind": "directory", "size": None}')
s=s.replace('{"name": "project-parent", "path": str(child.resolve()), "writable": True}', '{"name": "project-parent", "path": str(child.resolve()), "writable": True, "kind": "directory", "size": None}')
s=s.replace('assert "not-a-directory.txt" not in str(payload)', '''assert payload["files"] == [{
            "name": "not-a-directory.txt",
            "path": str((root / "not-a-directory.txt").resolve()),
            "writable": True, "kind": "file", "size": len("not exposed".encode("utf-8")),
        }]''')
s=s.replace('"directory_not_found"','"path_not_found"').replace('{"current_path", "parent_path", "roots", "directories", "can_select"}', '{"current_path", "parent_path", "roots", "directories", "files", "can_select"}');p.write_text(s)
p=Path('tests/test_zone_system.py');s=p.read_text().replace('assert zone_params.shape == (2, 26)  # 2 zones, 26 parameters','''# Match the runtime mapping's column contract, including erosion controls.
        columns = (
            "K_sat", "theta_s", "theta_i", "psi_f", "c", "phi", "gamma_s", "gamma_w", "depth",
            "n_manning", "alpha1", "beta1", "alpha2", "beta2", "alpha_top", "alpha_bottom",
            "K_sat_top", "K_sat_bottom", "theta_sat_top", "theta_sat_bottom", "theta_res_top",
            "theta_res_bottom", "phib", "kero", "ltstar", "lbstar", "ctao", "cvero",
        )
        assert zone_params.shape == (2, len(columns))
        for row, zone_id in enumerate(sorted(zone_config)):
            for col, name in enumerate(columns):
                value = getattr(zone_config[zone_id], name)
                expected = -1.0 if name == "cvero" and value is None else value
                assert zone_params[row, col] == expected, (zone_id, name)''')
a=s.index('def test_parameter_mapping_basic');b=s.index('\n    def ', a+5)
frag=s[a:b].replace('K_sat=1e-5,','K_sat=1e-5,\n                ctao=1.25,\n                cvero=0.42,',1).replace('K_sat=5e-6,','K_sat=5e-6,\n                ctao=2.5,\n                cvero=None,',1)
s=s[:a]+frag+s[b:];p.write_text(s)
p=Path('tests/test_dfs_dynamic_wave.py');s=p.read_text()
a=s.index('def test_sfdf_classify_cv_variant_prev_vs_predicted_commit_branch():');b=s.index('    rho_water =',a)
s=s[:a]+'''def test_sfdf_classify_cv_variant_prev_vs_predicted_commit_branch():
    """Classification is pre-outflow; committing must not overwrite its result."""
'''+s[b:]
needle='''        solver._commit_step(0.1, 0.1, rho_water, rho_sediment, cfg.rheology.Cv_max)
        return (
            fields.sfh.to_numpy()[0, 0],'''
repl='''        solver._classify_sfdf_pre_outflow(rho_water, rho_sediment)
        before = [field.to_numpy().copy() for field in (fields.sfh, fields.dfh, fields.ffh)]
        solver._commit_step(0.1, 0.1, rho_water, rho_sediment, cfg.rheology.Cv_max)
        for field, expected in zip((fields.sfh, fields.dfh, fields.ffh), before):
            np.testing.assert_array_equal(field.to_numpy(), expected)
        return (
            fields.sfh.to_numpy()[0, 0],'''
assert s.count(needle)==1;s=s.replace(needle,repl);p.write_text(s)
p=Path('tests/test_native_input_chain.py');s=p.read_text()
s=s.replace('def _write_ascii_grid(path: Path, values: np.ndarray, nodata: float = -9999.0) -> None:', 'def _write_ascii_grid(path: Path, values: np.ndarray, nodata: float = -9999.0, *, cellsize: float = 1.0) -> None:')
s=s.replace('handle.write("cellsize 1\\n")','handle.write(f"cellsize {cellsize}\\n")').replace('def _make_reference_case(tmp_path: Path) -> Path:', 'def _make_reference_case(tmp_path: Path, *, cellsize: float = 1.0) -> Path:')
lines=s.splitlines()
for i in range(38,46):
    ix=i-1
    assert '_write_ascii_grid(' in lines[ix]
    lines[ix]=lines[ix][:-1]+', cellsize=cellsize)'
p.write_text('\n'.join(lines)+'\n')
p=Path('tests/test_runtime_source_chain_diagnostics.py');s=p.read_text()
s=s.replace('def _make_precomputed_schedule_case(tmp_path, *, with_artifacts: bool = True):', 'def _make_precomputed_schedule_case(tmp_path, *, with_artifacts: bool = True, cellsize: float = 30.0):')
s=s.replace('edda_in = _make_reference_case(tmp_path)','''# This is a synthetic schedule/ledger test, not a historical reference run.
    # At 1 m spacing its 1 s candidate violates the real CFL threshold (~0.303 s).
    # A consistent 30 m grid lets both .5/.75 s source events be committed in
    # one stable candidate WITHOUT changing solver thresholds or forcing accept.
    edda_in = _make_reference_case(tmp_path, cellsize=cellsize)''',1)
lines=s.splitlines()
for i,line in enumerate(lines):
    if '_write_ascii_grid(edda_in.parent / "precomputed_unsfin_' in line:
        lines[i]=line[:-1]+', cellsize=cellsize)'
s='\n'.join(lines)+'\n'
s+='''

def test_real_cfl_rejection_discards_sources_then_retries_commit_exactly_once(tmp_path):
    import pytest

    # Retain the original steep 1 m synthetic grid to exercise a REAL reject.
    # The controlled retry uses a smaller candidate, not a larger CFL tolerance.
    edda_in = _make_precomputed_schedule_case(tmp_path, cellsize=1.0)
    solver, manifest, _, _ = _initialize_real_solver(edda_in, tmp_path / "out_real_retry")
    solver.fields.erodible_thickness.from_numpy(np.full((solver.fields.nx, solver.fields.ny), 10.0, dtype=np.float64))
    dfs = solver.dfs_dynamic_wave
    dfs.set_current_time(0.0)
    rejected = dfs.step(1.0)
    assert not rejected["accepted"]
    assert rejected["rejected_stage"] == "cfl"
    diagnostics = collect_runtime_source_chain_diagnostics(solver, manifest)
    assert diagnostics["committed_fired_count"] == 0
    assert diagnostics["candidate_fired_count"] == 0
    assert diagnostics["rejected_step_discard_count"] == 2
    assert diagnostics["failure_source_flow_depth_sum"] == 0.0
    t, dt = 0.0, 0.1
    for _ in range(200):
        if t >= 1.0 - 1.e-12:
            break
        dfs.set_current_time(t)
        info = dfs.step(min(dt, 1.0 - t))
        if info["accepted"]:
            t += info["used_dt"]
        else:
            # Test driver only; time never advances for a rejected attempt.
            dt = min(float(info["suggested_dt"]), dt / 2.0)
    assert t == pytest.approx(1.0, rel=0.0, abs=1.e-12)
    diagnostics = collect_runtime_source_chain_diagnostics(solver, manifest)
    assert diagnostics["committed_fired_count"] == 2
    assert diagnostics["candidate_fired_count"] == 0
    assert diagnostics["duplicate_fire_count"] == 0
    assert diagnostics["failure_source_flow_depth_sum"] == pytest.approx(0.6, rel=1.e-12)
    rho = (solver.config.rheology.rho_sediment - solver.config.rheology.rho_water) * solver.config.rheology.Cv_max + solver.config.rheology.rho_water
    assert diagnostics["failure_source_mass_sum"] == pytest.approx(0.6 * rho, rel=1.e-12)
'''
p.write_text(s)
p=Path('edda/solver/native_unsfin/analytic_cell.py');s=p.read_text()
s=s.replace('from .ledger import LedgerArrays, load_original_oracle','from .ledger import LedgerArrays, load_original_oracle\nfrom .input_grid import load_aligned_active_inputs, read_ascii_active_values')
a=s.index('def read_ascii_active_values(');b=s.index('def build_cell_field_packs(',a);s=s[:a]+s[b:]
old='''    paths = config["paths"]
    slope_values, active_mapping, slope_header = read_ascii_active_values(case_dir / paths["slope"])
    zone_values, zone_mapping, _zone_header = read_ascii_active_values(case_dir / paths["zone"], integer=True)
    ltstar_values, ltstar_mapping, _lt_header = read_ascii_active_values(case_dir / paths["ltstar"])'''
new='''    grids = load_aligned_active_inputs(case_dir, config["paths"])
    slope_values, active_mapping, slope_header = grids["slope"]
    zone_values, zone_mapping, _zone_header = grids["zone"]
    ltstar_values, ltstar_mapping, _lt_header = grids["ltstar"]'''
assert s.count(old)==2;s=s.replace(old,new)
s=s.replace('len(active_mapping) == len(zone_mapping)','active_mapping == zone_mapping').replace('len(active_mapping) == len(ltstar_mapping)','active_mapping == ltstar_mapping')
s=s.replace('''    if len(active_mapping) != len(zone_mapping) or len(active_mapping) != len(ltstar_mapping):
        raise ValueError("active-cell mapping mismatch across slope/zone/ltstar grids")
''','');p.write_text(s)
p=Path('edda/solver/dfs_dynamic_wave.py');s=p.read_text()
old='''                if int(cell_id[ni, nj]) < source_cell_id:
                    continue'''
new='''                # Match the strict kernel ownership predicate, including the
                # opt-in reverse owner. Otherwise a real kernel assignment can
                # have no host pair (or a self-edge can be invented).
                target_cell_id = int(cell_id[ni, nj])
                owns_face = (
                    source_cell_id > target_cell_id
                    if self.fortran_face_owner_max_cell_enabled
                    else target_cell_id > source_cell_id
                )
                if not owns_face:
                    continue'''
assert s.count(old)==1;s=s.replace(old,new)
a=s.index('    def _diagnostic_qnet_qmassnet_accumulation_kernel');b=s.index('\n    @',a);frag=s[a:b]
assert 'qnet = 0.0' in frag
frag=frag.replace('qnet = 0.0','qnet = ti.cast(0.0, ti.f64)').replace('qmassnet = 0.0','qmassnet = ti.cast(0.0, ti.f64)')
frag=frag.replace('                qnet = ti.cast(0.0, ti.f64)', '''                # Match _accumulate_and_check even when runtime default_fp is
                # f32: declaring f64 fields does not type a local accumulator.
                qnet = ti.cast(0.0, ti.f64)''')
s=s[:a]+frag+s[b:];p.write_text(s)
checks = {
  "edda/solver/dfs_dynamic_wave.py": "b699c42e5e3ea747deeaea3074aa0187be9351797629c915e60fa596ccdac951",
  "edda/solver/native_unsfin/analytic_cell.py": "f459484dd088d179bec6864f78fc05ef676d6ab95710f3e796546b0f4550a3f5",
  "tests/test_dfs_dynamic_wave.py": "48de4f7b9a6413b8126ad0cae91efa01b5e3dc2c695d6ef9481f7d5eb00e2ebc",
  "tests/test_native_input_chain.py": "0a1e08768297506ad6a338998870106b5aab4c550681b14cfff429fa26ac07f5",
  "tests/test_runtime_source_chain_diagnostics.py": "3c4f579fbb0972978a4dde448f05c642efbaa34e89c345216745266cd4a7dcbc",
  "tests/test_solver.py": "f49ea9683debdc7eb37787bd8d97b7aec74e4e8b2f82afb369a77f1190bc4db6",
  "tests/test_system_directories.py": "de6be22673b7f2b512e18793fe15c96e405907c08b5aee9ee3de48b4233159af",
  "tests/test_time_integration_consistency.py": "aba4d39edcab1f02eb66fe13de8346fa3c509a82a8ec30a42b2d755d2a356230",
  "tests/test_zone_system.py": "ad6f8d36c0a1732f88eb019b365bb7dd991ff059210bc2aefd078512014d58a2"
}
for name, expected in checks.items():
    actual = hashlib.sha256(Path(name).read_bytes()).hexdigest()
    assert actual == expected, (name, actual, expected)
print('All nine changed files match the locally tested bytes.')
