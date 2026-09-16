"""Audit-only common-state Chamoli source replay; never a restart facility.

The native oracle compiles verbatim blocks from the supplied dfs.F90. Inputs
are complete, synthetic local source states, not reconstructed trajectories.
This verifies the source operator only: topology, forcing, CFL, retry, and
commit remain explicitly outside its evidence scope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def native_source(source: Path) -> tuple[str, list[dict]]:
    lines = source.read_text(encoding="utf-8-sig").splitlines()
    spans = []

    def block(start: str, end: str, *, inclusive: bool = False) -> str:
        starts = [i for i, line in enumerate(lines) if line.strip() == start]
        if len(starts) != 1:
            raise ValueError(f"ambiguous source anchor: {start}")
        a = starts[0]
        b = next(i for i in range(a + 1, len(lines)) if lines[i].strip() == end)
        b += int(inclusive)
        spans.append({"start_line": a + 1, "end_line": b, "text_sha256": hashlib.sha256("\n".join(lines[a:b]).encode()).hexdigest()})
        return "\n".join(lines[a:b])

    velocity = block("vx=(fv(i,5)-fv(i,1))*0.5+(fv(i,4)-fv(i,8))*0.5*0.707+(fv(i,6)-fv(i,2))*0.5*0.707", "end do")
    settling = block("if (cv(i)<eps) then", "end do")
    erosion = block("! determine the erosion rate of each cell", "! determine the deposition rate of each cell")
    deposition = block("! determine the deposition rate of each cell", "!if (sepdepositionsimul) then", inclusive=True)
    # Include the outer IF terminator, immediately after its identifying comment.
    deposition += "\nend if\n"
    declarations = """
program replay_source
implicit none
integer,parameter::imx1=1
integer::i,j,n,s,zo(1)
logical::erosionsimul,sepdepositionsimul
double precision::fv(1,8),fh(1),fhpredi1(1),frhopredi1(1),cv(1),cvlimit(1),rholimit(1),slo(1)
double precision::absubar(1),fvdepo(1),erorate(1),deporate(1),inierodithick(1),tempinierodithick(1)
double precision::debdepothick(1),tempdebdepothick(1),barrier(1),fhpredi(1),ele(1),eleori(1)
double precision::rhodepo(1),manning(1),phit(1),ctao(1),kero(1),cvero(1)
double precision::vx,vy,dt,rhow,rhos,cvstar,cvbar,grav,cvtol,eps,cs,alpha1,beta1,alpha2,beta2
double precision::kresis,debrisflowmanning,coedepo,d50,sfy,sfmiu,sfmanning,tao,taoc,gammadeb
double precision::normfriccoe,miudebris,coemiu,coemanning,manningbar,rhoero,lambdainverse,tanthetae,sinthetae
read(*,*) n
do s=1,n
read(*,*) dt,fh(1),fhpredi1(1),frhopredi1(1),cvlimit(1),rholimit(1),slo(1),cvbar, &
 inierodithick(1),debdepothick(1), (fv(1,j),j=1,8)
read(*,*) rhow,rhos,cvstar,grav,cvtol,eps,cs,alpha1,beta1,alpha2,beta2,kresis, &
 debrisflowmanning,coedepo,d50,manning(1),phit(1),ctao(1),kero(1),cvero(1)
zo=1
erosionsimul=.true.
sepdepositionsimul=.true.
barrier=0
fhpredi=fhpredi1
ele=0
eleori=0
erorate=0
deporate=0
sfy=0
sfmanning=0
sfmiu=0
tao=0
taoc=0
tempinierodithick=inierodithick
tempdebdepothick=debdepothick
rhodepo=cvstar*(rhos-rhow)+rhow
i=1
cv=(frhopredi1-rhow)/(rhos-rhow)
if(cv(1)<eps) cv(1)=0
"""
    trailer = """
write(*,'(11(ES25.17E3,1X))') absubar(1),sfy,sfmanning,sfmiu,tao,taoc,erorate(1),deporate(1), &
 tempinierodithick(1),tempdebdepothick(1),rhodepo(1)
end do
end program
"""
    return declarations + velocity + "\n" + settling + "\n" + erosion + "\n" + deposition + trailer, spans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arch", choices=["cpu", "cuda"], default="cuda")
    parser.add_argument("--vcvars", type=Path, default=Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Auxiliary/Build/vcvars64.bat"))
    parser.add_argument("--setvars", type=Path, default=Path("D:/Tool/oneAPI/1API/setvars.bat"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    generated, spans = native_source(args.source)
    f90 = args.output.resolve() / "source_native.f90"
    f90.write_text(generated, encoding="utf-8")
    executable = args.output.resolve() / "source_native.exe"
    compile_cmd = f'call "{args.vcvars}" >nul && call "{args.setvars}" intel64 >nul && ifx /nologo /Od /fp:strict /exe:"{executable}" "{f90}"'
    t0 = time.perf_counter()
    # Windows list2cmdline escapes embedded quotes with backslashes, which
    # cmd.exe does not interpret as Python-style escaping. Preserve /s /c's
    # outer quote contract for these explicit, local compiler paths.
    compiled = subprocess.run('cmd.exe /d /s /c "' + compile_cmd + '"', cwd=args.output, capture_output=True, text=True)
    (args.output / "compile.log").write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
    compiled.check_returncode()
    native_compile_s = time.perf_counter() - t0

    import numpy as np
    import taichi as ti
    from edda.solver.dfs_dynamic_wave import DFSDynamicWaveSolver
    from edda.solver.dynamic_wave_fortran import FortranDynamicWaveWorkspace
    from edda.solver.fortran_literals import DFS_CVTOL, FORTRAN_DEG2RAD
    from tests.test_dfs_dynamic_wave import _build_config, _build_fields

    ti.init(arch=ti.cuda if args.arch == "cuda" else ti.cpu, default_fp=ti.f64, fast_math=False, offline_cache=False)
    t0 = time.perf_counter()
    cfg = _build_config(absubar_variant="signed_mean_chamoli", manningbar_variant="debrisflowmanning_cvtol", debrisflowmanning=0.07)
    fields = _build_fields()
    solver = DFSDynamicWaveSolver(fields, cfg, FortranDynamicWaveWorkspace(fields))
    initialization_s = time.perf_counter() - t0
    material = dict(rhow=1000., rhos=2650., cvstar=.65, grav=solver.g, cvtol=DFS_CVTOL, eps=1e-18,
                    cs=solver.cs, alpha1=.01, beta1=10., alpha2=.002, beta2=8., kresis=solver.kresis,
                    debrisflowmanning=solver.debrisflowmanning, coedepo=solver.coedepo, d50=solver.d50,
                    manning=.05, phi_rad=24*FORTRAN_DEG2RAD, ctao=10., kero=.0001, cvero=.65)
    samples = []
    for slope in (.05, .4):
        for cv, limit in ((.08,.6),(.4,.6),(.55,.2)):
            for velocities in ([0,0,0,0,20,0,0,0], [0,0,0,20,0,0,0,0], [4]*8):
                samples.append(dict(dt=.25,h=.4,hp=.5,rhop=1000+1650*cv,cvlimit=limit,rholimit=1000+1650*limit,
                                    slope=slope,cvbar=.4,erodible=.01,deposit=.03,fv=velocities))
    # Repeat the complete batch on the same instance, restoring every input.
    samples = samples + [dict(s) for s in samples]
    input_lines = [str(len(samples))]
    for sample in samples:
        input_lines.append(" ".join(format(x,".17g") for x in [sample[k] for k in ("dt","h","hp","rhop","cvlimit","rholimit","slope","cvbar","erodible","deposit")] + sample["fv"]))
        input_lines.append(" ".join(format(x,".17g") for x in material.values()))
    input_text = "\n".join(input_lines) + "\n"
    (args.output / "source_inputs.txt").write_text(input_text, encoding="utf-8")
    native = subprocess.run([str(executable)], input=input_text, capture_output=True, text=True, check=True)
    (args.output / "native_outputs.txt").write_text(native.stdout, encoding="utf-8")
    oracle = np.array([[float(v) for v in line.split()] for line in native.stdout.splitlines() if line.strip()])
    outputs = ["absubar_temp","sfy_temp","sfmanning_temp","sfmiu_temp","tau_temp","taoc_temp","erosion_rate",
               "deposition_rate","temp_erodible_thickness","temp_depo_thickness","rhodepo_temp"]
    records = []
    for index, sample in enumerate(samples):
        t0 = time.perf_counter()
        assigned = {"h":sample["h"],"fhpredi1":sample["hp"],"frhopredi1":sample["rhop"],
                    "cvlimit_temp":sample["cvlimit"],"rholimit_temp":sample["rholimit"],"tanslo_fortran":math.tan(sample["slope"]),
                    "erodible_thickness":sample["erodible"],"depo_thickness":sample["deposit"],"phi_field":24.,
                    "alpha1_field":material["alpha1"],"beta1_field":material["beta1"],"alpha2_field":material["alpha2"],
                    "beta2_field":material["beta2"],"ctao_field":material["ctao"],"kero_field":material["kero"],
                    "cvero_field":material["cvero"],"n_manning_field":material["manning"]}
        for name,value in assigned.items():
            getattr(fields,name).from_numpy(np.full((2,1),value,dtype=np.float64))
        fields.fv_fortran.from_numpy(np.broadcast_to(np.array(sample["fv"],dtype=np.float64),(2,1,8)).copy())
        upload_s = time.perf_counter()-t0
        t0 = time.perf_counter()
        solver._compute_source_rates(sample["dt"], material["rhow"], material["rhos"], material["cvstar"], sample["cvbar"])
        ti.sync()
        compute_s = time.perf_counter()-t0
        actual = np.array([float(getattr(fields,name)[0,0]) for name in outputs])
        # Fortran retains previous stress scalars when cv>=cvlimit; those are
        # inapplicable diagnostics, not zero-valued physical observations.
        active = (sample["rhop"]-1000)/1650 < sample["cvlimit"]
        mask = np.ones(len(outputs),dtype=bool)
        mask[1:6] = active
        close = np.isclose(actual,oracle[index],rtol=1e-6,atol=1e-10) | ~mask
        records.append(dict(index=index, state=sample, applicable=mask.tolist(), native=oracle[index].tolist(),
                            taichi=actual.tolist(), passed=bool(np.all(close)), mismatches=[name for name,ok in zip(outputs,close) if not ok],
                            upload_s=upload_s,compute_s=compute_s))
    report = dict(schema="fix3-common-source-replay-v1",scope="synthetic_local_source_only",final_acceptance_pass=False,
                  source=str(args.source),source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),source_spans=spans,
                  tested_solver_sha256=hashlib.sha256((ROOT/"edda/solver/dfs_dynamic_wave.py").read_bytes()).hexdigest(),
                  runtime_arch=str(ti.lang.impl.current_cfg().arch),material=material,outputs=outputs,rtol=1e-6,atol=1e-10,
                  native_compile_s=native_compile_s,initialization_s=initialization_s,records=records,
                  passed=all(r["passed"] for r in records), limitations=["No trajectory capture, topology, forcing, CFL, retry or commit equivalence claim", "Original binary is not replaced by this source-built oracle"])
    (args.output/"replay.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("passed","scope","runtime_arch","native_compile_s","initialization_s")}))
    print("mismatches:",[(r["index"],r["mismatches"]) for r in records if not r["passed"]])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
