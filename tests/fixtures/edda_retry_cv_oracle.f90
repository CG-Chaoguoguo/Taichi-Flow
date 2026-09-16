! Reduced source-order oracle, NOT a full EDDA/Chamoli simulation.
! Based on EDDA-Fortran@8b0b7cf4b64266f941ae87daaae7f86eaf7d7630:
! Chamoli-EDDA file/Chamoli-EDDA file/dfs.F90:312-327,342-359,797-800.
! Two attempts share accepted h/rho. The first attempt is deliberately
! rejected after source evaluation; cv is NOT restored at the retry label.
program edda_retry_cv_oracle
  use iso_fortran_env, only: real64
  implicit none
  integer :: attempt
  real(real64) :: h, rho, cv, cvstar, dt, rhow, rhos, kst, ir
  real(real64) :: fhw, inflx, fhpredi1, frhopredi1
  rhow=1000.0_real64
  rhos=2650.0_real64
  cvstar=0.65_real64
  h=1.0_real64
  cv=0.325_real64
  rho=rhow+cv*(rhos-rhow)
  kst=10.0_real64
  do attempt=1,2
    dt=0.1_real64 / real(attempt,real64)
    ! Original staging with zero rainfall/inflow, no exfiltration.
    fhw=h*(1-cv/cvstar)
    inflx=fhw/dt
    if (kst<inflx) then
      ir=kst
    else
      ir=inflx
    end if
    fhpredi1=h-ir*dt
    frhopredi1=(rho*h-ir*dt*rhow)/fhpredi1
    if (fhpredi1<=0.0_real64) fhpredi1=0.0_real64
    if (fhpredi1<=1.e-18_real64) frhopredi1=rhow
    ! This source-stage cv assignment survives the original goto 1000.
    cv=(frhopredi1-rhow)/(rhos-rhow)
    if (cv<1.e-18_real64) cv=0.0_real64
    write(*,'(I1,2(1X,ES24.16))') attempt,fhpredi1,cv
  end do
end program edda_retry_cv_oracle
