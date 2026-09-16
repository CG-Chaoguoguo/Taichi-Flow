param(
    [Parameter(Mandatory=$false)]
    [string]$CaseRoot = "",
    [string]$PatchPath = "",
    [string]$OutputWorkDir = "",
    [string]$SandboxRoot = "",
    [string]$BuildVariant = "debug_bounds"
)

$ErrorActionPreference = "Continue"

if (-not $SandboxRoot) {
    $SandboxRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not $PatchPath) {
    $PatchPath = Join-Path $SandboxRoot "patches\instrument_tfail_dump.patch"
}
if (-not $OutputWorkDir) {
    $OutputWorkDir = Join-Path $SandboxRoot "work\instrumented_build"
}

$LogsDir = Join-Path $SandboxRoot "logs"
$GeneratedDir = Join-Path $SandboxRoot "generated"
New-Item -ItemType Directory -Force -Path $LogsDir, $GeneratedDir, $OutputWorkDir | Out-Null

$BuildVariantSafe = ($BuildVariant -replace '[^A-Za-z0-9_.-]', '_')
if (-not $BuildVariantSafe) { $BuildVariantSafe = "debug_bounds" }

$BuildLog = Join-Path $LogsDir "original_instrumented_build_log_$BuildVariantSafe.txt"
$BuildOrderMd = Join-Path $GeneratedDir "fortran_build_order_$BuildVariantSafe.md"
$ManifestMd = Join-Path $GeneratedDir "instrumented_exe_manifest_$BuildVariantSafe.md"
$LegacyBuildLog = Join-Path $LogsDir "original_instrumented_build_log.txt"
$LegacyBuildOrderMd = Join-Path $GeneratedDir "fortran_build_order.md"
$LegacyManifestMd = Join-Path $GeneratedDir "instrumented_exe_manifest.md"

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $BuildLog -Value $line -Encoding UTF8
    Write-Output $Message
}

function Find-Executable {
    param([string[]]$Candidates, [string]$CommandName)
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }
    if ($CommandName) {
        $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Copy-SourceProject {
    param([string]$Source, [string]$Destination)
    if (Test-Path $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Get-ChildItem -Path (Join-Path $Source "*") -File -Include *.F90,*.f90,*.for,*.f,*.vfproj,*.sln,*.txt,*.dat |
        Where-Object { $_.Name -notmatch "EDDALog|TopoIndexLog" } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Destination $_.Name) -Force
        }
}

function Apply-TfailInstrumentation {
    param([string]$ProjectDir)
    $main = Join-Path $ProjectDir "edda main program.F90"
    $vfproj = Join-Path $ProjectDir "EDDA.vfproj"
    $dump = Join-Path $ProjectDir "tfail_dump.F90"

    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $vfproj)) { throw "Missing EDDA.vfproj in $ProjectDir" }

    $mainText = Get-Content $main -Raw
    if ($mainText -notmatch "dump_unsfin_schedule_artifacts") {
        $mainText = $mainText.Replace(
            "if (fssimul) call unsfin(imx1,u(19),u(2),profil)",
            "call dump_instrumented_progress('before_unsfin')`r`nif (fssimul) call unsfin(imx1,u(19),u(2),profil)`r`ncall dump_instrumented_progress('after_unsfin')`r`nif (fssimul) call dump_unsfin_schedule_artifacts(imx1)"
        )
        $mainText = $mainText.Replace(
            "     &nodata,mnd,sctr,ncol,nrow,header,test1,u,25)",
            "     &nodata,mnd,sctr,ncol,nrow,header,test1,u,25)`r`ncall dump_instrumented_progress('after_rnoff')"
        )
        $mainText = $mainText.Replace(
            "allocate (nvu(imax),nv(imax),gs(nzon),gst(nzon),gsb(nzon))",
            "allocate (nvu(imax),nv(imax),gs(nzon),gst(nzon),gsb(nzon))`r`ncall dump_instrumented_progress('after_slope_allocations')"
        )
        $mainText = $mainText.Replace(
            "fsmin=10.; pmin=0.; zfmin=0.; fdepth=0.; pfmin=0.",
            "fsmin=10.; pmin=0.; zfmin=0.; fdepth=0.; pfmin=0.`r`ncall dump_instrumented_progress('after_failure_state_init')"
        )
        $mainText = $mainText.Replace(
            "fc=0.; fw=0.",
            "fc=0.; fw=0.`r`ncall dump_instrumented_progress('after_fc_fw_init')"
        )
        $mainText = $mainText.Replace(
            "thzb=0.; thzt=0.",
            "thzb=0.; thzt=0.`r`ncall dump_instrumented_progress('after_theta_init')"
        )
        $mainText = $mainText.Replace(
            "nv=0",
            "call dump_instrumented_progress('before_nv_init')`r`nnv=0`r`ncall dump_instrumented_progress('after_nv_init')"
        )
        $mainText = $mainText.Replace(
            "nvu=0",
            "nvu=0`r`ncall dump_instrumented_progress('after_nvu_init')"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $progressSubroutine = @"
subroutine dump_instrumented_progress(marker)
    implicit none
    character(len=*), intent(in) :: marker

    open(990,file='instrumented_progress.log',status='unknown',position='append')
    write(990,'(A)') trim(marker)
    close(990)
end subroutine dump_instrumented_progress

subroutine dump_unsfin_schedule_artifacts(imx1)
    use model_vars
    use grids
    implicit none
    integer, intent(in) :: imx1
    integer :: i

    open(991,file='precomputed_unsfin_gindx.txt',status='replace')
    do i=1,imx1
        write(991,*) gindx(i)
    end do
    close(991)

    open(992,file='precomputed_unsfin_tfail.txt',status='replace')
    do i=1,imx1
        write(992,'(ES24.16)') dble(tfail(i))
    end do
    close(992)

    open(993,file='precomputed_unsfin_fdepth.txt',status='replace')
    do i=1,imx1
        write(993,'(ES24.16)') fdepth(i)
    end do
    close(993)

    open(994,file='precomputed_unsfin_meta.json',status='replace')
    write(994,'(A)') '{'
    write(994,'(A,I0,A)') '  "imx1": ', imx1, ','
    write(994,'(A)') '  "shape_kind": "active_cell_vector",'
    write(994,'(A)') '  "provider": "original_instrumented_unsfin",'
    write(994,'(A)') '  "dump_point": "after unsfin returns and before dfs enters",'
    write(994,'(A)') '  "notes": "Vector order follows original EDDA active DEM point order; current loader maps through DEM valid-cell order."'
    write(994,'(A)') '}'
    close(994)
end subroutine dump_unsfin_schedule_artifacts
"@ | Set-Content -Path $dump -Encoding ASCII

    $vfText = Get-Content $vfproj -Raw
    if ($vfText -notmatch "tfail_dump\.F90") {
        $vfText = $vfText.Replace(
            '<File RelativePath=".\unsfin.F90"/>',
            '<File RelativePath=".\unsfin.F90"/>' + "`r`n`t`t" + '<File RelativePath=".\tfail_dump.F90"/>'
        )
        Set-Content -Path $vfproj -Value $vfText -Encoding UTF8
    }
}

function Apply-MainProgressInstrumentation {
    param([string]$ProjectDir)
    $main = Join-Path $ProjectDir "edda main program.F90"
    $vfproj = Join-Path $ProjectDir "EDDA.vfproj"
    $dump = Join-Path $ProjectDir "tfail_dump.F90"

    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $vfproj)) { throw "Missing EDDA.vfproj in $ProjectDir" }

    $mainText = Get-Content $main -Raw
    if ($mainText -notmatch "dump_instrumented_progress") {
        $mainText = $mainText.Replace(
            "if (fssimul) call unsfin(imx1,u(19),u(2),profil)",
            "call dump_instrumented_progress('before_unsfin')`r`nif (fssimul) call unsfin(imx1,u(19),u(2),profil)`r`ncall dump_instrumented_progress('after_unsfin')"
        )
        $mainText = $mainText.Replace(
            "     &nodata,mnd,sctr,ncol,nrow,header,test1,u,25)",
            "     &nodata,mnd,sctr,ncol,nrow,header,test1,u,25)`r`ncall dump_instrumented_progress('after_rnoff')"
        )
        $mainText = $mainText.Replace(
            "allocate (nvu(imax),nv(imax),gs(nzon),gst(nzon),gsb(nzon))",
            "allocate (nvu(imax),nv(imax),gs(nzon),gst(nzon),gsb(nzon))`r`ncall dump_instrumented_progress('after_slope_allocations')"
        )
        $mainText = $mainText.Replace(
            "fsmin=10.; pmin=0.; zfmin=0.; fdepth=0.; pfmin=0.",
            "fsmin=10.; pmin=0.; zfmin=0.; fdepth=0.; pfmin=0.`r`ncall dump_instrumented_progress('after_failure_state_init')"
        )
        $mainText = $mainText.Replace(
            "fc=0.; fw=0.",
            "fc=0.; fw=0.`r`ncall dump_instrumented_progress('after_fc_fw_init')"
        )
        $mainText = $mainText.Replace(
            "thzb=0.; thzt=0.",
            "thzb=0.; thzt=0.`r`ncall dump_instrumented_progress('after_theta_init')"
        )
        $mainText = $mainText.Replace(
            "nv=0",
            "call dump_instrumented_progress('before_nv_init')`r`nnv=0`r`ncall dump_instrumented_progress('after_nv_init')"
        )
        $mainText = $mainText.Replace(
            "nvu=0",
            "nvu=0`r`ncall dump_instrumented_progress('after_nvu_init')"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $progressSubroutine = @"
subroutine dump_instrumented_progress(marker)
    implicit none
    character(len=*), intent(in) :: marker

    open(990,file='instrumented_progress.log',status='unknown',position='append')
    write(990,'(A)') trim(marker)
    close(990)
end subroutine dump_instrumented_progress
"@
    if (Test-Path $dump) {
        $dumpText = Get-Content $dump -Raw
        if ($dumpText -notmatch "subroutine\s+dump_instrumented_progress") {
            Add-Content -Path $dump -Value "`r`n$progressSubroutine" -Encoding ASCII
        }
    } else {
        $progressSubroutine | Set-Content -Path $dump -Encoding ASCII
    }

    $vfText = Get-Content $vfproj -Raw
    if ($vfText -notmatch "tfail_dump\.F90") {
        $vfText = $vfText.Replace(
            '<File RelativePath=".\unsfin.F90"/>',
            '<File RelativePath=".\unsfin.F90"/>' + "`r`n`t`t" + '<File RelativePath=".\tfail_dump.F90"/>'
        )
        Set-Content -Path $vfproj -Value $vfText -Encoding UTF8
    }
}

function Apply-DownstreamDfsInstrumentation {
    param([string]$ProjectDir)
    $main = Join-Path $ProjectDir "edda main program.F90"
    $dfs = Join-Path $ProjectDir "dfs.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dfs)) { throw "Missing dfs.F90 in $ProjectDir" }

    $mainText = Get-Content $main -Raw
    if ($mainText -notmatch "before_dfs") {
        $mainText = $mainText.Replace(
            "if (debrissimul) then`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)",
            "if (debrissimul) then`r`ncall dump_instrumented_progress('before_dfs')`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)`r`ncall dump_instrumented_progress('after_dfs')"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $text = Get-Content $dfs -Raw
    if ($text -match "original_downstream_internal_600s") {
        Write-Log "Downstream DFS instrumentation already present."
        return
    }

    $text = $text.Replace(
        "integer:: u(28),ncc,nccs,eroindx(imx1),tempgindx(imx1)",
        "integer:: u(28),ncc,nccs,eroindx(imx1),tempgindx(imx1)`r`ninteger:: erosion_gate_trace(imx1),rholimit_clamp_trace(imx1),erodible_clamp_trace(imx1),deposition_gate_trace(imx1)"
    )
    $text = $text.Replace(
        "double precision:: faildph(imx1),fsdepth(imx1)",
        "double precision:: faildph(imx1),fsdepth(imx1)`r`ndouble precision:: tao_trace(imx1),taoc_trace(imx1),cvbar_trace(imx1),erorate_raw_trace(imx1),erorate_clamped_trace(imx1),deporate_raw_trace(imx1),deporate_clamped_trace(imx1)"
    )
    $includeDirectionalDepositionProbe = ((Split-Path $PatchPath -Leaf) -match "deposition_directional_velocity")
    if ($includeDirectionalDepositionProbe) {
        $text = $text.Replace(
            "double precision:: faildph(imx1),fsdepth(imx1)`r`ndouble precision:: tao_trace(imx1),taoc_trace(imx1),cvbar_trace(imx1),erorate_raw_trace(imx1),erorate_clamped_trace(imx1),deporate_raw_trace(imx1),deporate_clamped_trace(imx1)",
            "double precision:: faildph(imx1),fsdepth(imx1)`r`ndouble precision:: tao_trace(imx1),taoc_trace(imx1),cvbar_trace(imx1),erorate_raw_trace(imx1),erorate_clamped_trace(imx1),deporate_raw_trace(imx1),deporate_clamped_trace(imx1)`r`ndouble precision:: vorth_trace(imx1),vcomp_trace(imx1),absubar_recomputed_trace(imx1),fvpredi2_trace(imx1,maxdirection)`r`ninteger:: selected_is_vorth_trace(imx1)"
        )
    }
    $text = $text.Replace(
        "erorate=0.`r`ndeporate=0.",
        "erorate=0.`r`ndeporate=0.`r`ntao_trace=0.; taoc_trace=0.; cvbar_trace=0.`r`nerorate_raw_trace=0.; erorate_clamped_trace=0.`r`ndeporate_raw_trace=0.; deporate_clamped_trace=0.`r`nerosion_gate_trace=0; rholimit_clamp_trace=0; erodible_clamp_trace=0; deposition_gate_trace=0"
    )
    if ($includeDirectionalDepositionProbe) {
        $text = $text.Replace(
            "erorate=0.`r`ndeporate=0.`r`ntao_trace=0.; taoc_trace=0.; cvbar_trace=0.`r`nerorate_raw_trace=0.; erorate_clamped_trace=0.`r`ndeporate_raw_trace=0.; deporate_clamped_trace=0.`r`nerosion_gate_trace=0; rholimit_clamp_trace=0; erodible_clamp_trace=0; deposition_gate_trace=0",
            "erorate=0.`r`ndeporate=0.`r`ntao_trace=0.; taoc_trace=0.; cvbar_trace=0.`r`nerorate_raw_trace=0.; erorate_clamped_trace=0.`r`ndeporate_raw_trace=0.; deporate_clamped_trace=0.`r`nerosion_gate_trace=0; rholimit_clamp_trace=0; erodible_clamp_trace=0; deposition_gate_trace=0`r`nvorth_trace=0.; vcomp_trace=0.; absubar_recomputed_trace=0.; fvpredi2_trace=0.; selected_is_vorth_trace=0"
        )
        $text = $text.Replace(
            "    absubar(i)=max(vorth,vcomp)",
            "    vorth_trace(i)=vorth`r`n    vcomp_trace(i)=vcomp`r`n    selected_is_vorth_trace(i)=1`r`n    if (vcomp>vorth) selected_is_vorth_trace(i)=0`r`n    absubar(i)=max(vorth,vcomp)`r`n    absubar_recomputed_trace(i)=max(vorth,vcomp)`r`n    fvpredi2_trace(i,:)=fvpredi2(i,:)"
        )
    }
    $text = $text.Replace(
        "        taoc=ctao(zo(i))+(1-cs)*cv(i)*(rhos-rhow)*grav*fh(i)*cos(slo(i))**2.*tan(phit(zo(i)))`r`n        if (fhpredi1(i)>0.05 .and. tao>taoc) then`r`n            erorate(i)=kero(zo(i))*(tao-taoc)`r`n            !eroindx(i)=1`r`n        end if",
        "        taoc=ctao(zo(i))+(1-cs)*cv(i)*(rhos-rhow)*grav*fh(i)*cos(slo(i))**2.*tan(phit(zo(i)))`r`n        tao_trace(i)=tao`r`n        taoc_trace(i)=taoc`r`n        if (fhpredi1(i)>0.05 .and. tao>taoc) then`r`n            erosion_gate_trace(i)=1`r`n            erorate(i)=kero(zo(i))*(tao-taoc)`r`n            !eroindx(i)=1`r`n        end if`r`n        erorate_raw_trace(i)=erorate(i)"
    )
    $text = $text.Replace(
        "    erorate(i)=(rholimit(i)-frhopredi1(i))*fhpredi1(i)/(rhoero-rholimit(i))/dt`r`n    end if",
        "    rholimit_clamp_trace(i)=1`r`n    erorate(i)=(rholimit(i)-frhopredi1(i))*fhpredi1(i)/(rhoero-rholimit(i))/dt`r`n    end if"
    )
    $text = $text.Replace(
        "    erorate(i)=(inierodithick(i))/dt`r`n    tempinierodithick(i)=0.`r`n    end if",
        "    erodible_clamp_trace(i)=1`r`n    erorate(i)=(inierodithick(i))/dt`r`n    tempinierodithick(i)=0.`r`n    end if`r`n    erorate_clamped_trace(i)=erorate(i)"
    )
    $text = $text.Replace(
        "                        fvdepo(i)=2./5./d50*(grav*sinthetae*frhopredi1(i)/0.02/rhos)**0.5*lambdainverse*fhpredi1(i)**1.5`r`nend do",
        "                        fvdepo(i)=2./5./d50*(grav*sinthetae*frhopredi1(i)/0.02/rhos)**0.5*lambdainverse*fhpredi1(i)**1.5`r`nend do"
    )
    $text = $text.Replace(
        "            cvbar=(parai* cellareacal(i)+paran* cellareacal(nq)) / (fhpredi(i)*cellareacal(i)+fhpredi(nq)*cellareacal(nq))",
        "            cvbar=(parai* cellareacal(i)+paran* cellareacal(nq)) / (fhpredi(i)*cellareacal(i)+fhpredi(nq)*cellareacal(nq))`r`n            cvbar_trace(i)=cvbar"
    )
    $text = $text.Replace(
        "            if(cv(i) >0.65) then            `r`n                deporate(i) = -fhpredi1(i) * cv(i) / cvstar / dt !cv(i) / cvstar / dt",
        "            if(cv(i) >0.65) then            `r`n                deposition_gate_trace(i)=1`r`n                deporate(i) = -fhpredi1(i) * cv(i) / cvstar / dt !cv(i) / cvstar / dt`r`n                deporate_raw_trace(i)=deporate(i)"
    )
    $text = $text.Replace(
        "        deporate(i)=coedepo*(1.-3./2.*absubar(i)/fvdepo(i))*(cvlimit(i)-cv(i))/cvstar*absubar(i)",
        "        deposition_gate_trace(i)=1`r`n        deporate(i)=coedepo*(1.-3./2.*absubar(i)/fvdepo(i))*(cvlimit(i)-cv(i))/cvstar*absubar(i)`r`n        deporate_raw_trace(i)=deporate(i)"
    )
    $text = $text.Replace(
        "    tempdebdepothick(i)=debdepothick(i)+abs(deporate(i)*dt)",
        "    deporate_clamped_trace(i)=deporate(i)`r`n    tempdebdepothick(i)=debdepothick(i)+abs(deporate(i)*dt)"
    )
    $positiveDepositionVariants = @(
        "first_nonzero_deporate",
        "first_tempdebdepothick_positive",
        "first_deposit_writer_positive",
        "target_sparse_checkpoint",
        "target_600s_tracked",
        "restore_extended_upstream_pre222_history"
    )
    if ($BuildVariantSafe -in $positiveDepositionVariants) {
        $probeMode = $BuildVariantSafe
        $trackedCondition = "i==36761 .or. i==36762 .or. i==36763 .or. i==37023 .or. i==50752 .or. i==87236 .or. i==28679 .or. i==22544 .or. i==87235 .or. i==28680 .or. i==50753 .or. i==87237 .or. i==87545 .or. i==147642 .or. i==50442 .or. i==178425 .or. i==51062 .or. i==50751 .or. i==122238 .or. i==66575 .or. i==98776 .or. i==98779 .or. i==89955 .or. i==98762 .or. i==190539 .or. i==107309 .or. i==107310 .or. i==148221 .or. i==190538 .or. i==35538 .or. i==156303 .or. i==156441 .or. i==156442 .or. i==156461 .or. i==84745 .or. i==156603 .or. i==64307 .or. i==156604 .or. i==156607 .or. i==72728 .or. i==73036 .or. i==72419 .or. i==179354 .or. i==86927 .or. i==28370 .or. i==101528 .or. i==73035 .or. i==190212 .or. i==86926 .or. i==189902 .or. i==189283 .or. i==28371 .or. i==180284 .or. i==98099 .or. i==101527 .or. i==244218 .or. i==131891 .or. i==112343 .or. i==177804 .or. i==62772 .or. i==82211 .or. i==189592 .or. i==142321 .or. i==244528 .or. i==200451 .or. i==188663"
        $triggerCondition = "sum(abs(deporate_clamped_trace))>0.d0"
        $eventType = "first_nonzero_deporate"
        $rowCondition = "abs(deporate_raw_trace(i))>0.d0 .or. abs(deporate_clamped_trace(i))>0.d0 .or. $trackedCondition"
        if ($BuildVariantSafe -eq "first_tempdebdepothick_positive") {
            $triggerCondition = "maxval(tempdebdepothick)>0.d0"
            $eventType = "first_tempdebdepothick_positive"
            $rowCondition = "tempdebdepothick(i)>0.d0 .or. $trackedCondition"
        } elseif ($BuildVariantSafe -eq "first_deposit_writer_positive") {
            $triggerCondition = "maxval(ele-eleori)>0.d0"
            $eventType = "first_deposit_writer_positive"
            $rowCondition = "max(ele(i)-eleori(i),0.d0)>0.d0 .or. $trackedCondition"
        } elseif ($BuildVariantSafe -eq "target_sparse_checkpoint") {
            $triggerCondition = "((tnow>=220.d0 .and. tnow<221.d0) .or. (tnow>=260.d0 .and. tnow<261.d0) .or. tnow>=600.d0)"
            $eventType = "target_sparse_checkpoint"
            $rowCondition = "$trackedCondition .or. abs(deporate_clamped_trace(i))>0.d0 .or. tempdebdepothick(i)>0.d0 .or. max(ele(i)-eleori(i),0.d0)>0.d0"
        } elseif ($BuildVariantSafe -eq "target_600s_tracked") {
            $triggerCondition = "tnow>=600.d0"
            $eventType = "target_600s_tracked"
            $rowCondition = "$trackedCondition .or. abs(deporate_clamped_trace(i))>0.d0 .or. tempdebdepothick(i)>0.d0 .or. max(ele(i)-eleori(i),0.d0)>0.d0"
        }
        if ($includeDirectionalDepositionProbe) {
            $dumpBlock = @"
cv=(frho-rhow)/(rhos-rhow)
if ($triggerCondition) then
    open(996,file='original_deposition_positive_event.txt',status='replace')
    write(996,'(A)') 'cell_id tnow tnext tfail gindx fdepth fsdepth inierodithick tempfsh tempfsrho fh frho fhpredi1 fhpredi fhpredi2 frhopredi frhopredi2 cv cvbar cvlimit tao taoc erorate_raw erorate_clamped rholimit_clamp erodible_clamp deporate_raw deporate_clamped abs_deporate_dt deposition_gate absubar fvdepo rhodepo tempdebdepothick ele tempele ele_minus_eleori deposit_equiv erosion_equiv vorth vcomp selected_is_vorth absubar_recomputed fvpredi2_1 fvpredi2_2 fvpredi2_3 fvpredi2_4 fvpredi2_5 fvpredi2_6 fvpredi2_7 fvpredi2_8'
    do i=1,imx1
        if ($rowCondition) then
            write(996,*) i,tnow,tnext,tfail(i),gindx(i),fdepth(i),fsdepth(i),inierodithick(i),tempfsh(i),tempfsrho(i),fh(i),frho(i),fhpredi1(i),fhpredi(i),fhpredi2(i),frhopredi(i),frhopredi2(i),cv(i),cvbar_trace(i),cvlimit(i),tao_trace(i),taoc_trace(i),erorate_raw_trace(i),erorate_clamped_trace(i),rholimit_clamp_trace(i),erodible_clamp_trace(i),deporate_raw_trace(i),deporate_clamped_trace(i),abs(deporate_clamped_trace(i)*dt),deposition_gate_trace(i),absubar(i),fvdepo(i),rhodepo(i),tempdebdepothick(i),ele(i),tempele(i),ele(i)-eleori(i),max(ele(i)-eleori(i),0.d0),erodph(i),vorth_trace(i),vcomp_trace(i),selected_is_vorth_trace(i),absubar_recomputed_trace(i),fvpredi2_trace(i,1),fvpredi2_trace(i,2),fvpredi2_trace(i,3),fvpredi2_trace(i,4),fvpredi2_trace(i,5),fvpredi2_trace(i,6),fvpredi2_trace(i,7),fvpredi2_trace(i,8)
        end if
    end do
    close(996)
    open(997,file='original_deposition_positive_event_meta.json',status='replace')
    write(997,'(A)') '{'
    write(997,'(A)') '  "provider": "instrumented_original_deposition_directional_velocity_probe",'
    write(997,'(A)') '  "probe_mode": "$probeMode",'
    write(997,'(A)') '  "event_type": "$eventType",'
    write(997,'(A)') '  "trigger_condition": "$triggerCondition",'
    write(997,'(A)') '  "directional_fields": ["vorth", "vcomp", "selected_is_vorth", "absubar_recomputed", "fvpredi2_1..fvpredi2_8"],'
    write(997,'(A)') '  "debug_stop_after_dump": true,'
    write(997,'(A)') '  "not_fresh_output_reproduction": true'
    write(997,'(A)') '}'
    close(997)
    stop 0
end if
"@
        } else {
        $dumpBlock = @"
cv=(frho-rhow)/(rhos-rhow)
if ($triggerCondition) then
    open(996,file='original_deposition_positive_event.txt',status='replace')
    write(996,'(A)') 'cell_id tnow tnext tfail gindx fdepth fsdepth inierodithick tempfsh tempfsrho fh frho fhpredi1 fhpredi fhpredi2 frhopredi frhopredi2 cv cvbar cvlimit tao taoc erorate_raw erorate_clamped rholimit_clamp erodible_clamp deporate_raw deporate_clamped abs_deporate_dt deposition_gate absubar fvdepo rhodepo tempdebdepothick ele tempele ele_minus_eleori deposit_equiv erosion_equiv'
    do i=1,imx1
        if ($rowCondition) then
            write(996,*) i,tnow,tnext,tfail(i),gindx(i),fdepth(i),fsdepth(i),inierodithick(i),tempfsh(i),tempfsrho(i),fh(i),frho(i),fhpredi1(i),fhpredi(i),fhpredi2(i),frhopredi(i),frhopredi2(i),cv(i),cvbar_trace(i),cvlimit(i),tao_trace(i),taoc_trace(i),erorate_raw_trace(i),erorate_clamped_trace(i),rholimit_clamp_trace(i),erodible_clamp_trace(i),deporate_raw_trace(i),deporate_clamped_trace(i),abs(deporate_clamped_trace(i)*dt),deposition_gate_trace(i),absubar(i),fvdepo(i),rhodepo(i),tempdebdepothick(i),ele(i),tempele(i),ele(i)-eleori(i),max(ele(i)-eleori(i),0.d0),erodph(i)
        end if
    end do
    close(996)
    open(997,file='original_deposition_positive_event_meta.json',status='replace')
    write(997,'(A)') '{'
    write(997,'(A)') '  "provider": "instrumented_original_deposition_positive_probe",'
    write(997,'(A)') '  "probe_mode": "$probeMode",'
    write(997,'(A)') '  "event_type": "$eventType",'
    write(997,'(A)') '  "trigger_condition": "$triggerCondition",'
    write(997,'(A)') '  "tracked_cells": [36761, 36762, 36763, 37023, 50752, 87236, 28679, 22544, 87235, 28680, 50753, 87237, 87545, 147642, 50442, 178425, 51062, 50751, 122238, 66575, 98776, 98779, 89955, 98762, 190539, 107309, 107310, 148221, 190538, 35538, 156303, 156441, 156442, 156461, 84745, 156603, 64307, 156604, 156607, 72728, 73036, 72419, 179354, 86927, 28370, 101528, 73035, 190212, 86926, 189902, 189283, 28371, 180284, 98099, 101527, 244218, 131891, 112343, 177804, 62772, 82211, 189592, 142321, 244528, 200451, 188663],'
    write(997,'(A)') '  "debug_stop_after_dump": true,'
    write(997,'(A)') '  "not_fresh_output_reproduction": true'
    write(997,'(A)') '}'
    close(997)
    stop 0
end if
"@
        }
    } elseif ($BuildVariantSafe -eq "original_deposition_first_event_early_stop") {
        $dumpBlock = @"
cv=(frho-rhow)/(rhos-rhow)
if (sum(abs(deporate_clamped_trace))>0.d0 .or. sum(deposition_gate_trace)>0) then
    open(996,file='original_deposition_first_event.txt',status='replace')
    write(996,'(A)') 'cell_id tnow tnext tfail gindx fdepth fsdepth inierodithick tempfsh tempfsrho fhpredi1 fhpredi fhpredi2 frhopredi frhopredi2 cv cvbar cvlimit tao taoc erorate_raw erorate_clamped rholimit_clamp erodible_clamp deporate_raw deporate_clamped deposition_gate absubar fvdepo rhodepo tempdebdepothick ele tempele deposit_equiv erosion_equiv'
    do i=1,imx1
        if (deposition_gate_trace(i)/=0 .or. deporate_raw_trace(i)/=0.d0 .or. deporate_clamped_trace(i)/=0.d0 .or. tempdebdepothick(i)>0.d0 .or. max(ele(i)-eleori(i),0.d0)>0.d0) then
            write(996,*) i,tnow,tnext,tfail(i),gindx(i),fdepth(i),fsdepth(i),inierodithick(i),tempfsh(i),tempfsrho(i),fhpredi1(i),fhpredi(i),fhpredi2(i),frhopredi(i),frhopredi2(i),cv(i),cvbar_trace(i),cvlimit(i),tao_trace(i),taoc_trace(i),erorate_raw_trace(i),erorate_clamped_trace(i),rholimit_clamp_trace(i),erodible_clamp_trace(i),deporate_raw_trace(i),deporate_clamped_trace(i),deposition_gate_trace(i),absubar(i),fvdepo(i),rhodepo(i),tempdebdepothick(i),ele(i),tempele(i),max(ele(i)-eleori(i),0.d0),erodph(i)
        end if
    end do
    close(996)
    open(997,file='original_deposition_first_event_meta.json',status='replace')
    write(997,'(A)') '{'
    write(997,'(A)') '  "provider": "instrumented_original_deposition_first_event",'
    write(997,'(A)') '  "probe_mode": "first_deposition_event_early_stop",'
    write(997,'(A)') '  "dump_point": "after accepted writeback when first deposition gate or deporate appears",'
    write(997,'(A)') '  "debug_stop_after_dump": true,'
    write(997,'(A)') '  "not_fresh_output_reproduction": true'
    write(997,'(A)') '}'
    close(997)
    stop 0
end if
"@
    } else {
        $dumpBlock = @"
cv=(frho-rhow)/(rhos-rhow)
if (tnow>=600.d0) then
    open(996,file='original_downstream_internal_600s.txt',status='replace')
    write(996,'(A)') 'cell_id tnow tnext tfail gindx fdepth fsdepth inierodithick tempfsh tempfsrho fhpredi1 fhpredi fhpredi2 frhopredi frhopredi2 cv cvbar cvlimit tao taoc erorate_raw erorate_clamped rholimit_clamp erodible_clamp deporate_raw deporate_clamped deposition_gate absubar fvdepo rhodepo tempdebdepothick ele tempele deposit_equiv erosion_equiv'
    do i=1,imx1
        if (tempfsh(i)>0.d0 .or. erorate_raw_trace(i)/=0.d0 .or. erorate_clamped_trace(i)/=0.d0 .or. deporate_raw_trace(i)/=0.d0 .or. deporate_clamped_trace(i)/=0.d0 .or. erosion_gate_trace(i)/=0 .or. deposition_gate_trace(i)/=0) then
            write(996,*) i,tnow,tnext,tfail(i),gindx(i),fdepth(i),fsdepth(i),inierodithick(i),tempfsh(i),tempfsrho(i),fhpredi1(i),fhpredi(i),fhpredi2(i),frhopredi(i),frhopredi2(i),cv(i),cvbar_trace(i),cvlimit(i),tao_trace(i),taoc_trace(i),erorate_raw_trace(i),erorate_clamped_trace(i),rholimit_clamp_trace(i),erodible_clamp_trace(i),deporate_raw_trace(i),deporate_clamped_trace(i),deposition_gate_trace(i),absubar(i),fvdepo(i),rhodepo(i),tempdebdepothick(i),ele(i),tempele(i),max(ele(i)-eleori(i),0.d0),erodph(i)
        end if
    end do
    close(996)
    open(997,file='original_downstream_internal_600s_meta.json',status='replace')
    write(997,'(A)') '{'
    write(997,'(A)') '  "provider": "instrumented_original_dfs",'
    write(997,'(A)') '  "dump_point": "after accepted writeback when tnow>=600s",'
    write(997,'(A)') '  "debug_stop_after_dump": true,'
    write(997,'(A)') '  "not_fresh_output_reproduction": true'
    write(997,'(A)') '}'
    close(997)
    stop 0
end if
"@
    }
    $text = $text.Replace("cv=(frho-rhow)/(rhos-rhow)", $dumpBlock)

    if ((Split-Path $PatchPath -Leaf) -match "extended_upstream_pre222_history") {
        $text = $text.Replace("tnow>=226.5d0", "tnow>=220.0d0")
        $text = $text.Replace(
            "i==35978 .or. i==36238 .or. i==36239",
            "i==35978 .or. i==36238 .or. i==36239 .or. i==36500"
        )
        $text = $text.Replace(
            "i==36238 .or. i==36239",
            "i==36238 .or. i==36239 .or. i==36500"
        )
        if ((Split-Path $PatchPath -Leaf) -match "neighbor_cells") {
            $text = $text.Replace(
                "i==35978 .or. i==36238 .or. i==36239 .or. i==36500",
                "i==35978 .or. i==36238 .or. i==36239 .or. i==36500 .or. i==36762 .or. i==36761"
            )
            $text = $text.Replace(
                "i==36238 .or. i==36239 .or. i==36500",
                "i==36238 .or. i==36239 .or. i==36500 .or. i==36762 .or. i==36761"
            )
        }
    }
    elseif ((Split-Path $PatchPath -Leaf) -match "extended_upstream_history") {
        $text = $text.Replace("tnow>=226.5d0", "tnow>=222.0d0")
        $text = $text.Replace(
            "i==35978 .or. i==36238 .or. i==36239",
            "i==35978 .or. i==36238 .or. i==36239 .or. i==36500"
        )
    }
    Set-Content -Path $dfs -Value $text -Encoding UTF8
    Write-Log "Applied downstream DFS 600s dump instrumentation."
}

function Apply-MinimalDfsGateInstrumentation {
    param([string]$ProjectDir)
    $main = Join-Path $ProjectDir "edda main program.F90"
    $dfs = Join-Path $ProjectDir "dfs.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dfs)) { throw "Missing dfs.F90 in $ProjectDir" }

    $mainText = Get-Content $main -Raw
    if ($mainText -notmatch "before_dfs") {
        $mainText = $mainText.Replace(
            "if (debrissimul) then`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)",
            "if (debrissimul) then`r`ncall dump_instrumented_progress('before_dfs')`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)`r`ncall dump_instrumented_progress('after_dfs')"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $text = Get-Content $dfs -Raw
    if ($text -match "original_dfs_minimal_gate_dump") {
        Write-Log "Minimal DFS gate instrumentation already present."
        return
    }

    $text = $text.Replace(
        "integer:: u(28),ncc,nccs,eroindx(imx1),tempgindx(imx1)",
        "integer:: u(28),ncc,nccs,eroindx(imx1),tempgindx(imx1)`r`ninteger:: trace_cv_lt_cvlimit,trace_fhpredi1_gt_005,trace_tau_gt_taoc,trace_all_erosion_gate,trace_tempfsh_pos,trace_deposition_gate"
    )
    $text = $text.Replace(
        "double precision:: finalnvol,finalcvol,retaindeposit,soliddepth",
        "double precision:: finalnvol,finalcvol,retaindeposit,soliddepth`r`ndouble precision:: trace_sum_erorate,trace_max_erorate,trace_sum_deporate,trace_max_abs_deporate"
    )
    $text = $text.Replace(
        "cv=0.`r`ngrav=9.81",
        "call dump_instrumented_progress('dfs_entry')`r`ncv=0.`r`ngrav=9.81"
    )
    $text = $text.Replace(
        "! main loop`r`ndo 1000, nt=1,maxnts",
        "call dump_instrumented_progress('dfs_before_main_loop')`r`n! main loop`r`ndo 1000, nt=1,maxnts"
    )
    $text = $text.Replace(
        "erorate=0.`r`ndeporate=0.",
        "erorate=0.`r`ndeporate=0.`r`ntrace_cv_lt_cvlimit=0; trace_fhpredi1_gt_005=0; trace_tau_gt_taoc=0; trace_all_erosion_gate=0`r`ntrace_tempfsh_pos=0; trace_deposition_gate=0`r`ntrace_sum_erorate=0.d0; trace_max_erorate=0.d0; trace_sum_deporate=0.d0; trace_max_abs_deporate=0.d0"
    )
    $text = $text.Replace(
        "        taoc=ctao(zo(i))+(1-cs)*cv(i)*(rhos-rhow)*grav*fh(i)*cos(slo(i))**2.*tan(phit(zo(i)))`r`n        if (fhpredi1(i)>0.05 .and. tao>taoc) then",
        "        taoc=ctao(zo(i))+(1-cs)*cv(i)*(rhos-rhow)*grav*fh(i)*cos(slo(i))**2.*tan(phit(zo(i)))`r`n        if (cv(i)<cvlimit(i)) trace_cv_lt_cvlimit=trace_cv_lt_cvlimit+1`r`n        if (fhpredi1(i)>0.05d0) trace_fhpredi1_gt_005=trace_fhpredi1_gt_005+1`r`n        if (tao>taoc) trace_tau_gt_taoc=trace_tau_gt_taoc+1`r`n        if (cv(i)<cvlimit(i) .and. fhpredi1(i)>0.05d0 .and. tao>taoc) trace_all_erosion_gate=trace_all_erosion_gate+1`r`n        if (fhpredi1(i)>0.05 .and. tao>taoc) then"
    )
    $text = $text.Replace(
        "        deporate(i)=coedepo*(1.-3./2.*absubar(i)/fvdepo(i))*(cvlimit(i)-cv(i))/cvstar*absubar(i)",
        "        trace_deposition_gate=trace_deposition_gate+1`r`n        deporate(i)=coedepo*(1.-3./2.*absubar(i)/fvdepo(i))*(cvlimit(i)-cv(i))/cvstar*absubar(i)"
    )
    $text = $text.Replace(
        "fhpredi(:)=fhpredi1(:)+(erorate(:)+deporate(:))*dt+tempfsh(:)",
        "trace_tempfsh_pos=count(tempfsh>0.d0)`r`ntrace_sum_erorate=sum(erorate)`r`ntrace_max_erorate=maxval(erorate)`r`ntrace_sum_deporate=sum(deporate)`r`ntrace_max_abs_deporate=maxval(abs(deporate))`r`nfhpredi(:)=fhpredi1(:)+(erorate(:)+deporate(:))*dt+tempfsh(:)"
    )
    $text = $text.Replace(
        "write (*,*) 'tnow',tnow,'dt',dt",
        "write (*,*) 'tnow',tnow,'dt',dt`r`nopen(995,file='original_dfs_minimal_gate_dump.txt',status='unknown',position='append')`r`nwrite(995,*) nt,tnow,dt,trace_tempfsh_pos,trace_cv_lt_cvlimit,trace_fhpredi1_gt_005,trace_tau_gt_taoc,trace_all_erosion_gate,trace_sum_erorate,trace_max_erorate,trace_deposition_gate,trace_sum_deporate,trace_max_abs_deporate`r`nclose(995)`r`nif (tnow>=600.d0) then`r`nopen(994,file='original_dfs_minimal_gate_dump_meta.json',status='replace')`r`nwrite(994,'(A)') '{'`r`nwrite(994,'(A)') '  ""provider"": ""instrumented_original_dfs_minimal_gate_dump"",'`r`nwrite(994,'(A)') '  ""dump_point"": ""accepted step aggregate after tnow update"",'`r`nwrite(994,'(A)') '  ""columns"": ""nt tnow dt count_tempfsh_gt0 count_cv_lt_cvlimit count_fhpredi1_gt_0_05 count_tau_gt_taoc count_all_erosion_gate sum_erorate max_erorate count_deposition_gate sum_deporate max_abs_deporate"",'`r`nwrite(994,'(A)') '  ""debug_stop_after_600s"": true,'`r`nwrite(994,'(A)') '  ""not_fresh_output_reproduction"": true'`r`nwrite(994,'(A)') '}'`r`nclose(994)`r`nstop 0`r`nend if"
    )

    Set-Content -Path $dfs -Value $text -Encoding UTF8
    Write-Log "Applied minimal DFS gate aggregate instrumentation."
}

function Apply-OriginalErosionEventProbeInstrumentation {
    param([string]$ProjectDir)
    $main = Join-Path $ProjectDir "edda main program.F90"
    $dfs = Join-Path $ProjectDir "dfs.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dfs)) { throw "Missing dfs.F90 in $ProjectDir" }

    $mainText = Get-Content $main -Raw
    if ($mainText -notmatch "before_dfs") {
        $mainText = $mainText.Replace(
            "if (debrissimul) then`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)",
            "if (debrissimul) then`r`ncall dump_instrumented_progress('before_dfs')`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)`r`ncall dump_instrumented_progress('after_dfs')"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $text = Get-Content $dfs -Raw
    if ($text -match "original_erosion_event_probe") {
        Write-Log "Original erosion event probe instrumentation already present."
        return
    }
    if ($BuildVariantSafe -in @("progress_only", "no_large_array_dump")) {
        $text = $text.Replace(
            "cv=0.`r`ngrav=9.81",
            "call dump_instrumented_progress('dfs_entry')`r`ncv=0.`r`ngrav=9.81"
        )
        $text = $text.Replace(
            "! main loop`r`ndo 1000, nt=1,maxnts",
            "call dump_instrumented_progress('dfs_before_main_loop')`r`n! main loop`r`ndo 1000, nt=1,maxnts"
        )
        $text = $text.Replace(
            "write (*,*) 'tnow',tnow,'dt',dt",
            "call dump_instrumented_progress('accepted_step_end')`r`nwrite (*,*) 'tnow',tnow,'dt',dt"
        )
        Set-Content -Path $dfs -Value $text -Encoding UTF8
        Write-Log "Applied original DFS progress-only instrumentation without event trace arrays."
        return
    }

    $text = $text.Replace(
        "integer:: u(28),ncc,nccs,eroindx(imx1),tempgindx(imx1)",
        "integer:: u(28),ncc,nccs,eroindx(imx1),tempgindx(imx1)`r`ninteger:: trace_cv_lt_cvlimit,trace_fhpredi1_gt_005,trace_tau_gt_taoc,trace_all_erosion_gate,trace_erorate_pos,trace_event_cells_written"
    )
    $text = $text.Replace(
        "double precision:: finalnvol,finalcvol,retaindeposit,soliddepth",
        "double precision:: finalnvol,finalcvol,retaindeposit,soliddepth`r`ndouble precision:: trace_sum_erorate,trace_max_erorate,trace_eleori_minus_ele_sum,trace_eleori_minus_ele_max`r`ndouble precision:: trace_tao(imx1),trace_taoc(imx1)"
    )
    $text = $text.Replace(
        "cv=0.`r`ngrav=9.81",
        "call dump_instrumented_progress('dfs_entry')`r`ncv=0.`r`ngrav=9.81`r`ntrace_tao=0.d0; trace_taoc=0.d0"
    )
    $text = $text.Replace(
        "! main loop`r`ndo 1000, nt=1,maxnts",
        "call dump_instrumented_progress('dfs_before_main_loop')`r`n! main loop`r`ndo 1000, nt=1,maxnts"
    )
    $text = $text.Replace(
        "erorate=0.`r`ndeporate=0.",
        "erorate=0.`r`ndeporate=0.`r`ntrace_cv_lt_cvlimit=0; trace_fhpredi1_gt_005=0; trace_tau_gt_taoc=0; trace_all_erosion_gate=0; trace_erorate_pos=0`r`ntrace_sum_erorate=0.d0; trace_max_erorate=0.d0; trace_eleori_minus_ele_sum=0.d0; trace_eleori_minus_ele_max=0.d0"
    )
    $text = $text.Replace(
        "        taoc=ctao(zo(i))+(1-cs)*cv(i)*(rhos-rhow)*grav*fh(i)*cos(slo(i))**2.*tan(phit(zo(i)))`r`n        if (fhpredi1(i)>0.05 .and. tao>taoc) then",
        "        taoc=ctao(zo(i))+(1-cs)*cv(i)*(rhos-rhow)*grav*fh(i)*cos(slo(i))**2.*tan(phit(zo(i)))`r`n        trace_tao(i)=tao`r`n        trace_taoc(i)=taoc`r`n        if (cv(i)<cvlimit(i)) trace_cv_lt_cvlimit=trace_cv_lt_cvlimit+1`r`n        if (fhpredi1(i)>0.05d0) trace_fhpredi1_gt_005=trace_fhpredi1_gt_005+1`r`n        if (tao>taoc) trace_tau_gt_taoc=trace_tau_gt_taoc+1`r`n        if (cv(i)<cvlimit(i) .and. fhpredi1(i)>0.05d0 .and. tao>taoc) trace_all_erosion_gate=trace_all_erosion_gate+1`r`n        if (fhpredi1(i)>0.05 .and. tao>taoc) then"
    )
    $eventDump = @"
trace_sum_erorate=sum(erorate)
trace_max_erorate=maxval(erorate)
trace_erorate_pos=count(erorate>0.d0)
trace_eleori_minus_ele_sum=sum(max(eleori-ele,0.d0))
trace_eleori_minus_ele_max=maxval(max(eleori-ele,0.d0))
open(995,file='original_erosion_event_probe_progress.txt',status='unknown',position='append')
write(995,*) nt,tnow,dt,trace_cv_lt_cvlimit,trace_fhpredi1_gt_005,trace_tau_gt_taoc,trace_all_erosion_gate,trace_erorate_pos,trace_sum_erorate,trace_max_erorate,trace_eleori_minus_ele_sum,trace_eleori_minus_ele_max
close(995)
if (trace_erorate_pos>0) then
    open(996,file='original_erosion_event_probe.csv',status='replace')
    write(996,'(A)') 'cell_id,tnow,dt,tfail,gindx,fdepth,fhpredi1,fh,cv,cvlimit,tau,taoc,tau_minus_taoc,erorate,eleori_minus_ele,zone_id'
    trace_event_cells_written=0
    do i=1,imx1
        if (erorate(i)>0.d0 .and. trace_event_cells_written<20) then
            trace_event_cells_written=trace_event_cells_written+1
            write(996,*) i,',',tnow,',',dt,',',tfail(i),',',gindx(i),',',fdepth(i),',',fhpredi1(i),',',fh(i),',',cv(i),',',cvlimit(i),',',trace_tao(i),',',trace_taoc(i),',',trace_tao(i)-trace_taoc(i),',',erorate(i),',',max(eleori(i)-ele(i),0.d0),',',zo(i)
        end if
    end do
    close(996)
    open(997,file='original_erosion_event_probe_meta.json',status='replace')
    write(997,'(A)') '{'
    write(997,'(A)') '  "provider": "instrumented_original_erosion_event_probe",'
    write(997,'(A)') '  "dump_point": "first accepted step with erorate > 0",'
    write(997,'(A)') '  "debug_stop_after_first_event": true,'
    write(997,'(A)') '  "not_fresh_output_reproduction": true,'
    write(997,'(A,I0,A)') '  "event_positive_erorate_count": ', trace_erorate_pos, ','
    write(997,'(A,ES24.16,A)') '  "event_erorate_sum": ', trace_sum_erorate, ','
    write(997,'(A,ES24.16,A)') '  "event_erorate_max": ', trace_max_erorate, ','
    write(997,'(A,ES24.16,A)') '  "event_eleori_minus_ele_sum": ', trace_eleori_minus_ele_sum, ','
    write(997,'(A,ES24.16)') '  "event_eleori_minus_ele_max": ', trace_eleori_minus_ele_max
    write(997,'(A)') '}'
    close(997)
    stop 0
end if
fhpredi(:)=fhpredi1(:)+(erorate(:)+deporate(:))*dt+tempfsh(:)
"@
    $text = $text.Replace(
        "fhpredi(:)=fhpredi1(:)+(erorate(:)+deporate(:))*dt+tempfsh(:)",
        $eventDump
    )

    Set-Content -Path $dfs -Value $text -Encoding UTF8
    Write-Log "Applied original DFS first erosion event probe instrumentation."
}

function Apply-OriginalFirstEventTauComponentInstrumentation {
    param([string]$ProjectDir)
    $main = Join-Path $ProjectDir "edda main program.F90"
    $dfs = Join-Path $ProjectDir "dfs.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dfs)) { throw "Missing dfs.F90 in $ProjectDir" }

    Apply-MainProgressInstrumentation -ProjectDir $ProjectDir

    $mainText = Get-Content $main -Raw
    if ($mainText -notmatch "before_dfs") {
        $mainText = $mainText.Replace(
            "if (debrissimul) then`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)",
            "if (debrissimul) then`r`ncall dump_instrumented_progress('before_dfs')`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)`r`ncall dump_instrumented_progress('after_dfs')"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $text = Get-Content $dfs -Raw
    if ($text -match "original_first_event_tau_components") {
        Write-Log "Original first-event tau component instrumentation already present."
        return
    }
    $text = [regex]::Replace(
        $text,
        '(?m)^voltonode\s*=\s*0\.\s*$',
        "if (allocated(voltonode)) voltonode=0.`r`ncall dump_instrumented_progress('dfs_after_stormdrain_module_zero_guard')"
    )
    $text = $text.Replace(
        "integer:: u(28),ncc,nccs,eroindx(imx1),tempgindx(imx1)",
        "integer:: u(28),ncc,nccs,eroindx(imx1),tempgindx(imx1)`r`ninteger:: trace_cv_lt_cvlimit,trace_fhpredi1_gt_005,trace_tau_gt_taoc,trace_all_erosion_gate,trace_erorate_pos,trace_event_cells_written"
    )
    $text = $text.Replace(
        "double precision:: finalnvol,finalcvol,retaindeposit,soliddepth",
        "double precision:: finalnvol,finalcvol,retaindeposit,soliddepth`r`ndouble precision:: trace_sum_erorate,trace_max_erorate,trace_eleori_minus_ele_sum,trace_eleori_minus_ele_max`r`ndouble precision:: trace_tao(imx1),trace_taoc(imx1),trace_sfy(imx1),trace_sfmiu(imx1),trace_sfmanning(imx1),trace_absubar(imx1),trace_gammadeb(imx1)`r`ndouble precision:: trace_manningbar(imx1),trace_miudebris(imx1),trace_coemiu(imx1),trace_coemanning(imx1),trace_cvbar(imx1),trace_vorth(imx1),trace_vcomp(imx1)"
    )
    $text = $text.Replace(
        "cv=0.`r`ngrav=9.81",
        "call dump_instrumented_progress('dfs_entry')`r`ncv=0.`r`ngrav=9.81`r`ntrace_tao=0.d0; trace_taoc=0.d0; trace_sfy=0.d0; trace_sfmiu=0.d0; trace_sfmanning=0.d0; trace_absubar=0.d0; trace_gammadeb=0.d0`r`ntrace_manningbar=0.d0; trace_miudebris=0.d0; trace_coemiu=0.d0; trace_coemanning=0.d0; trace_cvbar=0.d0; trace_vorth=0.d0; trace_vcomp=0.d0"
    )
    $text = $text.Replace(
        "! main loop`r`ndo 1000, nt=1,maxnts",
        "call dump_instrumented_progress('dfs_before_main_loop')`r`n! main loop`r`ndo 1000, nt=1,maxnts"
    )
    $text = $text.Replace(
        "erorate=0.`r`ndeporate=0.",
        "erorate=0.`r`ndeporate=0.`r`ntrace_cv_lt_cvlimit=0; trace_fhpredi1_gt_005=0; trace_tau_gt_taoc=0; trace_all_erosion_gate=0; trace_erorate_pos=0`r`ntrace_sum_erorate=0.d0; trace_max_erorate=0.d0; trace_eleori_minus_ele_sum=0.d0; trace_eleori_minus_ele_max=0.d0"
    )
    $text = $text.Replace(
        "    absubar(i)=max(vorth,vcomp)",
        "    absubar(i)=max(vorth,vcomp)`r`n    trace_vorth(i)=vorth`r`n    trace_vcomp(i)=vcomp"
    )
    $text = $text.Replace(
        "        taoc=ctao(zo(i))+(1-cs)*cv(i)*(rhos-rhow)*grav*fh(i)*cos(slo(i))**2.*tan(phit(zo(i)))`r`n        if (fhpredi1(i)>0.05 .and. tao>taoc) then",
        "        taoc=ctao(zo(i))+(1-cs)*cv(i)*(rhos-rhow)*grav*fh(i)*cos(slo(i))**2.*tan(phit(zo(i)))`r`n        trace_tao(i)=tao`r`n        trace_taoc(i)=taoc`r`n        trace_sfy(i)=sfy`r`n        trace_sfmiu(i)=sfmiu`r`n        trace_sfmanning(i)=sfmanning`r`n        trace_absubar(i)=absubar(i)`r`n        trace_gammadeb(i)=gammadeb`r`n        trace_manningbar(i)=manningbar`r`n        trace_miudebris(i)=miudebris`r`n        trace_coemiu(i)=coemiu`r`n        trace_coemanning(i)=coemanning`r`n        trace_cvbar(i)=cvbar`r`n        if (cv(i)<cvlimit(i)) trace_cv_lt_cvlimit=trace_cv_lt_cvlimit+1`r`n        if (fhpredi1(i)>0.05d0) trace_fhpredi1_gt_005=trace_fhpredi1_gt_005+1`r`n        if (tao>taoc) trace_tau_gt_taoc=trace_tau_gt_taoc+1`r`n        if (cv(i)<cvlimit(i) .and. fhpredi1(i)>0.05d0 .and. tao>taoc) trace_all_erosion_gate=trace_all_erosion_gate+1`r`n        if (fhpredi1(i)>0.05 .and. tao>taoc) then"
    )
    $eventDump = @"
trace_sum_erorate=sum(erorate)
trace_max_erorate=maxval(erorate)
trace_erorate_pos=count(erorate>0.d0)
trace_eleori_minus_ele_sum=sum(max(eleori-ele,0.d0))
trace_eleori_minus_ele_max=maxval(max(eleori-ele,0.d0))
open(995,file='original_first_event_tau_components_progress.txt',status='unknown',position='append')
write(995,*) nt,tnow,dt,trace_cv_lt_cvlimit,trace_fhpredi1_gt_005,trace_tau_gt_taoc,trace_all_erosion_gate,trace_erorate_pos,trace_sum_erorate,trace_max_erorate,trace_eleori_minus_ele_sum,trace_eleori_minus_ele_max
close(995)
if (trace_erorate_pos>0) then
    open(996,file='original_first_event_tau_components.csv',status='replace')
    write(996,'(A)') 'case_id,cell_id,tnow,dt,tfail,gindx,fdepth,fhpredi1,fh,cv,cvbar,cvlimit,frhopredi1,gammadeb,manning,manningbar,miudebris,coemiu,coemanning,sfy,sfmiu,sfmanning,absubar,vorth,vcomp,tau,taoc,tau_minus_taoc,kero,erorate,deporate,ele,tempele,eleori,eleori_minus_ele,zone_id,output_mask_gindx,threshold_pass'
    trace_event_cells_written=0
    do i=1,imx1
        if ((i==36761 .or. i==36762 .or. i==36763 .or. i==37023) .and. trace_event_cells_written<20) then
            trace_event_cells_written=trace_event_cells_written+1
            write(996,*) 'case',',',i,',',tnow,',',dt,',',tfail(i),',',gindx(i),',',fdepth(i),',',fhpredi1(i),',',fh(i),',',cv(i),',',trace_cvbar(i),',',cvlimit(i),',',frhopredi1(i),',',trace_gammadeb(i),',',manning(i),',',trace_manningbar(i),',',trace_miudebris(i),',',trace_coemiu(i),',',trace_coemanning(i),',',trace_sfy(i),',',trace_sfmiu(i),',',trace_sfmanning(i),',',trace_absubar(i),',',trace_vorth(i),',',trace_vcomp(i),',',trace_tao(i),',',trace_taoc(i),',',trace_tao(i)-trace_taoc(i),',',kero(zo(i)),',',erorate(i),',',deporate(i),',',ele(i),',',tempele(i),',',eleori(i),',',max(eleori(i)-ele(i),0.d0),',',zo(i),',',gindx(i),',',max(eleori(i)-ele(i),0.d0)>=0.001d0
        end if
    end do
    close(996)
    open(997,file='original_first_event_tau_components_meta.json',status='replace')
    write(997,'(A)') '{'
    write(997,'(A)') '  "provider": "instrumented_original_first_event_tau_components",'
    write(997,'(A)') '  "dump_point": "first accepted step with erorate > 0",'
    write(997,'(A)') '  "tracked_cells": [36761, 36762, 36763, 37023],'
    write(997,'(A)') '  "debug_stop_after_first_event": true,'
    write(997,'(A)') '  "not_fresh_output_reproduction": true,'
    write(997,'(A,I0,A)') '  "event_positive_erorate_count": ', trace_erorate_pos, ','
    write(997,'(A,ES24.16,A)') '  "event_erorate_sum": ', trace_sum_erorate, ','
    write(997,'(A,ES24.16,A)') '  "event_erorate_max": ', trace_max_erorate, ','
    write(997,'(A,ES24.16,A)') '  "event_eleori_minus_ele_sum": ', trace_eleori_minus_ele_sum, ','
    write(997,'(A,ES24.16)') '  "event_eleori_minus_ele_max": ', trace_eleori_minus_ele_max
    write(997,'(A)') '}'
    close(997)
    stop 0
end if
fhpredi(:)=fhpredi1(:)+(erorate(:)+deporate(:))*dt+tempfsh(:)
"@
    $text = $text.Replace(
        "fhpredi(:)=fhpredi1(:)+(erorate(:)+deporate(:))*dt+tempfsh(:)",
        $eventDump
    )

    Set-Content -Path $dfs -Value $text -Encoding UTF8
    Write-Log "Applied original first-event tau component instrumentation."
}

function Apply-OriginalTarget36762ErosionComponentInstrumentation {
    param([string]$ProjectDir)
    $main = Join-Path $ProjectDir "edda main program.F90"
    $dfs = Join-Path $ProjectDir "dfs.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dfs)) { throw "Missing dfs.F90 in $ProjectDir" }

    Apply-MainProgressInstrumentation -ProjectDir $ProjectDir

    $mainText = Get-Content $main -Raw
    if ($mainText -notmatch "before_dfs") {
        $mainText = $mainText.Replace(
            "if (debrissimul) then`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)",
            "if (debrissimul) then`r`ncall dump_instrumented_progress('before_dfs')`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)`r`ncall dump_instrumented_progress('after_dfs')"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $text = Get-Content $dfs -Raw
    if ($text -match "original_target_36762_erosion_components") {
        Write-Log "Original target 36762 erosion component instrumentation already present."
        return
    }
    $text = [regex]::Replace(
        $text,
        '(?m)^voltonode\s*=\s*0\.\s*$',
        "if (allocated(voltonode)) voltonode=0.`r`ncall dump_instrumented_progress('dfs_after_stormdrain_module_zero_guard')"
    )
    $text = $text.Replace(
        "integer:: u(28),ncc,nccs,eroindx(imx1),tempgindx(imx1)",
        "integer:: u(28),ncc,nccs,eroindx(imx1),tempgindx(imx1)`r`ninteger:: trace_cv_lt_cvlimit,trace_fhpredi1_gt_005,trace_tau_gt_taoc,trace_all_erosion_gate,trace_event_cells_written`r`ninteger:: trace_rholimit_clamp(imx1),trace_erodible_clamp(imx1)"
    )
    $text = $text.Replace(
        "double precision:: finalnvol,finalcvol,retaindeposit,soliddepth",
        "double precision:: finalnvol,finalcvol,retaindeposit,soliddepth`r`ndouble precision:: trace_sum_erorate,trace_max_erorate,trace_eleori_minus_ele_sum,trace_eleori_minus_ele_max`r`ndouble precision:: trace_tao(imx1),trace_taoc(imx1),trace_sfy(imx1),trace_sfmiu(imx1),trace_sfmanning(imx1),trace_absubar(imx1),trace_gammadeb(imx1)`r`ndouble precision:: trace_manningbar(imx1),trace_miudebris(imx1),trace_coemiu(imx1),trace_coemanning(imx1),trace_cvbar(imx1),trace_vorth(imx1),trace_vcomp(imx1)"
    )
    $text = $text.Replace(
        "cv=0.`r`ngrav=9.81",
        "call dump_instrumented_progress('dfs_entry')`r`ncv=0.`r`ngrav=9.81`r`ntrace_tao=0.d0; trace_taoc=0.d0; trace_sfy=0.d0; trace_sfmiu=0.d0; trace_sfmanning=0.d0; trace_absubar=0.d0; trace_gammadeb=0.d0`r`ntrace_manningbar=0.d0; trace_miudebris=0.d0; trace_coemiu=0.d0; trace_coemanning=0.d0; trace_cvbar=0.d0; trace_vorth=0.d0; trace_vcomp=0.d0`r`ntrace_rholimit_clamp=0; trace_erodible_clamp=0"
    )
    $text = $text.Replace(
        "! main loop`r`ndo 1000, nt=1,maxnts",
        "call dump_instrumented_progress('dfs_before_main_loop')`r`n! main loop`r`ndo 1000, nt=1,maxnts"
    )
    $text = $text.Replace(
        "erorate=0.`r`ndeporate=0.",
        "erorate=0.`r`ndeporate=0.`r`ntrace_cv_lt_cvlimit=0; trace_fhpredi1_gt_005=0; trace_tau_gt_taoc=0; trace_all_erosion_gate=0`r`ntrace_sum_erorate=0.d0; trace_max_erorate=0.d0; trace_eleori_minus_ele_sum=0.d0; trace_eleori_minus_ele_max=0.d0`r`ntrace_rholimit_clamp=0; trace_erodible_clamp=0"
    )
    $text = $text.Replace(
        "    absubar(i)=max(vorth,vcomp)",
        "    absubar(i)=max(vorth,vcomp)`r`n    trace_vorth(i)=vorth`r`n    trace_vcomp(i)=vcomp"
    )
    $text = $text.Replace(
        "        taoc=ctao(zo(i))+(1-cs)*cv(i)*(rhos-rhow)*grav*fh(i)*cos(slo(i))**2.*tan(phit(zo(i)))`r`n        if (fhpredi1(i)>0.05 .and. tao>taoc) then",
        "        taoc=ctao(zo(i))+(1-cs)*cv(i)*(rhos-rhow)*grav*fh(i)*cos(slo(i))**2.*tan(phit(zo(i)))`r`n        trace_tao(i)=tao`r`n        trace_taoc(i)=taoc`r`n        trace_sfy(i)=sfy`r`n        trace_sfmiu(i)=sfmiu`r`n        trace_sfmanning(i)=sfmanning`r`n        trace_absubar(i)=absubar(i)`r`n        trace_gammadeb(i)=gammadeb`r`n        trace_manningbar(i)=manningbar`r`n        trace_miudebris(i)=miudebris`r`n        trace_coemiu(i)=coemiu`r`n        trace_coemanning(i)=coemanning`r`n        trace_cvbar(i)=cvbar`r`n        if (cv(i)<cvlimit(i)) trace_cv_lt_cvlimit=trace_cv_lt_cvlimit+1`r`n        if (fhpredi1(i)>0.05d0) trace_fhpredi1_gt_005=trace_fhpredi1_gt_005+1`r`n        if (tao>taoc) trace_tau_gt_taoc=trace_tau_gt_taoc+1`r`n        if (cv(i)<cvlimit(i) .and. fhpredi1(i)>0.05d0 .and. tao>taoc) trace_all_erosion_gate=trace_all_erosion_gate+1`r`n        if (fhpredi1(i)>0.05 .and. tao>taoc) then"
    )
    $text = $text.Replace(
        "    erorate(i)=(rholimit(i)-frhopredi1(i))*fhpredi1(i)/(rhoero-rholimit(i))/dt`r`n    end if",
        "    trace_rholimit_clamp(i)=1`r`n    erorate(i)=(rholimit(i)-frhopredi1(i))*fhpredi1(i)/(rhoero-rholimit(i))/dt`r`n    end if"
    )
    $text = $text.Replace(
        "    erorate(i)=(inierodithick(i))/dt`r`n    tempinierodithick(i)=0.`r`n    end if",
        "    trace_erodible_clamp(i)=1`r`n    erorate(i)=(inierodithick(i))/dt`r`n    tempinierodithick(i)=0.`r`n    end if"
    )
    $eventDump = @"
trace_sum_erorate=sum(erorate)
trace_max_erorate=maxval(erorate)
trace_eleori_minus_ele_sum=sum(max(eleori-ele,0.d0))
trace_eleori_minus_ele_max=maxval(max(eleori-ele,0.d0))
open(995,file='original_target_36762_erosion_components_progress.txt',status='unknown',position='append')
write(995,*) nt,tnow,tnext,dt,trace_cv_lt_cvlimit,trace_fhpredi1_gt_005,trace_tau_gt_taoc,trace_all_erosion_gate,trace_sum_erorate,trace_max_erorate,trace_eleori_minus_ele_sum,trace_eleori_minus_ele_max
close(995)
if (tnow>=220.2539d0 .and. tnow<=220.2541d0 .and. dt<=0.2161000001d0) then
    open(996,file='original_target_36762_erosion_components.csv',status='replace')
    write(996,'(A)') 'case_id,nt,cell_id,tnow,tnext,dt,tfail,gindx,fdepth,fhpredi1,fh,cv,cvbar,cvlimit,frhopredi1,gammadeb,manning,manningbar,miudebris,coemiu,coemanning,sfy,sfmiu,sfmanning,absubar,vorth,vcomp,tau,taoc,tau_minus_taoc,kero,erorate_raw,erorate_clamped,deporate,tempfsh,tempfsrho,ele,tempele,eleori,eleori_minus_ele,zone_id,output_mask_gindx,rholimit_clamp,erodible_clamp,threshold_pass'
    trace_event_cells_written=0
    do i=1,imx1
        if ((i==36761 .or. i==36762 .or. i==36763 .or. i==37023) .and. trace_event_cells_written<20) then
            trace_event_cells_written=trace_event_cells_written+1
            write(996,*) 'case',',',nt,',',i,',',tnow,',',tnext,',',dt,',',tfail(i),',',gindx(i),',',fdepth(i),',',fhpredi1(i),',',fh(i),',',cv(i),',',trace_cvbar(i),',',cvlimit(i),',',frhopredi1(i),',',trace_gammadeb(i),',',manning(i),',',trace_manningbar(i),',',trace_miudebris(i),',',trace_coemiu(i),',',trace_coemanning(i),',',trace_sfy(i),',',trace_sfmiu(i),',',trace_sfmanning(i),',',trace_absubar(i),',',trace_vorth(i),',',trace_vcomp(i),',',trace_tao(i),',',trace_taoc(i),',',trace_tao(i)-trace_taoc(i),',',kero(zo(i)),',',erorate(i),',',erorate(i),',',deporate(i),',',tempfsh(i),',',tempfsrho(i),',',ele(i),',',tempele(i),',',eleori(i),',',max(eleori(i)-ele(i),0.d0),',',zo(i),',',gindx(i),',',trace_rholimit_clamp(i),',',trace_erodible_clamp(i),',',max(eleori(i)-ele(i),0.d0)>=0.001d0
        end if
    end do
    close(996)
    open(997,file='original_target_36762_erosion_components_meta.json',status='replace')
    write(997,'(A)') '{'
    write(997,'(A)') '  "provider": "instrumented_original_target_36762_erosion_components",'
    write(997,'(A)') '  "dump_point": "target restored run source-rate components before source merge",'
    write(997,'(A)') '  "tracked_cells": [36761, 36762, 36763, 37023],'
    write(997,'(A)') '  "target_tnow": 220.254,'
    write(997,'(A)') '  "target_dt_upper_bound": 0.2161000001,'
    write(997,'(A)') '  "debug_stop_after_target": true,'
    write(997,'(A,I0,A)') '  "nt": ', nt, ','
    write(997,'(A,ES24.16,A)') '  "tnow": ', tnow, ','
    write(997,'(A,ES24.16,A)') '  "dt": ', dt, ','
    write(997,'(A,ES24.16,A)') '  "event_erorate_sum": ', trace_sum_erorate, ','
    write(997,'(A,ES24.16)') '  "event_erorate_max": ', trace_max_erorate
    write(997,'(A)') '}'
    close(997)
    stop 0
end if
fhpredi(:)=fhpredi1(:)+(erorate(:)+deporate(:))*dt+tempfsh(:)
"@
    $text = $text.Replace(
        "fhpredi(:)=fhpredi1(:)+(erorate(:)+deporate(:))*dt+tempfsh(:)",
        $eventDump
    )

    Set-Content -Path $dfs -Value $text -Encoding UTF8
    Write-Log "Applied original target 36762 erosion component instrumentation."
}

function Apply-OriginalTarget35716ErosionComponentInstrumentation {
    param([string]$ProjectDir)
    $dfs = Join-Path $ProjectDir "dfs.F90"
    if (-not (Test-Path $dfs)) { throw "Missing dfs.F90 in $ProjectDir" }
    $patchLeaf = Split-Path $PatchPath -Leaf
    $targetWindowPredicate = "tnow>=230.0d0 .and. tnow<=310.5d0"
    $targetWindowStopPredicate = "tnow>310.5d0"
    $targetWindowLabel = "230.0_to_310.5"
    if ($patchLeaf -match "380_395") {
        $targetWindowPredicate = "tnow>=380.0d0 .and. tnow<=395.0d0"
        $targetWindowStopPredicate = "tnow>395.0d0"
        $targetWindowLabel = "380.0_to_395.0"
    }
    if ($patchLeaf -match "540_545") {
        $targetWindowPredicate = "tnow>=540.0d0 .and. tnow<=545.0d0"
        $targetWindowStopPredicate = "tnow>545.0d0"
        $targetWindowLabel = "540.0_to_545.0"
    }
    if ($patchLeaf -match "580_600") {
        $targetWindowPredicate = "tnow>=580.0d0 .and. tnow<=600.5d0"
        $targetWindowStopPredicate = "tnow>600.5d0"
        $targetWindowLabel = "580.0_to_600.5"
    }

    Apply-OriginalTarget36762ErosionComponentInstrumentation -ProjectDir $ProjectDir

    $text = Get-Content $dfs -Raw
    $text = $text.Replace("original_target_36762_erosion_components", "original_target_35716_erosion_components")
    $text = $text.Replace("instrumented_original_target_36762_erosion_components", "instrumented_original_target_35716_erosion_components")
    $text = $text.Replace(
        "integer:: trace_cv_lt_cvlimit,trace_fhpredi1_gt_005,trace_tau_gt_taoc,trace_all_erosion_gate,trace_event_cells_written",
        "integer:: trace_cv_lt_cvlimit,trace_fhpredi1_gt_005,trace_tau_gt_taoc,trace_all_erosion_gate,trace_event_cells_written,trace_35716_header_written"
    )
    $text = $text.Replace(
        "trace_rholimit_clamp=0; trace_erodible_clamp=0",
        "trace_rholimit_clamp=0; trace_erodible_clamp=0`r`ntrace_35716_header_written=0"
    )
    $text = $text.Replace(
        "tnow>=220.2539d0 .and. tnow<=220.2541d0 .and. dt<=0.2161000001d0",
        $targetWindowPredicate
    )
    $text = $text.Replace(
        "open(996,file='original_target_35716_erosion_components.csv',status='replace')",
        "open(996,file='original_target_35716_erosion_components.csv',status='unknown',position='append')"
    )
    $text = $text.Replace(
        "    write(996,'(A)') 'case_id,nt,cell_id,tnow,tnext,dt,tfail,gindx,fdepth,fhpredi1,fh,cv,cvbar,cvlimit,frhopredi1,gammadeb,manning,manningbar,miudebris,coemiu,coemanning,sfy,sfmiu,sfmanning,absubar,vorth,vcomp,tau,taoc,tau_minus_taoc,kero,erorate_raw,erorate_clamped,deporate,tempfsh,tempfsrho,ele,tempele,eleori,eleori_minus_ele,zone_id,output_mask_gindx,rholimit_clamp,erodible_clamp,threshold_pass'",
        "    if (trace_35716_header_written==0) then`r`n        write(996,'(A)') 'case_id,nt,cell_id,tnow,tnext,dt,tfail,gindx,fdepth,fhpredi1,fh,cv,cvbar,cvlimit,frhopredi1,gammadeb,manning,manningbar,miudebris,coemiu,coemanning,sfy,sfmiu,sfmanning,absubar,vorth,vcomp,tau,taoc,tau_minus_taoc,kero,erorate_raw,erorate_clamped,deporate,tempfsh,tempfsrho,ele,tempele,eleori,eleori_minus_ele,zone_id,output_mask_gindx,rholimit_clamp,erodible_clamp,threshold_pass'`r`n        trace_35716_header_written=1`r`n    end if"
    )
    $text = $text.Replace(
        "i==36761 .or. i==36762 .or. i==36763 .or. i==37023",
        "i==35716 .or. i==29392 .or. i==29163 .or. i==29621 .or. i==29622"
    )
    $text = $text.Replace(
        '"tracked_cells": [36761, 36762, 36763, 37023]',
        '"tracked_cells": [35716, 29392, 29163, 29621, 29622]'
    )
    $text = $text.Replace('"target_tnow": 220.254', ('"target_tnow_window": "' + $targetWindowLabel + '"'))
    $text = $text.Replace('"target_dt_upper_bound": 0.2161000001,', '"target_dt_upper_bound": null,')
    $text = $text.Replace(
        "trace_sum_erorate=0.d0; trace_max_erorate=0.d0; trace_eleori_minus_ele_sum=0.d0; trace_eleori_minus_ele_max=0.d0`r`ntrace_rholimit_clamp=0; trace_erodible_clamp=0`r`ntrace_35716_header_written=0",
        "trace_sum_erorate=0.d0; trace_max_erorate=0.d0; trace_eleori_minus_ele_sum=0.d0; trace_eleori_minus_ele_max=0.d0`r`ntrace_rholimit_clamp=0; trace_erodible_clamp=0"
    )
    $text = $text.Replace("    stop 0", "")
    $text = $text.Replace(
        "fhpredi(:)=fhpredi1(:)+(erorate(:)+deporate(:))*dt+tempfsh(:)",
        ("if (" + $targetWindowStopPredicate + ") then`r`n    stop 0`r`nend if`r`nfhpredi(:)=fhpredi1(:)+(erorate(:)+deporate(:))*dt+tempfsh(:)")
    )
    Set-Content -Path $dfs -Value $text -Encoding UTF8
    Write-Log "Applied original target 35716 erosion component instrumentation."
}

function Add-BoundaryProbeSourceToProject {
    param([string]$ProjectDir)
    $vfproj = Join-Path $ProjectDir "EDDA.vfproj"
    $vfText = Get-Content $vfproj -Raw
    if ($vfText -notmatch "dfs_boundary_probe\.F90") {
        $vfText = $vfText.Replace(
            '<File RelativePath=".\dfs.F90"/>',
            '<File RelativePath=".\dfs.F90"/>' + "`r`n`t`t" + '<File RelativePath=".\dfs_boundary_probe.F90"/>'
        )
        Set-Content -Path $vfproj -Value $vfText -Encoding UTF8
    }
}

function Apply-DfsCallBoundaryProbeInstrumentation {
    param([string]$ProjectDir)
    $main = Join-Path $ProjectDir "edda main program.F90"
    $dfs = Join-Path $ProjectDir "dfs.F90"
    $stub = Join-Path $ProjectDir "dfs_boundary_probe.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dfs)) { throw "Missing dfs.F90 in $ProjectDir" }

    Apply-MainProgressInstrumentation -ProjectDir $ProjectDir

    $mainText = Get-Content $main -Raw
    if ($BuildVariantSafe -eq "dfs_noop_stub") {
        $mainText = $mainText.Replace(
            "if (debrissimul) then`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)",
            "if (debrissimul) then`r`ncall dump_instrumented_progress('before_dfs')`r`ncall dfs_noop_stub(imx1,nrow,ncol,header,u,maxdirection)`r`ncall dump_instrumented_progress('after_dfs')"
        )
        @"
subroutine dfs_noop_stub(imx1,nrow,ncol,header,u,maxdirection)
    implicit none
    integer, intent(in) :: imx1,nrow,ncol,maxdirection
    integer, intent(in) :: u(28)
    character(len=14), intent(in) :: header(6)

    open(990,file='instrumented_progress.log',status='unknown',position='append')
    write(990,'(A)') 'dfs_noop_stub_entered'
    close(990)

    open(989,file='dfs_noop_stub_args.txt',status='replace')
    write(989,'(A,I0)') 'imx1=', imx1
    write(989,'(A,I0)') 'nrow=', nrow
    write(989,'(A,I0)') 'ncol=', ncol
    write(989,'(A,I0)') 'maxdirection=', maxdirection
    write(989,'(A,I0)') 'u_count=', size(u)
    write(989,'(A,A)') 'header_1=', trim(header(1))
    close(989)
    return
end subroutine dfs_noop_stub
"@ | Set-Content -Path $stub -Encoding ASCII
        Add-BoundaryProbeSourceToProject -ProjectDir $ProjectDir
        Set-Content -Path $main -Value $mainText -Encoding UTF8
        Write-Log "Applied DFS noop stub call-boundary probe."
        return
    }

    if ($mainText -notmatch "before_dfs") {
        $mainText = $mainText.Replace(
            "if (debrissimul) then`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)",
            "if (debrissimul) then`r`ncall dump_instrumented_progress('before_dfs')`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)`r`ncall dump_instrumented_progress('after_dfs')"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $text = Get-Content $dfs -Raw
    if ($text -match "dfs_entry_entered") {
        Write-Log "DFS call-boundary probe already present."
        return
    }
    if ($BuildVariantSafe -eq "dfs_prologue_minimal") {
        $text = $text.Replace(
            "cv=0.`r`ngrav=9.81",
            "call dump_instrumented_progress('dfs_entry_entered')`r`ncall dump_instrumented_progress('dfs_prologue_minimal_return')`r`nreturn`r`ncv=0.`r`ngrav=9.81"
        )
    } else {
        $text = $text.Replace(
            "cv=0.`r`ngrav=9.81",
            "call dump_instrumented_progress('dfs_entry_entered')`r`ncv=0.`r`ngrav=9.81`r`ncall dump_instrumented_progress('dfs_after_scalar_init')"
        )
        $text = $text.Replace(
            "! main loop`r`ndo 1000, nt=1,maxnts",
            "call dump_instrumented_progress('dfs_before_timestep_loop')`r`n! main loop`r`ndo 1000, nt=1,maxnts"
        )
    }
    Set-Content -Path $dfs -Value $text -Encoding UTF8
    Write-Log "Applied DFS call-boundary progress instrumentation for variant $BuildVariantSafe."
}

function Apply-DfsPrologueStorageProbeInstrumentation {
    param([string]$ProjectDir)
    $main = Join-Path $ProjectDir "edda main program.F90"
    $dfs = Join-Path $ProjectDir "dfs.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dfs)) { throw "Missing dfs.F90 in $ProjectDir" }

    Apply-MainProgressInstrumentation -ProjectDir $ProjectDir

    $mainText = Get-Content $main -Raw
    if ($mainText -notmatch "before_dfs") {
        $mainText = $mainText.Replace(
            "if (debrissimul) then`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)",
            "if (debrissimul) then`r`ncall dump_instrumented_progress('before_dfs')`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)`r`ncall dump_instrumented_progress('after_dfs')"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $text = Get-Content $dfs -Raw
    if ($text -notmatch "dfs_entry_marker_reached") {
        $text = [regex]::Replace(
            $text,
            '(?m)^inflowvol\s*=\s*0\.\s*$',
            "call dump_instrumented_progress('dfs_entry_marker_reached')`r`ninflowvol = 0."
        )
    }
    if ($text -notmatch "dfs_before_stormdrain_module_zero") {
        $text = [regex]::Replace(
            $text,
            '(?m)^voltonode\s*=\s*0\.\s*$',
            "call dump_instrumented_progress('dfs_before_stormdrain_module_zero')`r`nvoltonode=0."
        )
    }

    if ($BuildVariantSafe -in @("dfs_prologue_guard_non_arrays", "dfs_prologue_allocatable_non_arrays", "dfs_prologue_first_event_early_stop", "original_deposition_first_event_early_stop", "first_nonzero_deporate", "first_tempdebdepothick_positive", "first_deposit_writer_positive", "target_sparse_checkpoint", "target_600s_tracked", "restore_extended_upstream_pre222_history")) {
        $text = [regex]::Replace(
            $text,
            '(?m)^voltonode\s*=\s*0\.\s*$',
            "if (allocated(voltonode)) voltonode=0."
        )
        if ($text -notmatch "dfs_after_stormdrain_module_zero_guard") {
            $text = $text.Replace(
                "if (allocated(voltonode)) voltonode=0.",
                "if (allocated(voltonode)) voltonode=0.`r`ncall dump_instrumented_progress('dfs_after_stormdrain_module_zero_guard')"
            )
        }
    }

    if ($BuildVariantSafe -eq "dfs_prologue_allocatable_non_arrays") {
        $text = $text.Replace(
            "double precision:: totalvoltonode(non), totalvolfromnode(non)",
            "double precision, allocatable:: totalvoltonode(:), totalvolfromnode(:)"
        )
        $text = $text.Replace(
            "totalvoltonode = 0.`r`ntotalvolfromnode = 0.",
            "call dump_instrumented_progress('dfs_before_non_local_allocate')`r`nif (non > 0) then`r`n    allocate(totalvoltonode(non), totalvolfromnode(non))`r`nelse`r`n    allocate(totalvoltonode(0), totalvolfromnode(0))`r`nend if`r`ncall dump_instrumented_progress('dfs_after_non_local_allocate')`r`ntotalvoltonode = 0.`r`ntotalvolfromnode = 0."
        )
    }

    if ($BuildVariantSafe -eq "dfs_prologue_first_event_early_stop") {
        if ($text -notmatch "original_erosion_event_probe_progress") {
            Write-Log "Applying original event probe after DFS storage guard."
            Set-Content -Path $dfs -Value $text -Encoding UTF8
            Apply-OriginalErosionEventProbeInstrumentation -ProjectDir $ProjectDir
            $text = Get-Content $dfs -Raw
        }
    }

    Set-Content -Path $dfs -Value $text -Encoding UTF8
    Write-Log "Applied DFS prologue storage probe instrumentation for variant $BuildVariantSafe."
}

function Apply-OriginalTrackedScalarMomentumProbeInstrumentation {
    param([string]$ProjectDir)
    Apply-MainProgressInstrumentation -ProjectDir $ProjectDir

    $main = Join-Path $ProjectDir "edda main program.F90"
    $dump = Join-Path $ProjectDir "tfail_dump.F90"
    $dfs = Join-Path $ProjectDir "dfs.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dump)) { throw "Missing tfail_dump.F90 in $ProjectDir" }
    if (-not (Test-Path $dfs)) { throw "Missing dfs.F90 in $ProjectDir" }

    $unsfin = Join-Path $ProjectDir "unsfin.F90"
    if (Test-Path $unsfin) {
        $unsfinText = Get-Content $unsfin -Raw
        $unsfinText = $unsfinText.Replace(
            "    write (*,*) 'starting computing', i, 'cell'",
            "    ! tracked scalar probe: suppress per-cell stdout to keep original run bounded"
        )
        $unsfinText = $unsfinText.Replace(
            "    if (mod(i-1,2000)==0) write (*,*) i-1 ! cells completed",
            "    ! tracked scalar probe: suppress per-2000-cell stdout"
        )
        Set-Content -Path $unsfin -Value $unsfinText -Encoding UTF8
    }

    $text = Get-Content $dfs -Raw
    if ($text -match "original_tracked_scalar_momentum_terms_raw") {
        Write-Log "Original tracked-scalar momentum probe already present."
        return
    }
    $includeSkipPredicateProbe = ((Split-Path $PatchPath -Leaf) -match "assignment_skip_predicate")
    $includeDepthComponentLedger = ((Split-Path $PatchPath -Leaf) -match "depth_component_ledger")
    $includeAllDirectionAssignmentProbe = ((Split-Path $PatchPath -Leaf) -match "all_direction")
    if ($includeAllDirectionAssignmentProbe) {
        $targetAssignmentPredicate = "i==35978 .and. tnow>=226.5d0 .and. tnow<=228.5d0"
        if ((Split-Path $PatchPath -Leaf) -match "extended_upstream_history") {
            $targetAssignmentPredicate = "(i==35978 .or. i==36238 .or. i==36239) .and. tnow>=226.5d0 .and. tnow<=228.5d0"
        }
        if ($includeDepthComponentLedger) {
            $targetStopPredicate = "i==36238 .and. ii>=6 .and. tnow>=228.09d0"
        } else {
            $targetStopPredicate = "i==35978 .and. ii>=6 .and. tnow>=228.09d0"
        }
    } else {
        $targetAssignmentPredicate = "i==35978 .and. ii==6 .and. tnow>=226.5d0 .and. tnow<=228.5d0"
        $targetStopPredicate = "i==35978 .and. tnow>=228.09d0"
    }

    $text = $text.Replace(
        "double precision:: artivis",
        "double precision:: artivis`r`ndouble precision:: tracked_fvpredi_before_clamp,tracked_fvpredi_after_clamp,tracked_ybar_fvlimit,tracked_hbar,tracked_frhobar,tracked_cvbar,tracked_miubar,tracked_hi,tracked_hn`r`ndouble precision:: tracked_fv_nq_same_direction,tracked_fv_i_opposite_direction`r`ninteger:: tracked_clamp_status,tracked_sign_flip_status"
    )

    $headerBlock = @"
open(991,file='original_tracked_scalar_momentum_terms_raw.txt',status='replace')
write(991,'(A)') 'record_scope tnow tnext dt i ii nq opposite_direction fhpredi1_i frhopredi1_i cv_i gammadeb_probe manningbar miudebris grad sfy sfmiu sfmanning localvdiff artivis dv fv_before fvpredi_before_clamp fvpredi_after_clamp fvlimit clamp_status sign_flip_status qq qqmass frhoflux ybar_fvlimit hbar hi hn vcomp vorth absubar fvdepo threshold_2_3_fvdepo deposition_gate deporate mirrored_fvpredi_i2 source_fv_i6 source_fvpredi_i6 source_fvpredi2_i6 receiver_cell operand_fv_neighbor_same_direction operand_fv_source_opposite_direction'
close(991)

! main loop
do 1000, nt=1,maxnts
"@
    if ($includeSkipPredicateProbe) {
        $skipHeaderBlock = @"
open(992,file='original_assignment_skip_predicate_raw.txt',status='replace')
write(992,'(A)') 'record_scope tnow tnext dt i ii nq skip_code skip_reason qq_before nq_zero nq_lt_i both_dry ybar_zero fhpredi_i fhpredi_nq tol hbar ybar hi hn arf_i arf_nq source_fv_i6 source_fvpredi_i6 source_fvpredi2_i6'
close(992)
"@
        $headerBlock = $skipHeaderBlock + "`r`n" + $headerBlock
    }
    if ($includeDepthComponentLedger) {
        $depthHeaderBlock = @"
open(993,file='original_depth_component_ledger_raw.txt',status='replace')
write(993,'(A)') 'record_scope tnow tnext dt nt i cell_role fh fhpredi1 fhpredi erorate deporate tempfsh tempri ir tempinflowh frho frhopredi1 frhopredi cv rhodepo tempfsrho tempele ele outflow arf qnet hinflow fhpredi2 frhopredi2 qq_sum qqmass_sum qq_d6 qqmass_d6 fv_d6 fvpredi_d6 fvpredi2_d6'
close(993)
open(994,file='original_depth_face_qq_ledger_raw.txt',status='replace')
write(994,'(A)') 'record_scope tnow tnext dt nt i qnet hinflow fhpredi fhpredi2 qq_sum qq1 qq2 qq3 qq4 qq5 qq6 qq7 qq8 qqmass_sum qqmass1 qqmass2 qqmass3 qqmass4 qqmass5 qqmass6 qqmass7 qqmass8 fp1 fp2 fp3 fp4 fp5 fp6 fp7 fp8'
close(994)
"@
        $headerBlock = $depthHeaderBlock + "`r`n" + $headerBlock
    }
    $text = $text.Replace("! main loop`r`ndo 1000, nt=1,maxnts", $headerBlock)

    if ($includeDepthComponentLedger) {
        $depthSurfaceBlock = @"
where (outflow==.true.) frhopredi1=rhow

if (tnow>=226.5d0 .and. tnow<=228.5d0) then
    do i=1,imx1
        if (i==35978 .or. i==36238 .or. i==36239) then
            open(993,file='original_depth_component_ledger_raw.txt',status='unknown',position='append')
            if (i==35978) then
                write(993,*) 'after_surface_forcing',tnow,tnext,dt,nt,i,'source',fh(i),fhpredi1(i),0.d0,erorate(i),deporate(i),tempfsh(i),tempri(i),ir(i),tempinflowh(i),frho(i),frhopredi1(i),0.d0,0.d0,rhodepo(i),tempfsrho(i),0.d0,ele(i),outflow(i),arf(i),0.d0,0.d0,0.d0,0.d0,0.d0,0.d0,qq(i,6),qqmass(i,6),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
            else
                write(993,*) 'after_surface_forcing',tnow,tnext,dt,nt,i,'contributor',fh(i),fhpredi1(i),0.d0,erorate(i),deporate(i),tempfsh(i),tempri(i),ir(i),tempinflowh(i),frho(i),frhopredi1(i),0.d0,0.d0,rhodepo(i),tempfsrho(i),0.d0,ele(i),outflow(i),arf(i),0.d0,0.d0,0.d0,0.d0,0.d0,0.d0,qq(i,6),qqmass(i,6),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
            end if
            close(993)
        end if
    end do
end if
"@
        $text = $text.Replace(
            "where (outflow==.true.) frhopredi1=rhow",
            $depthSurfaceBlock
        )

        $depthPostSourceNeedle = @"
where (fhpredi<=eps) frhopredi=rhow

! out flow
where (outflow==.true.) fhpredi=0.
where (outflow==.true.) frhopredi=rhow
"@
        $depthPostSourceBlock = @"
where (fhpredi<=eps) frhopredi=rhow

! out flow
where (outflow==.true.) fhpredi=0.
where (outflow==.true.) frhopredi=rhow

if (tnow>=226.5d0 .and. tnow<=228.5d0) then
    do i=1,imx1
        if (i==35978 .or. i==36238 .or. i==36239) then
            open(993,file='original_depth_component_ledger_raw.txt',status='unknown',position='append')
            if (i==35978) then
                write(993,*) 'after_source_merge_before_face_loop',tnow,tnext,dt,nt,i,'source',fh(i),fhpredi1(i),fhpredi(i),erorate(i),deporate(i),tempfsh(i),tempri(i),ir(i),tempinflowh(i),frho(i),frhopredi1(i),frhopredi(i),cv(i),rhodepo(i),tempfsrho(i),tempele(i),ele(i),outflow(i),arf(i),0.d0,0.d0,0.d0,0.d0,0.d0,0.d0,qq(i,6),qqmass(i,6),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
            else
                write(993,*) 'after_source_merge_before_face_loop',tnow,tnext,dt,nt,i,'contributor',fh(i),fhpredi1(i),fhpredi(i),erorate(i),deporate(i),tempfsh(i),tempri(i),ir(i),tempinflowh(i),frho(i),frhopredi1(i),frhopredi(i),cv(i),rhodepo(i),tempfsrho(i),tempele(i),ele(i),outflow(i),arf(i),0.d0,0.d0,0.d0,0.d0,0.d0,0.d0,qq(i,6),qqmass(i,6),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
            end if
            close(993)
        end if
    end do
end if
"@
        $text = $text.Replace($depthPostSourceNeedle, $depthPostSourceBlock)

        $depthQnetNeedle = @"
    fhpredi2(i)=fhpredi(i)+hinflow
    frhopredi2(i)=(frhopredi(i)*fhpredi(i)*cellareacal(i)+qmassnet)/fhpredi2(i)/cellareacal(i)
"@
        $depthQnetBlock = @"
    fhpredi2(i)=fhpredi(i)+hinflow
    frhopredi2(i)=(frhopredi(i)*fhpredi(i)*cellareacal(i)+qmassnet)/fhpredi2(i)/cellareacal(i)
    if (tnow>=226.5d0 .and. tnow<=228.5d0 .and. (i==35978 .or. i==36238 .or. i==36239)) then
        open(993,file='original_depth_component_ledger_raw.txt',status='unknown',position='append')
        if (i==35978) then
            write(993,*) 'after_qnet_fhpredi2',tnow,tnext,dt,nt,i,'source',fh(i),fhpredi1(i),fhpredi(i),erorate(i),deporate(i),tempfsh(i),tempri(i),ir(i),tempinflowh(i),frho(i),frhopredi1(i),frhopredi(i),cv(i),rhodepo(i),tempfsrho(i),tempele(i),ele(i),outflow(i),arf(i),qnet,hinflow,fhpredi2(i),frhopredi2(i),sum(qq(i,:)),sum(qqmass(i,:)),qq(i,6),qqmass(i,6),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
        else
            write(993,*) 'after_qnet_fhpredi2',tnow,tnext,dt,nt,i,'contributor',fh(i),fhpredi1(i),fhpredi(i),erorate(i),deporate(i),tempfsh(i),tempri(i),ir(i),tempinflowh(i),frho(i),frhopredi1(i),frhopredi(i),cv(i),rhodepo(i),tempfsrho(i),tempele(i),ele(i),outflow(i),arf(i),qnet,hinflow,fhpredi2(i),frhopredi2(i),sum(qq(i,:)),sum(qqmass(i,:)),qq(i,6),qqmass(i,6),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
        end if
        close(993)
        if (i==36238 .or. i==36239) then
            open(994,file='original_depth_face_qq_ledger_raw.txt',status='unknown',position='append')
            write(994,*) 'after_qnet_fhpredi2',tnow,tnext,dt,nt,i,qnet,hinflow,fhpredi(i),fhpredi2(i),sum(qq(i,:)),qq(i,1),qq(i,2),qq(i,3),qq(i,4),qq(i,5),qq(i,6),qq(i,7),qq(i,8),sum(qqmass(i,:)),qqmass(i,1),qqmass(i,2),qqmass(i,3),qqmass(i,4),qqmass(i,5),qqmass(i,6),qqmass(i,7),qqmass(i,8),fp(i,1),fp(i,2),fp(i,3),fp(i,4),fp(i,5),fp(i,6),fp(i,7),fp(i,8)
            close(994)
        end if
    end if
"@
        $text = $text.Replace($depthQnetNeedle, $depthQnetBlock)

        $depthCommitNeedle = "tnow=tnext ! tnow is the present time"
        $depthCommitBlock = @"
if (tnow>=226.5d0 .and. tnow<=228.5d0) then
    do i=1,imx1
        if (i==35978 .or. i==36238 .or. i==36239) then
            open(993,file='original_depth_component_ledger_raw.txt',status='unknown',position='append')
            if (i==35978) then
                write(993,*) 'before_accepted_commit',tnow,tnext,dt,nt,i,'source',fh(i),fhpredi1(i),fhpredi(i),erorate(i),deporate(i),tempfsh(i),tempri(i),ir(i),tempinflowh(i),frho(i),frhopredi1(i),frhopredi(i),cv(i),rhodepo(i),tempfsrho(i),tempele(i),ele(i),outflow(i),arf(i),0.d0,0.d0,fhpredi2(i),frhopredi2(i),sum(qq(i,:)),sum(qqmass(i,:)),qq(i,6),qqmass(i,6),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
            else
                write(993,*) 'before_accepted_commit',tnow,tnext,dt,nt,i,'contributor',fh(i),fhpredi1(i),fhpredi(i),erorate(i),deporate(i),tempfsh(i),tempri(i),ir(i),tempinflowh(i),frho(i),frhopredi1(i),frhopredi(i),cv(i),rhodepo(i),tempfsrho(i),tempele(i),ele(i),outflow(i),arf(i),0.d0,0.d0,fhpredi2(i),frhopredi2(i),sum(qq(i,:)),sum(qqmass(i,:)),qq(i,6),qqmass(i,6),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
            end if
            close(993)
        end if
    end do
end if
tnow=tnext ! tnow is the present time
"@
        $text = $text.Replace($depthCommitNeedle, $depthCommitBlock)

        if ($text -notmatch "after_source_merge_before_face_loop") {
            $text = [regex]::Replace(
                $text,
                'where\s*\(fhpredi<=eps\)\s*frhopredi=rhow\s*! out flow\s*where\s*\(outflow==\.true\.\)\s*fhpredi=0\.\s*where\s*\(outflow==\.true\.\)\s*frhopredi=rhow',
                $depthPostSourceBlock,
                [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
            )
        }
        if ($text -notmatch "after_qnet_fhpredi2") {
            $text = [regex]::Replace(
                $text,
                'fhpredi2\(i\)=fhpredi\(i\)\+hinflow\s*frhopredi2\(i\)=\(frhopredi\(i\)\*fhpredi\(i\)\*cellareacal\(i\)\+qmassnet\)/fhpredi2\(i\)/cellareacal\(i\)',
                $depthQnetBlock,
                [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
            )
        }
        if ($text -notmatch "before_accepted_commit") {
            $text = [regex]::Replace(
                $text,
                '(?m)^tnow=tnext ! tnow is the present time',
                $depthCommitBlock,
                [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
            )
        }
    }

    if ($includeSkipPredicateProbe) {
        $skipEarlyPredicateBlock = @"
        nq=fp(i,ii)
        dt0=0.
        if (($targetAssignmentPredicate) .and. nq==0) then
            open(992,file='original_assignment_skip_predicate_raw.txt',status='unknown',position='append')
            write(992,*) 'skip_nq_zero',tnow,tnext,dt,i,ii,nq,1,'nq_zero',0.d0,1,0,0,0,fhpredi(i),0.d0,tol,0.d0,0.d0,0.d0,0.d0,arf(i),0.d0,fv(i,6),fvpredi(i,6),fvpredi2(i,6)
            close(992)
        end if
        if (nq==0) cycle
        if (($targetAssignmentPredicate) .and. qq(i,ii)/=0.) then
            open(992,file='original_assignment_skip_predicate_raw.txt',status='unknown',position='append')
            write(992,*) 'skip_qq_nonzero',tnow,tnext,dt,i,ii,nq,2,'qq_nonzero',qq(i,ii),0,0,0,0,fhpredi(i),fhpredi(nq),tol,0.d0,0.d0,fhpredi(i)+tempele(i),fhpredi(nq)+tempele(nq),arf(i),arf(nq),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
            close(992)
        end if
        if (qq(i,ii)/=0.) cycle
        if (($targetAssignmentPredicate) .and. nq<i) then
            open(992,file='original_assignment_skip_predicate_raw.txt',status='unknown',position='append')
            write(992,*) 'skip_nq_lt_i',tnow,tnext,dt,i,ii,nq,3,'nq_lt_i',qq(i,ii),0,1,0,0,fhpredi(i),fhpredi(nq),tol,0.d0,0.d0,fhpredi(i)+tempele(i),fhpredi(nq)+tempele(nq),arf(i),arf(nq),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
            close(992)
        end if
        if (nq<i) cycle
"@
        $text = $text.Replace(
            "        nq=fp(i,ii)`r`n        dt0=0.`r`n        if (nq==0) cycle`r`n        if (qq(i,ii)/=0.) cycle`r`n        if (nq<i) cycle",
            $skipEarlyPredicateBlock
        )

        $skipWetDryBlock = @"
        if (($targetAssignmentPredicate) .and. fhpredi(i)<=tol .and. fhpredi(nq)<=tol) then
            open(992,file='original_assignment_skip_predicate_raw.txt',status='unknown',position='append')
            write(992,*) 'skip_wet_dry',tnow,tnext,dt,i,ii,nq,4,'both_depths_le_tol',qq(i,ii),0,0,1,0,fhpredi(i),fhpredi(nq),tol,0.d0,0.d0,hi,hn,arf(i),arf(nq),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
            close(992)
        end if
        if (fhpredi(i)<=tol .and. fhpredi(nq)<=tol) then
"@
        $text = $text.Replace(
            "        if (fhpredi(i)<=tol .and. fhpredi(nq)<=tol) then",
            $skipWetDryBlock
        )

        $skipYbarBlock = @"
        else
            if ($targetAssignmentPredicate) then
                open(992,file='original_assignment_skip_predicate_raw.txt',status='unknown',position='append')
                write(992,*) 'skip_ybar_zero',tnow,tnext,dt,i,ii,nq,5,'ybar_zero',qq(i,ii),0,0,0,1,fhpredi(i),fhpredi(nq),tol,hbar,ybar,hi,hn,arf(i),arf(nq),fv(i,6),fvpredi(i,6),fvpredi2(i,6)
                close(992)
            end if
            fvpredi(i,ii)=0.
"@
        $text = $text.Replace(
            "        else`r`n            fvpredi(i,ii)=0.",
            $skipYbarBlock
        )
    }

    $sourceEntryBlock = @"
    fvdepo(i)=2./5./d50*(grav*sinthetae*frhopredi1(i)/0.02/rhos)**0.5*lambdainverse*fhpredi1(i)**1.5
    if (i==35978 .and. tnow>=226.5d0 .and. tnow<=228.5d0) then
        open(991,file='original_tracked_scalar_momentum_terms_raw.txt',status='unknown',position='append')
        write(991,*) 'source_entry_face_predictor',tnow,tnext,dt,i,6,fp(i,6),2,fhpredi1(i),frhopredi1(i),cv(i),frhopredi1(i)*grav,0.d0,0.d0,0.d0,0.d0,0.d0,0.d0,0.d0,0.d0,0.d0,fv(i,6),fvpredi(i,6),fvpredi2(i,6),0.d0,0,0,qq(i,6),qqmass(i,6),0.d0,fhpredi1(i),fhpredi1(i),0.d0,0.d0,vcomp,vorth,absubar(i),fvdepo(i),2.d0/3.d0*fvdepo(i),0,deporate(i),fvpredi(i,2),fv(i,6),fvpredi(i,6),fvpredi2(i,6),fp(i,6)
        close(991)
    end if
"@
    $text = $text.Replace(
        "    fvdepo(i)=2./5./d50*(grav*sinthetae*frhopredi1(i)/0.02/rhos)**0.5*lambdainverse*fhpredi1(i)**1.5",
        $sourceEntryBlock
    )

    $text = $text.Replace(
        "                fvpredi(i,ii)=dv+fv(i,ii)",
        "                fvpredi(i,ii)=dv+fv(i,ii)`r`n                tracked_sign_flip_status=0"
    )
    $text = $text.Replace(
        "                if (fv(i,ii)*fvpredi(i,ii)<0) then",
        "                if (fv(i,ii)*fvpredi(i,ii)<0) then`r`n                    tracked_sign_flip_status=1"
    )

    $operandNeedle = @"
                if (ii==8) artivis=fv(nq,8)-2.*fv(i,8)-fv(i,4)

                if (ii==1 .or. ii==3 .or. ii==5 .or. ii==7) then
"@
    $operandBlock = @"
                if (ii==8) artivis=fv(nq,8)-2.*fv(i,8)-fv(i,4)
                tracked_fv_nq_same_direction=0.d0
                tracked_fv_i_opposite_direction=0.d0
                if (ii==1) then
                    tracked_fv_nq_same_direction=fv(nq,1)
                    tracked_fv_i_opposite_direction=fv(i,5)
                elseif (ii==2) then
                    tracked_fv_nq_same_direction=fv(nq,2)
                    tracked_fv_i_opposite_direction=fv(i,6)
                elseif (ii==3) then
                    tracked_fv_nq_same_direction=fv(nq,3)
                    tracked_fv_i_opposite_direction=fv(i,7)
                elseif (ii==4) then
                    tracked_fv_nq_same_direction=fv(nq,4)
                    tracked_fv_i_opposite_direction=fv(i,8)
                elseif (ii==5) then
                    tracked_fv_nq_same_direction=fv(nq,5)
                    tracked_fv_i_opposite_direction=fv(i,1)
                elseif (ii==6) then
                    tracked_fv_nq_same_direction=fv(nq,6)
                    tracked_fv_i_opposite_direction=fv(i,2)
                elseif (ii==7) then
                    tracked_fv_nq_same_direction=fv(nq,7)
                    tracked_fv_i_opposite_direction=fv(i,3)
                elseif (ii==8) then
                    tracked_fv_nq_same_direction=fv(nq,8)
                    tracked_fv_i_opposite_direction=fv(i,4)
                end if

                if (ii==1 .or. ii==3 .or. ii==5 .or. ii==7) then
"@
    $text = $text.Replace($operandNeedle, $operandBlock)
    if ($text -notmatch "tracked_fv_nq_same_direction=fv\(nq,1\)") {
        $operandInlineBlock = @"
`$1
                tracked_fv_nq_same_direction=0.d0
                tracked_fv_i_opposite_direction=0.d0
                if (ii==1) then
                    tracked_fv_nq_same_direction=fv(nq,1)
                    tracked_fv_i_opposite_direction=fv(i,5)
                elseif (ii==2) then
                    tracked_fv_nq_same_direction=fv(nq,2)
                    tracked_fv_i_opposite_direction=fv(i,6)
                elseif (ii==3) then
                    tracked_fv_nq_same_direction=fv(nq,3)
                    tracked_fv_i_opposite_direction=fv(i,7)
                elseif (ii==4) then
                    tracked_fv_nq_same_direction=fv(nq,4)
                    tracked_fv_i_opposite_direction=fv(i,8)
                elseif (ii==5) then
                    tracked_fv_nq_same_direction=fv(nq,5)
                    tracked_fv_i_opposite_direction=fv(i,1)
                elseif (ii==6) then
                    tracked_fv_nq_same_direction=fv(nq,6)
                    tracked_fv_i_opposite_direction=fv(i,2)
                elseif (ii==7) then
                    tracked_fv_nq_same_direction=fv(nq,7)
                    tracked_fv_i_opposite_direction=fv(i,3)
                elseif (ii==8) then
                    tracked_fv_nq_same_direction=fv(nq,8)
                    tracked_fv_i_opposite_direction=fv(i,4)
                end if
"@
        $text = [regex]::Replace(
            $text,
            '(?m)^(\s*if \(ii==8\) artivis=fv\(nq,8\)-2\.\*fv\(i,8\)-fv\(i,4\)\s*)$',
            $operandInlineBlock,
            1
        )
    }

    $clampBlock = @"
            fvlimit=limitfr*sqrt(grav*ybar)
            tracked_fvpredi_before_clamp=fvpredi(i,ii)
            tracked_ybar_fvlimit=ybar
            tracked_hbar=hbar
            tracked_frhobar=frhobar
            tracked_cvbar=cvbar
            tracked_miubar=miubar
            tracked_hi=hi
            tracked_hn=hn
            tracked_clamp_status=0
            if (abs(fvpredi(i,ii))>fvlimit) then
                tracked_clamp_status=1
                fvpredi(i,ii)=sign(fvlimit,fvpredi(i,ii))
            end if
            tracked_fvpredi_after_clamp=fvpredi(i,ii)
"@
    $text = $text.Replace(
        "            fvlimit=limitfr*sqrt(grav*ybar)`r`n            if (abs(fvpredi(i,ii))>fvlimit) fvpredi(i,ii)=sign(fvlimit,fvpredi(i,ii))",
        $clampBlock
    )

    $predictorDumpBlock = @"
        qqmass(i,ii)=frhoflux*qq(i,ii)
        if ((($targetAssignmentPredicate) .or. ((i==36238 .or. i==36239) .and. tnow>=226.5d0 .and. tnow<=228.5d0))) then
            open(991,file='original_tracked_scalar_momentum_terms_raw.txt',status='unknown',position='append')
            write(991,*) 'predictor_update_before_mirror',tnow,tnext,dt,i,ii,nq,2,fhpredi1(i),frhopredi1(i),cv(i),tracked_frhobar*grav,manningbar,tracked_miubar,grad,sfy,sfmiu,sfmanning,localvdiff,artivis,dv,fv(i,ii),tracked_fvpredi_before_clamp,tracked_fvpredi_after_clamp,fvlimit,tracked_clamp_status,tracked_sign_flip_status,qq(i,ii),qqmass(i,ii),frhoflux,tracked_ybar_fvlimit,tracked_hbar,tracked_hi,tracked_hn,0.d0,0.d0,0.d0,0.d0,0.d0,0,deporate(i),fvpredi(i,2),fv(i,6),fvpredi(i,6),fvpredi2(i,6),nq,tracked_fv_nq_same_direction,tracked_fv_i_opposite_direction
            close(991)
        end if
"@
    $text = $text.Replace("        qqmass(i,ii)=frhoflux*qq(i,ii)", $predictorDumpBlock)

    $mirrorBlock = @"
        fvpredi(nq,2)=-fvpredi(i,ii)
        if ((($targetAssignmentPredicate) .or. ((i==36238 .or. i==36239) .and. tnow>=226.5d0 .and. tnow<=228.5d0))) then
            open(991,file='original_tracked_scalar_momentum_terms_raw.txt',status='unknown',position='append')
            write(991,*) 'mirrored_opposite_after_assignment',tnow,tnext,dt,i,ii,nq,2,fhpredi1(i),frhopredi1(i),cv(i),tracked_frhobar*grav,manningbar,tracked_miubar,grad,sfy,sfmiu,sfmanning,localvdiff,artivis,dv,fv(i,ii),tracked_fvpredi_before_clamp,tracked_fvpredi_after_clamp,fvlimit,tracked_clamp_status,tracked_sign_flip_status,qq(i,ii),qqmass(i,ii),frhoflux,tracked_ybar_fvlimit,tracked_hbar,tracked_hi,tracked_hn,0.d0,0.d0,0.d0,0.d0,0.d0,0,deporate(i),fvpredi(nq,2),fv(i,6),fvpredi(i,6),fvpredi2(i,6),nq,tracked_fv_nq_same_direction,tracked_fv_i_opposite_direction
            close(991)
            if ($targetStopPredicate) stop 0
        end if
"@
    $text = $text.Replace("        fvpredi(nq,2)=-fvpredi(i,ii)", $mirrorBlock)

    if ((Split-Path $PatchPath -Leaf) -match "extended_upstream_pre222_history") {
        $text = $text.Replace("tnow>=226.5d0", "tnow>=220.0d0")
        $text = $text.Replace(
            "i==35978 .or. i==36238 .or. i==36239",
            "i==35978 .or. i==36238 .or. i==36239 .or. i==36500"
        )
        $text = $text.Replace(
            "i==36238 .or. i==36239",
            "i==36238 .or. i==36239 .or. i==36500"
        )
        if ((Split-Path $PatchPath -Leaf) -match "neighbor_cells") {
            $text = $text.Replace(
                "i==35978 .or. i==36238 .or. i==36239 .or. i==36500",
                "i==35978 .or. i==36238 .or. i==36239 .or. i==36500 .or. i==36762 .or. i==36761"
            )
            $text = $text.Replace(
                "i==36238 .or. i==36239 .or. i==36500",
                "i==36238 .or. i==36239 .or. i==36500 .or. i==36762 .or. i==36761"
            )
        }
    }
    elseif ((Split-Path $PatchPath -Leaf) -match "extended_upstream_history") {
        $text = $text.Replace("tnow>=226.5d0", "tnow>=222.0d0")
        $text = $text.Replace(
            "i==35978 .or. i==36238 .or. i==36239",
            "i==35978 .or. i==36238 .or. i==36239 .or. i==36500"
        )
    }
    Set-Content -Path $dfs -Value $text -Encoding UTF8
    Write-Log "Applied original tracked-scalar momentum faceflux probe instrumentation."
}

function Apply-UnsfinStateDumpInstrumentation {
    param([string]$ProjectDir)
    Apply-MainProgressInstrumentation -ProjectDir $ProjectDir

    $main = Join-Path $ProjectDir "edda main program.F90"
    $dump = Join-Path $ProjectDir "tfail_dump.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dump)) { throw "Missing tfail_dump.F90 in $ProjectDir" }

    $mainText = Get-Content $main -Raw
    if ($mainText -notmatch "dump_unsfin_state_artifacts") {
        $mainText = $mainText.Replace(
            "call dump_instrumented_progress('after_unsfin')",
            "call dump_instrumented_progress('after_unsfin')`r`ncall dump_instrumented_progress('state_dump_begin')`r`ncall dump_unsfin_state_artifacts(imx1,nrow,ncol,maxdirection)`r`ncall dump_instrumented_progress('state_dump_complete')"
        )
        $mainText = $mainText.Replace(
            "call dfs(imx1,nrow,ncol,header,u,maxdirection)",
            "call dump_instrumented_progress('before_dfs')`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $dumpText = Get-Content $dump -Raw
    if ($dumpText -notmatch "subroutine\s+dump_unsfin_state_artifacts") {
        $stateDumpSubroutine = @"

subroutine dump_unsfin_state_artifacts(imx1,nrow,ncol,maxdirection)
    use model_vars
    use grids
    use input_vars
    implicit none
    integer, intent(in) :: imx1,nrow,ncol,maxdirection
    integer :: i,j,qn1,qn2
    integer :: q_bytes
    double precision :: gindx_sum,tfail_sum,fdepth_sum,q_sum
    double precision :: fh_sum,frho_sum,cv_proxy_sum,fv_sum

    gindx_sum=0.d0
    tfail_sum=0.d0
    fdepth_sum=0.d0
    q_sum=0.d0
    fh_sum=0.d0
    frho_sum=0.d0
    cv_proxy_sum=0.d0
    fv_sum=0.d0
    qn1=0
    qn2=0
    q_bytes=0

    if (allocated(gindx)) gindx_sum=sum(dble(gindx(1:min(imx1,size(gindx)))))
    if (allocated(tfail)) tfail_sum=sum(dble(tfail(1:min(imx1,size(tfail)))))
    if (allocated(fdepth)) fdepth_sum=sum(fdepth(1:min(imx1,size(fdepth))))
    if (allocated(q)) then
        qn1=size(q,1)
        qn2=size(q,2)
        q_bytes=qn1*qn2*8
        q_sum=sum(q)
    end if
    if (allocated(fh)) fh_sum=sum(fh(1:min(imx1,size(fh))))
    if (allocated(frho)) frho_sum=sum(frho(1:min(imx1,size(frho))))
    if (allocated(fh) .and. allocated(frho)) cv_proxy_sum=sum((frho(1:min(imx1,size(frho)))-1000.d0)*fh(1:min(imx1,size(fh))))
    if (allocated(fv)) fv_sum=sum(fv)

    open(981,file='unsfin_state_manifest.json',status='replace')
    write(981,'(A)') '{'
    write(981,'(A)') '  "case_id": "20a_or_50a_copied_workdir",'
    write(981,'(A,I0,A)') '  "imx1": ', imx1, ','
    write(981,'(A,I0,A)') '  "nrow": ', nrow, ','
    write(981,'(A,I0,A)') '  "ncol": ', ncol, ','
    write(981,'(A,I0,A)') '  "maxdirection": ', maxdirection, ','
    write(981,'(A,I0,A)') '  "kper": ', kper, ','
    if (allocated(gindx)) then
        write(981,'(A)') '  "gindx_allocated": true,'
    else
        write(981,'(A)') '  "gindx_allocated": false,'
    end if
    if (allocated(tfail)) then
        write(981,'(A)') '  "tfail_allocated": true,'
    else
        write(981,'(A)') '  "tfail_allocated": false,'
    end if
    if (allocated(fdepth)) then
        write(981,'(A)') '  "fdepth_allocated": true,'
    else
        write(981,'(A)') '  "fdepth_allocated": false,'
    end if
    if (allocated(q)) then
        write(981,'(A)') '  "q_allocated": true,'
    else
        write(981,'(A)') '  "q_allocated": false,'
    end if
    write(981,'(A,I0,A)') '  "q_shape_0": ', qn1, ','
    write(981,'(A,I0,A)') '  "q_shape_1": ', qn2, ','
    write(981,'(A,I0,A)') '  "q_expected_bytes": ', q_bytes, ','
    if (allocated(q)) then
        write(981,'(A)') '  "q_values_serialized": true,'
    else
        write(981,'(A)') '  "q_values_serialized": false,'
    end if
    write(981,'(A)') '  "q_values_file": "unsfin_state_q.bin",'
    write(981,'(A)') '  "q_dtype": "float64",'
    write(981,'(A)') '  "q_storage_order": "fortran_column_major_unformatted_stream",'
    write(981,'(A)') '  "indexing_convention": "original active-cell order, Fortran 1-based",'
    write(981,'(A)') '  "dump_marker": "after_unsfin_before_dfs",'
    write(981,'(A)') '  "note": "full q values serialized as compact binary stream; tracked-row text retained for human inspection"'
    write(981,'(A)') '}'
    close(981)

    open(982,file='unsfin_state_checksums.json',status='replace')
    write(982,'(A)') '{'
    write(982,'(A,ES24.16,A)') '  "gindx_sum": ', gindx_sum, ','
    write(982,'(A,ES24.16,A)') '  "tfail_sum": ', tfail_sum, ','
    write(982,'(A,ES24.16,A)') '  "fdepth_sum": ', fdepth_sum, ','
    write(982,'(A,ES24.16,A)') '  "q_sum": ', q_sum, ','
    write(982,'(A,ES24.16,A)') '  "fh_sum": ', fh_sum, ','
    write(982,'(A,ES24.16,A)') '  "frho_sum": ', frho_sum, ','
    write(982,'(A,ES24.16,A)') '  "cv_proxy_sum": ', cv_proxy_sum, ','
    write(982,'(A,ES24.16)') '  "fv_sum": ', fv_sum
    write(982,'(A)') '}'
    close(982)

    if (allocated(gindx)) then
        open(983,file='unsfin_state_gindx.txt',status='replace')
        do i=1,min(imx1,size(gindx))
            write(983,*) gindx(i)
        end do
        close(983)
    end if

    if (allocated(tfail)) then
        open(984,file='unsfin_state_tfail.txt',status='replace')
        do i=1,min(imx1,size(tfail))
            write(984,'(ES24.16)') dble(tfail(i))
        end do
        close(984)
    end if

    if (allocated(fdepth)) then
        open(985,file='unsfin_state_fdepth.txt',status='replace')
        do i=1,min(imx1,size(fdepth))
            write(985,'(ES24.16)') fdepth(i)
        end do
        close(985)
    end if

    if (allocated(q)) then
        open(980,file='unsfin_state_q.bin',status='replace',form='unformatted',access='stream')
        write(980) q
        close(980)
        open(986,file='unsfin_state_q_tracked_rows.txt',status='replace')
        write(986,'(A)') 'cell_index j q'
        do i=1,size(q,1)
            if (i==35978 .or. i==36238) then
                do j=1,size(q,2)
                    write(986,*) i,j,q(i,j)
                end do
            end if
        end do
        close(986)
    end if
end subroutine dump_unsfin_state_artifacts
"@
        Add-Content -Path $dump -Value $stateDumpSubroutine -Encoding ASCII
    }

    Write-Log "Applied unsfin state dump instrumentation."
}

function Apply-UnsfinStateRestoreProbeInstrumentation {
    param([string]$ProjectDir)
    Apply-MainProgressInstrumentation -ProjectDir $ProjectDir

    $main = Join-Path $ProjectDir "edda main program.F90"
    $dump = Join-Path $ProjectDir "tfail_dump.F90"
    $dfs = Join-Path $ProjectDir "dfs.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dump)) { throw "Missing tfail_dump.F90 in $ProjectDir" }
    if (-not (Test-Path $dfs)) { throw "Missing dfs.F90 in $ProjectDir" }

    $mainText = Get-Content $main -Raw
    if ($mainText -notmatch "restore_unsfin_state_artifacts") {
        $mainText = $mainText.Replace(
            "if (fssimul) call unsfin(imx1,u(19),u(2),profil)",
            "if (fssimul) then`r`ncall dump_instrumented_progress('state_restore_begin')`r`ncall restore_unsfin_state_artifacts(imx1)`r`ncall dump_instrumented_progress('state_restore_complete')`r`nelse`r`ncall dump_instrumented_progress('state_restore_skipped_fssimul_false')`r`nend if"
        )
        $mainText = $mainText.Replace(
            "if (fssimul) call dump_unsfin_schedule_artifacts(imx1)",
            "if (fssimul) call dump_instrumented_progress('state_restore_skip_schedule_redump')"
        )
        $mainText = $mainText.Replace(
            "t0=0. ! t0 is the starting time of simulation",
            "call dump_instrumented_progress('restore_before_t0_assignment')`r`nt0=0. ! t0 is the starting time of simulation`r`ncall dump_instrumented_progress('restore_after_t0_assignment')"
        )
        $mainText = $mainText.Replace(
            "dt=1.0 !dtmin ! dt is the time step of simulation, which is set to be dtmin at the beginning",
            "call dump_instrumented_progress('restore_before_dt_assignment')`r`ndt=1.0 !dtmin ! dt is the time step of simulation, which is set to be dtmin at the beginning`r`ncall dump_instrumented_progress('restore_after_dt_assignment')"
        )
        $mainText = $mainText.Replace(
            "ttout=tout ! tout is the output interval, ttout is the output time",
            "call dump_instrumented_progress('restore_before_ttout_assignment')`r`nttout=tout ! tout is the output interval, ttout is the output time`r`ncall dump_instrumented_progress('restore_after_ttout_assignment')"
        )
        $mainText = $mainText.Replace(
            "tminimum=99. ! tminimum is used to record the minimum time step",
            "call dump_instrumented_progress('restore_before_tminimum_assignment')`r`ntminimum=99. ! tminimum is used to record the minimum time step`r`ncall dump_instrumented_progress('restore_after_tminimum_assignment')"
        )
        $mainText = $mainText.Replace(
            "tmaximum=-99 ! tmaximum is used to record the maximum time step",
            "call dump_instrumented_progress('restore_before_tmaximum_assignment')`r`ntmaximum=-99 ! tmaximum is used to record the maximum time step`r`ncall dump_instrumented_progress('restore_after_tmaximum_assignment')"
        )
        $mainText = $mainText.Replace(
            "tnow=t0 !  tnow is the present time",
            "call dump_instrumented_progress('restore_before_tnow_assignment')`r`ntnow=t0 !  tnow is the present time`r`ncall dump_instrumented_progress('restore_after_tnow_assignment')"
        )
        $mainText = $mainText.Replace(
            "tnext=tnow+dt ! tnext is the time of next step",
            "call dump_instrumented_progress('restore_before_tnext_assignment')`r`ntnext=tnow+dt ! tnext is the time of next step`r`ncall dump_instrumented_progress('restore_after_tnext_assignment')"
        )
        $mainText = $mainText.Replace(
            "if (debrissimul) then`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)",
            "call dump_instrumented_progress('restore_before_debris_branch')`r`ncall dump_restore_alloc_status(imx1,nrow,ncol,maxdirection)`r`nif (debrissimul) then`r`ncall dump_instrumented_progress('before_dfs')`r`ncall dfs(imx1,nrow,ncol,header,u,maxdirection)"
        )
        Set-Content -Path $main -Value $mainText -Encoding UTF8
    }

    $dfsText = Get-Content $dfs -Raw
    $restoreAllowsAssignmentLoop = $BuildVariantSafe -in @(
        "dfs_prologue_first_event_early_stop",
        "dfs_prologue_tau_component_early_stop",
        "original_deposition_first_event_early_stop",
        "first_nonzero_deporate",
        "first_tempdebdepothick_positive",
        "first_deposit_writer_positive",
        "target_sparse_checkpoint",
        "target_600s_tracked",
        "restore_extended_upstream_pre222_history"
    )
    if ($restoreAllowsAssignmentLoop) {
        if ($dfsText -notmatch "restore_assignment_loop_enabled") {
            $dfsText = $dfsText.Replace(
                "grav=9.81",
                "call dump_instrumented_progress('dfs_entry')`r`ncall dump_instrumented_progress('restore_assignment_loop_enabled')`r`ngrav=9.81"
            )
            Set-Content -Path $dfs -Value $dfsText -Encoding UTF8
        }
    } elseif ($dfsText -notmatch "assignment_loop_not_attempted_restore_entry_only") {
        $dfsText = $dfsText.Replace(
            "grav=9.81",
            "call dump_instrumented_progress('dfs_entry')`r`ncall dump_instrumented_progress('assignment_loop_not_attempted_restore_entry_only')`r`nreturn`r`ngrav=9.81"
        )
        Set-Content -Path $dfs -Value $dfsText -Encoding UTF8
    }

    $dumpText = Get-Content $dump -Raw
    if ($dumpText -notmatch "subroutine\s+restore_unsfin_state_artifacts") {
        $restoreSubroutine = @"

subroutine restore_unsfin_state_artifacts(imx1)
    use model_vars
    use grids
    implicit none
    integer, intent(in) :: imx1
    integer :: i, j, qn2
    double precision :: tmpd

    qn2=kper
    if (qn2<=0) qn2=18

    if (allocated(gindx)) deallocate(gindx)
    allocate(gindx(imx1))
    open(971,file='unsfin_state_gindx.txt',status='old')
    do i=1,imx1
        read(971,*) gindx(i)
    end do
    close(971)

    if (allocated(tfail)) deallocate(tfail)
    allocate(tfail(imx1))
    open(972,file='unsfin_state_tfail.txt',status='old')
    do i=1,imx1
        read(972,*) tmpd
        tfail(i)=nint(tmpd)
    end do
    close(972)

    if (allocated(fdepth)) deallocate(fdepth)
    allocate(fdepth(imx1))
    open(973,file='unsfin_state_fdepth.txt',status='old')
    do i=1,imx1
        read(973,*) fdepth(i)
    end do
    close(973)

    if (allocated(q)) deallocate(q)
    allocate(q(imx1,qn2))
    open(974,file='unsfin_state_q.bin',status='old',form='unformatted',access='stream')
    read(974) q
    close(974)

    call dump_instrumented_progress('state_restore_arrays_loaded')
    open(975,file='state_restore_manifest_check.txt',status='replace')
    write(975,*) 'imx1',imx1,'kper',qn2,'gindx_sum',sum(dble(gindx)),'tfail_sum',sum(dble(tfail)),'fdepth_sum',sum(fdepth),'q_sum',sum(q)
    close(975)
end subroutine restore_unsfin_state_artifacts

subroutine dump_restore_alloc_status(imx1,nrow,ncol,maxdirection)
    use model_vars
    use grids
    use input_vars
    implicit none
    integer, intent(in) :: imx1,nrow,ncol,maxdirection
    integer :: qn1,qn2,gindx_n,tfail_n,fdepth_n,fh_n,frho_n,fv_n1,fv_n2
    double precision :: gindx_sum,tfail_sum,fdepth_sum,q_sum,fh_sum,frho_sum,fv_sum

    qn1=0
    qn2=0
    gindx_n=0
    tfail_n=0
    fdepth_n=0
    fh_n=0
    frho_n=0
    fv_n1=0
    fv_n2=0
    gindx_sum=0.d0
    tfail_sum=0.d0
    fdepth_sum=0.d0
    q_sum=0.d0
    fh_sum=0.d0
    frho_sum=0.d0
    fv_sum=0.d0

    if (allocated(q)) then
        qn1=size(q,1)
        qn2=size(q,2)
        q_sum=sum(q)
    end if
    if (allocated(gindx)) then
        gindx_n=size(gindx)
        gindx_sum=sum(dble(gindx))
    end if
    if (allocated(tfail)) then
        tfail_n=size(tfail)
        tfail_sum=sum(dble(tfail))
    end if
    if (allocated(fdepth)) then
        fdepth_n=size(fdepth)
        fdepth_sum=sum(fdepth)
    end if
    if (allocated(fh)) then
        fh_n=size(fh)
        fh_sum=sum(fh)
    end if
    if (allocated(frho)) then
        frho_n=size(frho)
        frho_sum=sum(frho)
    end if
    if (allocated(fv)) then
        fv_n1=size(fv,1)
        fv_n2=size(fv,2)
        fv_sum=sum(fv)
    end if

    open(976,file='restore_allocatable_status_matrix.csv',status='replace')
    write(976,'(A)') 'name,allocated,dim1,dim2,sum'
    write(976,*) 'q',allocated(q),qn1,qn2,q_sum
    write(976,*) 'gindx',allocated(gindx),gindx_n,0,gindx_sum
    write(976,*) 'tfail',allocated(tfail),tfail_n,0,tfail_sum
    write(976,*) 'fdepth',allocated(fdepth),fdepth_n,0,fdepth_sum
    write(976,*) 'fh',allocated(fh),fh_n,0,fh_sum
    write(976,*) 'frho',allocated(frho),frho_n,0,frho_sum
    write(976,*) 'fv',allocated(fv),fv_n1,fv_n2,fv_sum
    write(976,*) 'imx1_arg',.true.,imx1,0,0.d0
    write(976,*) 'nrow_arg',.true.,nrow,0,0.d0
    write(976,*) 'ncol_arg',.true.,ncol,0,0.d0
    write(976,*) 'maxdirection_arg',.true.,maxdirection,0,0.d0
    close(976)

    call dump_instrumented_progress('after_restore_alloc_check')
end subroutine dump_restore_alloc_status
"@
        Add-Content -Path $dump -Value $restoreSubroutine -Encoding ASCII
    }

    Write-Log "Applied unsfin state restore DFS-entry probe instrumentation."
}

function Apply-UnsfinInternalCheckpointInstrumentation {
    param([string]$ProjectDir)
    Apply-MainProgressInstrumentation -ProjectDir $ProjectDir

    $main = Join-Path $ProjectDir "edda main program.F90"
    $dump = Join-Path $ProjectDir "tfail_dump.F90"
    $unsfin = Join-Path $ProjectDir "unsfin.F90"
    if (-not (Test-Path $main)) { throw "Missing edda main program.F90 in $ProjectDir" }
    if (-not (Test-Path $dump)) { throw "Missing tfail_dump.F90 in $ProjectDir" }
    if (-not (Test-Path $unsfin)) { throw "Missing unsfin.F90 in $ProjectDir" }

    $unsfinText = Get-Content $unsfin -Raw
    if ($unsfinText -notmatch "dump_unsfin_internal_checkpoint") {
        $unsfinText = $unsfinText.Replace(
            "    nmax3=0;nmax0=0",
            "    call dump_instrumented_progress('unsfin_entry')`r`n    call dump_unsfin_internal_checkpoint('unsfin_entry',imx1,0,kper,0.d0)`r`n    nmax3=0;nmax0=0"
        )
        $unsfinText = $unsfinText.Replace(
            "allocate (q(imx1,kper))",
            "allocate (q(imx1,kper))`r`ncall dump_instrumented_progress('unsfin_after_q_allocate')`r`ncall dump_unsfin_internal_checkpoint('unsfin_after_q_allocate',imx1,0,kper,0.d0)"
        )
        $unsfinText = $unsfinText.Replace(
            "finf=10.`r`n`r`n! loop over all grid cells to compute parameters used in analytical solution",
            "finf=10.`r`ncall dump_instrumented_progress('unsfin_q_fill_begin')`r`ncall dump_unsfin_internal_checkpoint('unsfin_q_fill_begin',imx1,0,kper,0.d0)`r`n`r`n! loop over all grid cells to compute parameters used in analytical solution"
        )
        $unsfinText = $unsfinText.Replace(
            "    write (*,*) 'starting computing', i, 'cell'",
            "    ! internal checkpoint probe: suppress per-cell stdout to keep original run bounded"
        )
        $unsfinText = $unsfinText.Replace(
            "    if (mod(i-1,2000)==0) write (*,*) i-1 ! cells completed",
            "    if (mod(i-1,2000)==0) call dump_unsfin_internal_checkpoint('unsfin_cell_progress',imx1,i,kper,tnown)"
        )
        $unsfinText = $unsfinText.Replace(
            "    end do `r`n    `r`n    ! compute the roots for cell i",
            "    end do `r`n    if (i==35978 .or. i==36238 .or. mod(i-1,2000)==0) call dump_unsfin_internal_checkpoint('unsfin_q_fill_progress',imx1,i,kper,tnown)`r`n    `r`n    ! compute the roots for cell i"
        )
        $unsfinText = $unsfinText.Replace(
            "call inidoublelayer(nmax,i,kper,ts,lambdaa,miua,lambdab,miub,lambdac,miuc,da,db,dc,lt,lb,nra,nrb,nrc)",
            "if (i==35978 .or. i==36238 .or. mod(i-1,2000)==0) call dump_unsfin_internal_checkpoint('unsfin_doublelayer_begin',imx1,i,kper,tnown)`r`ncall inidoublelayer(nmax,i,kper,ts,lambdaa,miua,lambdab,miub,lambdac,miuc,da,db,dc,lt,lb,nra,nrb,nrc)"
        )
        $unsfinText = $unsfinText.Replace(
            "    end do`r`n    `r`n`r`n`r`n! end do i=1,imxl",
            "    end do`r`n    if (i==35978 .or. i==36238 .or. mod(i-1,2000)==0) call dump_unsfin_internal_checkpoint('unsfin_doublelayer_complete',imx1,i,kper,tnown)`r`n    `r`n`r`n`r`n! end do i=1,imxl"
        )
        $unsfinText = $unsfinText.Replace(
            "! end do i=1,imxl`r`nend do     `r`nreturn",
            "! end do i=1,imxl`r`nend do     `r`ncall dump_instrumented_progress('unsfin_q_fill_complete')`r`ncall dump_unsfin_internal_checkpoint('unsfin_before_return',imx1,imx1,kper,tnown)`r`ncall dump_instrumented_progress('unsfin_before_return')`r`nreturn"
        )
        Set-Content -Path $unsfin -Value $unsfinText -Encoding UTF8
    }

    $dumpText = Get-Content $dump -Raw
    if ($dumpText -notmatch "subroutine\s+dump_unsfin_internal_checkpoint") {
        $checkpointSubroutine = @"

subroutine dump_unsfin_internal_checkpoint(stage,imx1,cell_index,kper_value,tnown_value)
    use model_vars
    use grids
    implicit none
    character(len=*), intent(in) :: stage
    integer, intent(in) :: imx1,cell_index,kper_value
    double precision, intent(in) :: tnown_value
    integer :: i,j,qn1,qn2
    double precision :: gindx_sum,tfail_sum,fdepth_sum,q_sum

    gindx_sum=0.d0
    tfail_sum=0.d0
    fdepth_sum=0.d0
    q_sum=0.d0
    qn1=0
    qn2=0

    if (allocated(gindx)) gindx_sum=sum(dble(gindx(1:min(imx1,size(gindx)))))
    if (allocated(tfail)) tfail_sum=sum(dble(tfail(1:min(imx1,size(tfail)))))
    if (allocated(fdepth)) fdepth_sum=sum(fdepth(1:min(imx1,size(fdepth))))
    if (allocated(q)) then
        qn1=size(q,1)
        qn2=size(q,2)
        q_sum=sum(q)
    end if

    open(987,file='unsfin_internal_checkpoint_events.csv',status='unknown',position='append')
    write(987,*) trim(stage),imx1,cell_index,kper_value,tnown_value,allocated(q),qn1,qn2,gindx_sum,tfail_sum,fdepth_sum,q_sum
    close(987)

    open(988,file='unsfin_q_state_manifest.json',status='replace')
    write(988,'(A)') '{'
    write(988,'(A,A,A)') '  "stage": "', trim(stage), '",'
    write(988,'(A,I0,A)') '  "imx1": ', imx1, ','
    write(988,'(A,I0,A)') '  "cell_index": ', cell_index, ','
    write(988,'(A,I0,A)') '  "kper": ', kper_value, ','
    if (allocated(q)) then
        write(988,'(A)') '  "q_allocated": true,'
    else
        write(988,'(A)') '  "q_allocated": false,'
    end if
    write(988,'(A,I0,A)') '  "q_shape_0": ', qn1, ','
    write(988,'(A,I0,A)') '  "q_shape_1": ', qn2, ','
    write(988,'(A)') '  "dump_level": "q_state_or_progress",'
    write(988,'(A)') '  "indexing_convention": "original active-cell order, Fortran 1-based"'
    write(988,'(A)') '}'
    close(988)

    open(989,file='unsfin_q_state_checksums.json',status='replace')
    write(989,'(A)') '{'
    write(989,'(A,ES24.16,A)') '  "gindx_sum": ', gindx_sum, ','
    write(989,'(A,ES24.16,A)') '  "tfail_sum": ', tfail_sum, ','
    write(989,'(A,ES24.16,A)') '  "fdepth_sum": ', fdepth_sum, ','
    write(989,'(A,ES24.16)') '  "q_sum": ', q_sum
    write(989,'(A)') '}'
    close(989)

    if (allocated(q)) then
        open(986,file='unsfin_q_state_tracked_rows.txt',status='replace')
        write(986,'(A)') 'cell_index j q'
        do i=1,size(q,1)
            if (i==35978 .or. i==36238) then
                do j=1,size(q,2)
                    write(986,*) i,j,q(i,j)
                end do
            end if
        end do
        close(986)
    end if
end subroutine dump_unsfin_internal_checkpoint
"@
        Add-Content -Path $dump -Value $checkpointSubroutine -Encoding ASCII
    }

    Write-Log "Applied unsfin internal checkpoint instrumentation."
}

function Apply-GFortranCompatibilityShims {
    param([string]$ProjectDir)

    # These edits are applied only to the copied sandbox build tree. They do not
    # change the original EDDA sources or any production solver code.
    $changed = @()
    $sourceFiles = Get-ChildItem -Path (Join-Path $ProjectDir "*") -File -Include *.F90,*.f90,*.for,*.f
    foreach ($file in $sourceFiles) {
        $text = Get-Content $file.FullName -Raw
        $next = $text

        # Intel Fortran accepts logical == .true.; gfortran requires .eqv.
        $next = [regex]::Replace(
            $next,
            '([A-Za-z_][A-Za-z0-9_]*(?:\s*\([^)]*\))?)\s*==\s*\.(true|false)\.',
            {
                param($match)
                "$($match.Groups[1].Value) .eqv. .$($match.Groups[2].Value)."
            },
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )

        # gfortran rejects Intel's width-less integer format; I0 keeps integer
        # output semantics while making the copied build tree standards-clean.
        $next = [regex]::Replace(
            $next,
            'format\(\s*i\s*\)',
            'format(I0)',
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )

        # The original main program assigns fsmin before allocating the
        # allocatable array, then initializes it again after allocation. Intel
        # tolerated this in the historical project; gfortran segfaults. Guarding
        # the pre-allocation assignment changes no scientific state because the
        # post-allocation initialization remains intact.
        $next = [regex]::Replace(
            $next,
            '(?m)^(\s*)fsmin\s*=\s*10\.\s*$',
            '$1if (allocated(fsmin)) fsmin=10.',
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )

        # The legacy source zeroes inithzb even though that allocatable array is
        # not allocated in this code path and is not otherwise consumed. Guard
        # this copied-build initialization so the gfortran instrumentation run
        # can reach unsfin without changing later scientific state.
        $next = [regex]::Replace(
            $next,
            'inithzt\s*=\s*0\.\s*;\s*inithzb\s*=\s*0\.',
            'inithzt=0.; if (allocated(inithzb)) inithzb=0.',
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )

        $next = [regex]::Replace(
            $next,
            'inidesatt\s*=\s*0\.\s*;\s*inidesatb\s*=\s*0\.',
            'if (allocated(inidesatt)) inidesatt=0.; if (allocated(inidesatb)) inidesatb=0.',
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )

        if ($next -ne $text) {
            Set-Content -Path $file.FullName -Value $next -Encoding UTF8
            $changed += $file.Name
        }
    }

    if ($changed.Count -gt 0) {
        Write-Log "Applied sandbox-only gfortran compatibility shims to: $($changed -join ', ')"
    } else {
        Write-Log "No sandbox-only gfortran compatibility shims were needed."
    }
}

function Get-VfprojSourceList {
    param([string]$ProjectDir)
    $vfproj = Join-Path $ProjectDir "EDDA.vfproj"
    $text = Get-Content $vfproj -Raw
    $matches = [regex]::Matches($text, 'RelativePath="\.\\([^"]+\.(?:F90|f90|for|f))"')
    $sources = @()
    foreach ($match in $matches) {
        $sources += (Join-Path $ProjectDir $match.Groups[1].Value)
    }
    return $sources
}

function Get-GFortranSourceOrder {
    param([string[]]$SourcePaths)
    $priority = @(
        "input_file_defs.f90",
        "input_vars.f90",
        "model_vars.f90",
        "grids.f90",
        "stormdrain_vars.f90",
        "inflow_vars.F90",
        "outflow_vars.F90",
        "output_file_defs.f90"
    )
    $ordered = @()
    foreach ($name in $priority) {
        $match = $SourcePaths | Where-Object { [IO.Path]::GetFileName($_) -ceq $name } | Select-Object -First 1
        if ($match) {
            $ordered += $match
        }
    }
    foreach ($source in $SourcePaths) {
        if ($ordered -notcontains $source) {
            $ordered += $source
        }
    }
    return $ordered
}

"" | Set-Content -Path $BuildLog -Encoding UTF8
Write-Log "Sandbox root: $SandboxRoot"
Write-Log "Case root: $CaseRoot"
Write-Log "Patch path: $PatchPath"
Write-Log "Output work dir: $OutputWorkDir"
Write-Log "Build variant: $BuildVariantSafe"

if (-not (Test-Path $CaseRoot)) {
    Write-Log "BLOCKED: case root not found."
    exit 2
}

Copy-SourceProject -Source $CaseRoot -Destination $OutputWorkDir
if ($BuildVariantSafe -in @("progress_only", "no_large_array_dump", "dfs_noop_stub", "dfs_entry_marker", "dfs_prologue_minimal", "dfs_progress_only", "dfs_prologue_entry_marker_only", "dfs_prologue_no_local_arrays_probe", "dfs_prologue_guard_non_arrays", "dfs_prologue_allocatable_non_arrays", "dfs_prologue_static_locals", "dfs_prologue_first_event_early_stop", "dfs_prologue_tau_component_early_stop", "original_deposition_first_event_early_stop", "first_nonzero_deporate", "first_tempdebdepothick_positive", "first_deposit_writer_positive", "target_sparse_checkpoint", "target_600s_tracked", "restore_extended_upstream_pre222_history")) {
    Apply-MainProgressInstrumentation -ProjectDir $OutputWorkDir
} else {
    Apply-TfailInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "downstream|deposition_positive|deposition_directional_velocity") {
    Apply-DownstreamDfsInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "minimal_gate") {
    Apply-MinimalDfsGateInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "erosion_event_probe") {
    Apply-OriginalErosionEventProbeInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "first_event_tau_components") {
    Apply-OriginalFirstEventTauComponentInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "target_36762_erosion_components") {
    Apply-OriginalTarget36762ErosionComponentInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "target_35716_erosion_components") {
    Apply-OriginalTarget35716ErosionComponentInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "dfs_call_boundary") {
    Apply-DfsCallBoundaryProbeInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "dfs_prologue_storage|deposition_positive|deposition_directional_velocity") {
    Apply-DfsPrologueStorageProbeInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "tracked_scalar_momentum_terms|momentum_assignment_terms_probe_v2|momentum_assignment_terms_all_direction|assignment_skip_predicate|depth_component_ledger") {
    Apply-OriginalTrackedScalarMomentumProbeInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "unsfin_state_dump") {
    Apply-UnsfinStateDumpInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "unsfin_state_restore") {
    Apply-UnsfinStateRestoreProbeInstrumentation -ProjectDir $OutputWorkDir
}
if ((Split-Path $PatchPath -Leaf) -match "unsfin_internal_checkpoint") {
    Apply-UnsfinInternalCheckpointInstrumentation -ProjectDir $OutputWorkDir
}
Apply-GFortranCompatibilityShims -ProjectDir $OutputWorkDir

$sources = Get-VfprojSourceList -ProjectDir $OutputWorkDir
$gfortranSources = Get-GFortranSourceOrder -SourcePaths $sources
$orderLines = @("# Fortran Build Order", "", "## Source Order From Copied EDDA.vfproj", "")
for ($idx = 0; $idx -lt $sources.Count; $idx++) {
    $orderLines += "$($idx + 1). ``$([IO.Path]::GetFileName($sources[$idx]))``"
}
$orderLines += ""
$orderLines += "## gfortran Manual Build Order"
$orderLines += ""
for ($idx = 0; $idx -lt $gfortranSources.Count; $idx++) {
    $orderLines += "$($idx + 1). ``$([IO.Path]::GetFileName($gfortranSources[$idx]))``"
}
$orderLines | Set-Content -Path $BuildOrderMd -Encoding UTF8

$msbuild = Find-Executable -CommandName "msbuild" -Candidates @(
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\amd64\MSBuild.exe",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
)
$gfortran = Find-Executable -CommandName "gfortran" -Candidates @(
    (Join-Path $SandboxRoot "toolchain\msys64\mingw64\bin\gfortran.exe"),
    (Join-Path $SandboxRoot "toolchain\msys64\ucrt64\bin\gfortran.exe"),
    "C:\msys64\mingw64\bin\gfortran.exe",
    "C:\msys64\ucrt64\bin\gfortran.exe"
)

$builtExe = $null
$buildStatus = "blocked"

if ($gfortran) {
    Write-Log "Attempting gfortran manual build."
    $gfortranBin = Split-Path $gfortran -Parent
    if ($env:PATH -notlike "*$gfortranBin*") {
        $env:PATH = "$gfortranBin;$env:PATH"
    }
    $exeOut = Join-Path $OutputWorkDir "EDDA_instrumented_${BuildVariantSafe}_gfortran.exe"
    $baseFlags = @(
        "-ffree-line-length-none",
        "-fallow-argument-mismatch",
        "-fallow-invalid-boz",
        "-fdec",
        "-std=legacy",
        "-fbacktrace",
        "-O0",
        "-g"
    )
    $variantFlags = @("-fcheck=bounds")
    switch ($BuildVariantSafe.ToLowerInvariant()) {
        "debug_bounds" {
            $variantFlags = @(
                "-fcheck=bounds",
                "-ffpe-trap=invalid,zero,overflow",
                "-finit-real=snan",
                "-finit-integer=-999999",
                "-Wl,--stack,536870912"
            )
        }
        "debug_backtrace" {
            $variantFlags = @("-fcheck=bounds", "-Wl,--stack,536870912")
        }
        "debug_all" {
            $variantFlags = @("-fcheck=all", "-Wl,--stack,536870912")
        }
        "static_locals" {
            $variantFlags = @("-fcheck=bounds", "-fno-automatic", "-Wl,--stack,536870912")
        }
        "minimal_io" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "first_event_early_stop" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "progress_only" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "no_large_array_dump" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "dfs_noop_stub" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "dfs_entry_marker" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "dfs_prologue_minimal" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "dfs_progress_only" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "dfs_first_event_early_stop" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "dfs_prologue_entry_marker_only" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "dfs_prologue_no_local_arrays_probe" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "dfs_prologue_guard_non_arrays" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "dfs_prologue_allocatable_non_arrays" {
            $variantFlags = @("-fno-automatic", "-Wl,--stack,536870912")
        }
        "dfs_prologue_static_locals" {
            $variantFlags = @("-fno-automatic", "-fmax-stack-var-size=0", "-Wl,--stack,536870912")
        }
        "dfs_prologue_first_event_early_stop" {
            $variantFlags = @("-fno-automatic", "-fmax-stack-var-size=0", "-Wl,--stack,536870912")
        }
        "dfs_prologue_tau_component_early_stop" {
            $variantFlags = @("-fno-automatic", "-fmax-stack-var-size=0", "-Wl,--stack,536870912")
        }
        "original_deposition_first_event_early_stop" {
            $variantFlags = @("-fno-automatic", "-fmax-stack-var-size=0", "-Wl,--stack,536870912")
        }
        { $_ -in @("first_nonzero_deporate", "first_tempdebdepothick_positive", "first_deposit_writer_positive", "target_sparse_checkpoint", "target_600s_tracked") } {
            $variantFlags = @("-fno-automatic", "-fmax-stack-var-size=0", "-Wl,--stack,536870912")
        }
        default {
            $variantFlags = @("-fcheck=bounds", "-fno-automatic", "-Wl,--stack,536870912")
        }
    }
    if ((Split-Path $PatchPath -Leaf) -match "minimal_gate" -and $BuildVariantSafe -eq "debug_bounds") {
        $variantFlags = @("-fcheck=bounds", "-fno-automatic", "-Wl,--stack,536870912")
    }
    $args = $baseFlags + $variantFlags + @("-o", $exeOut) + $gfortranSources
    Write-Log "gfortran flags: $($baseFlags + $variantFlags -join ' ')"
    $output = & $gfortran @args 2>&1
    $exitCode = $LASTEXITCODE
    Add-Content -Path $BuildLog -Value $output -Encoding UTF8
    Write-Log "gfortran exit code: $exitCode"
    if ($exitCode -eq 0 -and (Test-Path $exeOut)) {
        $builtExe = $exeOut
        $buildStatus = "built_with_gfortran"
    } else {
        $buildStatus = "gfortran_failed"
    }
}

if (-not $builtExe -and -not $gfortran -and $msbuild) {
    $sln = Join-Path $OutputWorkDir "EDDA.sln"
    if (Test-Path $sln) {
        Write-Log "Attempting MSBuild on copied solution."
        $output = & $msbuild $sln /t:Build /p:Configuration=Debug /p:Platform=x64 /nologo /verbosity:normal 2>&1
        $exitCode = $LASTEXITCODE
        Add-Content -Path $BuildLog -Value $output -Encoding UTF8
        Write-Log "MSBuild exit code: $exitCode"
        $candidateExe = Get-ChildItem $OutputWorkDir -Recurse -File -Filter EDDA.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($candidateExe) {
            $builtExe = $candidateExe.FullName
            $buildStatus = "built_with_msbuild"
        }
    }
}

if (-not $builtExe -and $buildStatus -eq "blocked") {
    Write-Log "BLOCKED: no usable Intel Fortran/MSBuild integration or gfortran build output."
}

$manifest = @(
    "# Instrumented Executable Manifest",
    "",
    "- build_status: $buildStatus",
    "- build_variant: $BuildVariantSafe",
    "- built_exe: $builtExe",
    "- work_dir: $OutputWorkDir",
    "- build_log: $BuildLog",
    "- patch_path: $PatchPath",
    "",
    "## Safety",
    "",
    "Original EDDA.exe and original results are not modified by this script."
)
$manifest | Set-Content -Path $ManifestMd -Encoding UTF8
Copy-Item -LiteralPath $BuildLog -Destination $LegacyBuildLog -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $BuildOrderMd -Destination $LegacyBuildOrderMd -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $ManifestMd -Destination $LegacyManifestMd -Force -ErrorAction SilentlyContinue

Write-Output "build_status=$buildStatus"
Write-Output "build_variant=$BuildVariantSafe"
Write-Output "built_exe=$builtExe"
Write-Output "manifest=$ManifestMd"
