"""Numeric literal helpers for matching the supplied Visual Fortran EDDA build.

The original project declares most solver variables as ``double precision`` but
uses many unsuffixed literals, for example ``grav=9.81`` and ``tol=0.01``.
With the checked-in Intel Visual Fortran project settings, these literals are
default real constants first, then converted to double precision. Reusing the
rounded default-real value avoids changing dry/wet gates and CFL phase.
"""

from __future__ import annotations

import numpy as np


def default_real(value: float) -> float:
    """Return a Python float carrying Fortran default-real rounding."""
    return float(np.float32(value))


def default_real_pow(base: float, exponent: float) -> float:
    """Evaluate ``base**exponent`` as Fortran default real, then widen."""
    return float(np.float32(base) ** np.float32(exponent))


FORTRAN_SQRT2 = default_real_pow(2.0, 0.5)
FORTRAN_INV_SQRT2 = 1.0 / FORTRAN_SQRT2
FORTRAN_PI = default_real(3.141592653589793)
FORTRAN_DEG2RAD = FORTRAN_PI / 180.0
# Chamoli dfs.F90 reconstructs ``absubar`` with the unsuffixed literal
# ``0.707``.  Intel Fortran evaluates that literal as default REAL before it
# is widened for the double-precision velocity expression.
DFS_ABSUBAR_DIAGONAL = default_real(0.707)
# Test31's source is not a Chamoli alias: its signed reconstruction applies
# these additional unsuffixed default-REAL weights after the cardinal and
# diagonal terms have been formed. Keep their source rounding explicitly.
DFS_TEST31_ABSUBAR_CARDINAL_WEIGHT = default_real(0.4142)
DFS_TEST31_ABSUBAR_DIAGONAL_GROUP_WEIGHT = default_real(0.2929)

DFS_GRAV = default_real(9.81)
DFS_MANNINGB = default_real(0.0538)
DFS_MANNINGM = default_real(6.0896)
DFS_TOL = default_real(0.01)
DFS_CVTOL = default_real(0.1)
DFS_ARTIVIS_COEFF = default_real(0.02)
DFS_CFL_COEFF = default_real(0.6)
DFS_LAMBDA_EXP = default_real(0.333)
DFS_MANNING_EXP = default_real(1.333)
DFS_MIU_BASE = default_real(0.001)
DFS_TWO_THIRDS = default_real(2.0 / 3.0)
# dfs.F90:380 `fvdepo(i)=2./5./d50*...` folds `2./5.` in default REAL before
# the double-precision division by `d50`.
DFS_TWO_FIFTHS = default_real(2.0 / 5.0)
DFS_SLOPE_BRANCH = default_real(0.175)
# Chamoli dfs.F90:470/:880-905 barrier branches compare `cv(i)` against the
# unsuffixed literals `0.2` / `0.4`, scale flexible-barrier velocity by `0.3`
# and use the fixed flux density `1330.`.
DFS_BARRIER_CV_LOW = default_real(0.2)
DFS_BARRIER_CV_HIGH = default_real(0.4)
# BJ dfs.F90:474/:891 uses unsuffixed `0.65` for barrier deposition and the
# flexible-barrier middle bin. Chamoli uses `0.4` at the same sites.
DFS_BARRIER_CV_HIGH_BJ = default_real(0.65)
DFS_FLEXIBLE_VELOCITY_FACTOR = default_real(0.3)
DFS_FLEXIBLE_MASS_DENSITY = default_real(1330.0)
# dfs.F90 erosion source branch writes erorate only when `fhpredi1(i)>0.05`.
DFS_EROSION_DEPTH_TRIGGER = default_real(0.05)
DFS_CVLIMIT_BREAK = default_real(0.15)
DFS_CVLIMIT_QUADRATIC_COEFF = default_real(6.7)
DFS_DPFHTEST_OUTFLOW = default_real(0.1)
# dfs.F90: if (abs(volumerelaerror)>0.001) then
DFS_VOLUME_REL_TOL = default_real(0.001)
INFR_TOLERR = default_real(1.0e-8)
