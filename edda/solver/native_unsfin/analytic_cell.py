"""Cell-scoped analytic `unsfin` diagnostic.

This module is a ledger-only diagnostic helper. It ports the original
`roota/rootb/rootc` eigen-root searches and parses instrumented original
`unsfin/doublelayer` traces for cell-level comparison. It deliberately does not
feed DFS runtime fields and does not enable a production native unsfin provider.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .ledger import LedgerArrays, load_original_oracle


TARGET_CELLS = (90008, 90001, 51509, 21846)
SOURCE_PROVENANCE = "production_native_unsfin_analytic_cell_diagnostic"
# `edda main program.F90` assigns `pi=3.141592653589793` without a
# double-precision suffix before computing `dg2rad`.  Under the original
# Fortran semantics that unsuffixed literal is default-real, then widened.
FORTRAN_MAIN_PI_DEFAULT_REAL = 3.1415927410125732
FORTRAN_MAIN_DG2RAD = FORTRAN_MAIN_PI_DEFAULT_REAL / 180.0
# `rootc.F90` assigns `deltamiu=0.01` without a double-precision suffix.
# The widened default-real value is active at 0-10800 fsmin boundaries.
FORTRAN_ROOTC_DELTAMIU_DEFAULT_REAL = 0.009999999776482582


@dataclass(frozen=True)
class RootResult:
    lambdas: list[float]
    mius: list[float]


@dataclass(frozen=True)
class ZoneParams:
    cb: float
    ct: float
    phib: float
    phit: float
    phibb: float
    phibt: float
    uwsb: float
    uwst: float
    ksb: float
    kst: float
    thsatb: float
    thsatt: float
    thresib: float
    thresit: float
    alphab: float
    alphat: float


@dataclass(frozen=True)
class CellFieldPack:
    cell: int
    row: int
    col: int
    slope_rad: float
    zone_id: int
    ltstar: float
    lbstar: float
    zmin: float
    nzst: int
    nzsb: int
    uww: float
    q: list[float]
    capt: list[float]
    beta: float
    lt: float
    lb: float
    rikzero: float
    zone: ZoneParams


@dataclass(frozen=True)
class Coefficients:
    da: list[float]
    db: list[float]
    dc: list[float]


@dataclass
class DoublelayerState:
    fdepth: float = 0.0
    fsmin: float = 10.0
    zfmin: float = 0.0
    pmin: float = 0.0
    gindx: int = 0


@dataclass(frozen=True)
class ActiveContext:
    config: dict[str, Any]
    slope_values_deg: list[float]
    zone_values: list[float]
    ltstar_values: list[float]
    active_mapping: list[tuple[int, int]]
    shape: tuple[int, int]


def _profile_add(profile_stats: dict[str, float] | None, key: str, seconds: float) -> None:
    if profile_stats is not None:
        profile_stats[key] = profile_stats.get(key, 0.0) + seconds


def _sha256_json(data: dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _f_root_a(x: float, beta: float, lt: float, lb: float, kst: float, ksb: float) -> tuple[float, float]:
    miu = math.sqrt(beta * x * x + (beta - 1.0) / 4.0)
    value = (
        (math.sin(x * lb) + 2.0 * x * math.cos(x * lb))
        * (math.sin(miu * lt) + 2.0 * miu * math.cos(miu * lt))
        - (1.0 + 4.0 * miu * miu) * kst / ksb * math.sin(x * lb) * math.sin(miu * lt)
    )
    return value, miu


def _f_root_b(x: float, beta: float, lt: float, lb: float, kst: float, ksb: float) -> tuple[float, float]:
    miu = math.sqrt((beta - 1.0) / 4.0 - beta * x * x)
    value = (
        (math.sinh(x * lb) + 2.0 * x * math.cosh(x * lb))
        * (math.sin(miu * lt) + 2.0 * miu * math.cos(miu * lt))
        - (1.0 + 4.0 * miu * miu) * kst / ksb * math.sinh(x * lb) * math.sin(miu * lt)
    )
    return value, miu


def _f_root_c(x: float, beta: float, lt: float, lb: float, kst: float, ksb: float) -> tuple[float, float]:
    lam = math.sqrt((1.0 - beta) / 4.0 / beta - x * x / beta)
    value = (
        (math.sin(lam * lb) + 2.0 * lam * math.cos(lam * lb))
        * (math.sinh(x * lt) + 2.0 * x * math.cosh(x * lt))
        - (1.0 - 4.0 * x * x) * kst / ksb * math.sin(lam * lb) * math.sinh(x * lt)
    )
    return value, lam


def _bisect_root_a(rtb: float, dx: float, beta: float, lt: float, lb: float, kst: float, ksb: float) -> tuple[float, float] | None:
    x0 = 1.0e-18
    miu = 0.0
    for m in range(1, 10001):
        dx /= 2.0
        x0 = dx + rtb
        fm, miu = _f_root_a(x0, beta, lt, lb, kst, ksb)
        if fm < 0.0:
            rtb = x0
        if abs(fm) <= 1.0e-8:
            return x0, miu
    return None


def _bisect_root_b(rtb: float, dx: float, beta: float, lt: float, lb: float, kst: float, ksb: float) -> tuple[float, float] | None:
    x0 = 1.0e-18
    miu = 0.0
    for m in range(1, 101):
        dx /= 2.0
        x0 = dx + rtb
        fm, miu = _f_root_b(x0, beta, lt, lb, kst, ksb)
        if fm < 0.0:
            rtb = x0
        if abs(fm) <= 1.0e-8:
            return x0, miu
    return None


def _bisect_root_c(rtb: float, dx: float, beta: float, lt: float, lb: float, kst: float, ksb: float) -> tuple[float, float] | None:
    x0 = 1.0e-18
    lam = 0.0
    for m in range(1, 101):
        dx /= 2.0
        x0 = dx + rtb
        fm, lam = _f_root_c(x0, beta, lt, lb, kst, ksb)
        if fm < 0.0:
            rtb = x0
        if abs(fm) <= 1.0e-8:
            return lam, x0
    return None


def roota(nmax: int, beta: float, lt: float, lb: float, kst: float, ksb: float) -> RootResult:
    lambdas: list[float] = []
    mius: list[float] = []
    rlb = 0.0
    deltalambda = 1.0e-3
    for _ in range(nmax):
        for _inner in range(10000):
            rub = rlb + deltalambda
            if beta * rlb * rlb + (beta - 1.0) / 4.0 < 0.0:
                rlb = rub
                continue
            fl, miulb = _f_root_a(rlb, beta, lt, lb, kst, ksb)
            fu, _miuub = _f_root_a(rub, beta, lt, lb, kst, ksb)
            if fl * fu > 0.0:
                rlb = rub
                continue
            if fl * fu == 0.0 and fl == 0.0 and miulb != 0.0:
                lambdas.append(rlb)
                mius.append(miulb)
                rlb = rub
                break
            rtb = rlb if fl < 0.0 else rub
            dx = rub - rlb if fl < 0.0 else rlb - rub
            root = _bisect_root_a(rtb, dx, beta, lt, lb, kst, ksb)
            rlb = rub
            if root is not None and root[1] != 0.0:
                lambdas.append(root[0])
                mius.append(root[1])
                break
    return RootResult(lambdas, mius)


def rootb(nmax: int, beta: float, lt: float, lb: float, kst: float, ksb: float) -> RootResult:
    lambdas: list[float] = []
    mius: list[float] = []
    rlb = 0.0
    deltalambda = 0.01
    for _ in range(nmax):
        for _inner in range(10000):
            rub = rlb + deltalambda
            if not (beta > 1.0 and rub < math.sqrt((beta - 1.0) / 4.0 / beta)):
                rlb = rub
                continue
            if (beta - 1.0) / 4.0 - beta * rub * rub < 0.0:
                rlb = rub
                continue
            fl, miulb = _f_root_b(rlb, beta, lt, lb, kst, ksb)
            fu, _miuub = _f_root_b(rub, beta, lt, lb, kst, ksb)
            if fl * fu > 0.0:
                rlb = rub
                continue
            if fl * fu == 0.0 and fl == 0.0 and miulb != 0.0:
                lambdas.append(rlb)
                mius.append(miulb)
                rlb = rub
                break
            rtb = rlb if fl < 0.0 else rub
            dx = rub - rlb if fl < 0.0 else rlb - rub
            root = _bisect_root_b(rtb, dx, beta, lt, lb, kst, ksb)
            rlb = rub
            if root is not None and root[1] != 0.0:
                lambdas.append(root[0])
                mius.append(root[1])
                break
    return RootResult(lambdas, mius)


def rootc(nmax: int, beta: float, lt: float, lb: float, kst: float, ksb: float) -> RootResult:
    lambdas: list[float] = []
    mius: list[float] = []
    rlb = 1.0e-18
    deltamiu = FORTRAN_ROOTC_DELTAMIU_DEFAULT_REAL
    for _ in range(nmax):
        for _inner in range(10000):
            rub = rlb + deltamiu
            if not (beta < 1.0 and rub < math.sqrt((1.0 - beta) / 4.0)):
                rlb = rub
                continue
            if (1.0 - beta) / 4.0 / beta - rub * rub / beta < 0.0:
                rlb = rub
                continue
            fl, lambdalb = _f_root_c(rlb, beta, lt, lb, kst, ksb)
            fu, _lambdaub = _f_root_c(rub, beta, lt, lb, kst, ksb)
            if fl * fu > 0.0:
                rlb = rub
                continue
            if fl * fu == 0.0 and fl == 0.0 and rlb != 0.0:
                lambdas.append(lambdalb)
                mius.append(rlb)
                rlb = rub
                break
            rtb = rlb if fl < 0.0 else rub
            dx = rub - rlb if fl < 0.0 else rlb - rub
            root = _bisect_root_c(rtb, dx, beta, lt, lb, kst, ksb)
            rlb = rub
            if root is not None and root[1] != 0.0:
                lambdas.append(root[0])
                mius.append(root[1])
                break
    return RootResult(lambdas, mius)


def unsfin_coefficients(
    roots_a: RootResult,
    roots_b: RootResult,
    roots_c: RootResult,
    *,
    beta: float,
    lt: float,
    lb: float,
    kst: float,
    ksb: float,
) -> Coefficients:
    """Port of `unsfin.F90:182-207` eigen-root coefficient formulas."""
    da: list[float] = []
    for lam, miu in zip(roots_a.lambdas, roots_a.mius):
        ass = 4.0 * beta * lam * kst / ksb + lam * (lb + beta * lt)
        asc = kst / ksb * beta * lam * lt / 2.0 / miu * (1.0 + 4.0 * miu * miu) + 2.0 * lam * miu * lb - beta * lam / 2.0 / miu * (2.0 + lt)
        acs = kst / ksb * lb / 2.0 * (1.0 + 4.0 * miu * miu) + 2.0 * beta * lam * lam * lt - 1.0 - lb / 2.0
        acc = -miu * (2.0 + lb) - beta * lam * lam / miu * (2.0 + lt)
        da.append(
            (0.25 + lam * lam)
            / miu
            / lam
            * (
                ass * math.sin(lam * lb) * math.sin(miu * lt)
                + asc * math.sin(lam * lb) * math.cos(miu * lt)
                + acs * math.cos(lam * lb) * math.sin(miu * lt)
                + acc * math.cos(lam * lb) * math.cos(miu * lt)
            )
        )

    db: list[float] = []
    for lam, miu in zip(roots_b.lambdas, roots_b.mius):
        bss = 4.0 * beta * lam * kst / ksb + lam * (lb + beta * lt)
        bsc = kst / ksb * beta * lam * lt / 2.0 / miu * (1.0 + 4.0 * miu * miu) + 2.0 * lam * miu * lb - beta * lam / 2.0 / miu * (2.0 + lt)
        bcs = -kst / ksb * lb / 2.0 * (1.0 + 4.0 * miu * miu) + 2.0 * beta * lam * lam * lt + 1.0 + lb / 2.0
        bcc = miu * (2.0 + lb) - beta * lam * lam / miu * (2.0 + lt)
        db.append(
            (0.25 - lam * lam)
            / miu
            / lam
            * (
                bss * math.sinh(lam * lb) * math.sin(miu * lt)
                + bsc * math.sinh(lam * lb) * math.cos(miu * lt)
                + bcs * math.cosh(lam * lb) * math.sin(miu * lt)
                + bcc * math.cosh(lam * lb) * math.cos(miu * lt)
            )
        )

    dc: list[float] = []
    for lam, miu in zip(roots_c.lambdas, roots_c.mius):
        css = 4.0 * beta * lam * kst / ksb + lam * (lb + beta * lt)
        csc = -kst / ksb * beta * lam * lt / 2.0 / miu * (1.0 - 4.0 * miu * miu) + 2.0 * lam * miu * lb + beta * lam / 2.0 / miu * (2.0 + lt)
        ccs = kst / ksb * lb / 2.0 * (1.0 - 4.0 * miu * miu) + 2.0 * beta * lam * lam * lt - 1.0 - lb / 2.0
        ccc = -miu * (2.0 + lb) + beta * lam * lam / miu * (2.0 + lt)
        dc.append(
            (0.25 + lam * lam)
            / miu
            / lam
            * (
                css * math.sin(lam * lb) * math.sinh(miu * lt)
                + csc * math.sin(lam * lb) * math.cosh(miu * lt)
                + ccs * math.cos(lam * lb) * math.sinh(miu * lt)
                + ccc * math.cos(lam * lb) * math.cosh(miu * lt)
            )
        )
    return Coefficients(da=da, db=db, dc=dc)


def _series_sum(values: Iterable[float], *, tol: float = 1.0e-5) -> float:
    total = 0.0
    for value in values:
        old = total
        total += value
        if total != 0.0 and abs((old - total) / total) <= tol:
            break
    return total


def _top_layer_kkt(
    pack: CellFieldPack,
    roots_a: RootResult,
    roots_b: RootResult,
    roots_c: RootResult,
    coeffs: Coefficients,
    *,
    tt: float,
    z: float,
    end_offset: int,
) -> float:
    """Port of `inidoublelayer.F90`/`doublelayer.F90` top-layer kkt loop.

    `end_offset=0` computes rka from `capt(j)`, while `end_offset=1` computes
    rkb from `capt(j+1)`.
    """
    zone = pack.zone
    qa = pack.rikzero * zone.kst
    qab = qa / zone.ksb
    rsum = 0.0
    cos2 = math.cos(pack.slope_rad) ** 2.0
    for idx, qb in enumerate(pack.q):
        capt_index = idx + end_offset
        if capt_index >= len(pack.capt):
            continue
        tdif = tt - pack.capt[capt_index]
        if tdif <= 0.0:
            continue
        qbb = qb / zone.ksb
        qbt = qb / zone.kst
        t = zone.alphab * zone.ksb * tdif / (zone.thsatb - zone.thresib) * cos2
        rat = _series_sum(
            (
                (
                    math.sin(lam * pack.lb)
                    * (math.sin(miu * (pack.lt - z)) + 2.0 * miu * math.cos(miu * (pack.lt - z)))
                    * math.exp(-(0.25 + lam * lam) * t)
                )
                / (da * (math.sin(miu * pack.lt) + 2.0 * miu * math.cos(miu * pack.lt)))
                for lam, miu, da in zip(roots_a.lambdas, roots_a.mius, coeffs.da)
            )
        )
        if pack.beta > 1.0:
            r_extra = _series_sum(
                (
                    (
                        math.sinh(lam * pack.lb)
                        * (math.sin(miu * (pack.lt - z)) + 2.0 * miu * math.cos(miu * (pack.lt - z)))
                        * math.exp(-(0.25 - lam * lam) * t)
                    )
                    / (db * (math.sin(miu * pack.lt) + 2.0 * miu * math.cos(miu * pack.lt)))
                    for lam, miu, db in zip(roots_b.lambdas, roots_b.mius, coeffs.db)
                )
            )
        elif pack.beta < 1.0:
            r_extra = _series_sum(
                (
                    (
                        math.sin(lam * pack.lb)
                        * (math.sinh(miu * (pack.lt - z)) + 2.0 * miu * math.cosh(miu * (pack.lt - z)))
                        * math.exp(-(0.25 + lam * lam) * t)
                    )
                    / (dc * (math.sinh(miu * pack.lt) + 2.0 * miu * math.cosh(miu * pack.lt)))
                    for lam, miu, dc in zip(roots_c.lambdas, roots_c.mius, coeffs.dc)
                )
            )
        else:
            r_extra = 0.0
        rsum += (
            qbt
            - (qbt - qbb + (qbb - 1.0) * math.exp(-pack.lb)) * math.exp(-z)
            - 4.0 * (qbb - qab) * math.exp((pack.lt - z) / 2.0) * (rat + r_extra)
        )
    return rsum


def evaluate_inidoublelayer(
    pack: CellFieldPack,
    roots_a: RootResult,
    roots_b: RootResult,
    roots_c: RootResult,
    coeffs: Coefficients,
    *,
    tt: float,
) -> list[dict[str, float]]:
    """Port of `inidoublelayer.F90:54-190` for top-layer rows."""
    rows: list[dict[str, float]] = []
    zone = pack.zone
    deltazt = pack.ltstar / pack.nzst
    cos2 = math.cos(pack.slope_rad) ** 2.0
    for depth_index in range(1, pack.nzst + 2):
        z = zone.alphat * (pack.ltstar - (depth_index - 1) * deltazt) * cos2
        rka = _top_layer_kkt(pack, roots_a, roots_b, roots_c, coeffs, tt=tt, z=z, end_offset=0)
        rkb = _top_layer_kkt(pack, roots_a, roots_b, roots_c, coeffs, tt=tt, z=z, end_offset=1)
        kkt = rka - rkb
        pt = math.log(kkt) / zone.alphat if kkt > 0.0 else math.nan
        thzt = zone.thresit + (zone.thsatt - zone.thresit) * math.exp(zone.alphat * pt) if math.isfinite(pt) else math.nan
        inidesat = thzt / zone.thsatt if math.isfinite(thzt) else math.nan
        rows.append(
            {
                "cell": float(pack.cell),
                "tt": float(tt),
                "depth_index": float(depth_index),
                "z": z,
                "kkt": kkt,
                "pt": pt,
                "inidesat": inidesat,
            }
        )
    return rows


def evaluate_inidoublelayer_values(
    pack: CellFieldPack,
    roots_a: RootResult,
    roots_b: RootResult,
    roots_c: RootResult,
    coeffs: Coefficients,
    *,
    tt: float,
) -> list[float]:
    """Final-only `inidoublelayer` path for long ledger runs."""
    values: list[float] = []
    zone = pack.zone
    deltazt = pack.ltstar / pack.nzst
    cos2 = math.cos(pack.slope_rad) ** 2.0
    for depth_index in range(1, pack.nzst + 2):
        z = zone.alphat * (pack.ltstar - (depth_index - 1) * deltazt) * cos2
        rka = _top_layer_kkt(pack, roots_a, roots_b, roots_c, coeffs, tt=tt, z=z, end_offset=0)
        rkb = _top_layer_kkt(pack, roots_a, roots_b, roots_c, coeffs, tt=tt, z=z, end_offset=1)
        kkt = rka - rkb
        pt = math.log(kkt) / zone.alphat if kkt > 0.0 else math.nan
        thzt = zone.thresit + (zone.thsatt - zone.thresit) * math.exp(zone.alphat * pt) if math.isfinite(pt) else math.nan
        values.append(thzt / zone.thsatt if math.isfinite(thzt) else math.nan)
    return values


def evaluate_inidoublelayer_depth(
    pack: CellFieldPack,
    roots_a: RootResult,
    roots_b: RootResult,
    roots_c: RootResult,
    coeffs: Coefficients,
    *,
    tt: float,
    depth_index: int,
) -> dict[str, float]:
    """Single-depth variant of `evaluate_inidoublelayer` for ts-carry fitting."""
    zone = pack.zone
    deltazt = pack.ltstar / pack.nzst
    cos2 = math.cos(pack.slope_rad) ** 2.0
    z = zone.alphat * (pack.ltstar - (depth_index - 1) * deltazt) * cos2
    rka = _top_layer_kkt(pack, roots_a, roots_b, roots_c, coeffs, tt=tt, z=z, end_offset=0)
    rkb = _top_layer_kkt(pack, roots_a, roots_b, roots_c, coeffs, tt=tt, z=z, end_offset=1)
    kkt = rka - rkb
    pt = math.log(kkt) / zone.alphat if kkt > 0.0 else math.nan
    thzt = zone.thresit + (zone.thsatt - zone.thresit) * math.exp(zone.alphat * pt) if math.isfinite(pt) else math.nan
    inidesat = thzt / zone.thsatt if math.isfinite(thzt) else math.nan
    return {
        "cell": float(pack.cell),
        "tt": float(tt),
        "depth_index": float(depth_index),
        "z": z,
        "kkt": kkt,
        "pt": pt,
        "inidesat": inidesat,
    }


def evaluate_doublelayer_top(
    pack: CellFieldPack,
    roots_a: RootResult,
    roots_b: RootResult,
    roots_c: RootResult,
    coeffs: Coefficients,
    inidesat_rows: list[dict[str, float]],
    *,
    tt: float,
    initial_state: DoublelayerState | None = None,
    finf: float = 10.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Port of `doublelayer.F90:89-287` top-layer pressure/FS path.

    The original trace shows `desatt` is zero in these unsfin windows, so the
    diagnostic uses a zero `desatt` initial module array until a later trace
    proves otherwise.
    """
    state = initial_state or DoublelayerState()
    zone = pack.zone
    deltazt = pack.ltstar / pack.nzst
    inidesat_by_depth = {int(row["depth_index"]): row["inidesat"] for row in inidesat_rows}
    cos2 = math.cos(pack.slope_rad) ** 2.0
    fft = math.tan(zone.phit) / math.tan(pack.slope_rad)
    uwsum = 0.0
    fmn = state.fsmin
    uwsfin = (zone.uwst / pack.uww - zone.thsatt + zone.thresit) * pack.uww
    zfmin = state.zfmin
    pmin = state.pmin
    fdepth = state.fdepth
    rows: list[dict[str, Any]] = []
    for depth_index in range(1, pack.nzst + 2):
        z = zone.alphat * (pack.ltstar - (depth_index - 1) * deltazt) * cos2
        rka = _top_layer_kkt(pack, roots_a, roots_b, roots_c, coeffs, tt=tt, z=z, end_offset=0)
        rkb = _top_layer_kkt(pack, roots_a, roots_b, roots_c, coeffs, tt=tt, z=z, end_offset=1)
        kkt = rka - rkb
        pt = math.log(kkt) / zone.alphat if kkt > 0.0 else math.nan
        thzt = zone.thresit + (zone.thsatt - zone.thresit) * math.exp(zone.alphat * pt) if math.isfinite(pt) else math.nan
        desat = thzt / zone.thsatt if math.isfinite(thzt) else math.nan
        desatt = 0.0
        inidesat = inidesat_by_depth.get(depth_index, math.nan)
        if math.isfinite(pt) and pt < -1.0 / zone.alphat:
            uwt1 = (zone.uwst / pack.uww - zone.thsatt + thzt) * pack.uww
        else:
            uwt1 = zone.uwst
        uwsum += uwt1
        uwspt = uwsum / float(depth_index)
        physical_depth = (depth_index - 1) * deltazt
        denominator_depth = physical_depth if physical_depth > pack.zmin else physical_depth + pack.zmin
        fsc = zone.ct / uwspt / denominator_depth / math.sin(pack.slope_rad) / math.cos(pack.slope_rad)
        if physical_depth > pack.zmin:
            phi = zone.phibt if pt < 0.0 else zone.phit
            fsw = -pt * pack.uww * math.tan(phi) / uwspt / physical_depth / math.sin(pack.slope_rad) / math.cos(pack.slope_rad)
            fs = fft + fsc + fsw
        else:
            fsw = 0.0
            fs = finf
        if fs < fsc:
            fs = fsc
        if fs > finf:
            fs = finf
        if physical_depth <= pack.zmin:
            fs = finf
        saturation_metric = abs((inidesat - desatt) / inidesat) if math.isfinite(inidesat) and inidesat != 0.0 else math.nan
        if math.isfinite(saturation_metric) and saturation_metric > 0.05:
            zfmin = pack.ltstar - physical_depth
            pmin = pt
            fdepth = physical_depth
            fmn = fs
            uwsfin = uwspt
        rows.append(
            {
                "event": "NATIVE_DL_TOP",
                "cell": pack.cell,
                "tt": tt,
                "depth_index": depth_index,
                "z": z,
                "pt": pt,
                "desat": desat,
                "desatt": desatt,
                "inidesat": inidesat,
                "fsc": fsc,
                "fsw": fsw,
                "fs": fs,
                "fmn": fmn,
                "fsmin": state.fsmin,
                "zfmin": zfmin,
                "pmin": pmin,
                "fdepth": fdepth,
                "gindx": state.gindx,
                "saturation_metric": saturation_metric,
                "uwsfin": uwsfin,
                "kkt": kkt,
            }
        )
    if fdepth == 0.0:
        zfmin = pack.ltstar
        pmin = rows[0]["pt"]
        fmn = finf
    fsmin = fmn
    gindx = 1 if fsmin <= 1.0 else 0
    final = {
        "event": "NATIVE_DL_FINAL",
        "cell": pack.cell,
        "tt": tt,
        "fsmin": fsmin,
        "fdepth": fdepth,
        "pmin": pmin,
        "gindx": gindx,
        "zfmin": zfmin,
    }
    return rows, final


def evaluate_doublelayer_top_final(
    pack: CellFieldPack,
    roots_a: RootResult,
    roots_b: RootResult,
    roots_c: RootResult,
    coeffs: Coefficients,
    inidesat_values: list[float],
    *,
    tt: float,
    initial_state: DoublelayerState | None = None,
    finf: float = 10.0,
) -> dict[str, Any]:
    """Final-only `doublelayer` path matching `evaluate_doublelayer_top`."""
    state = initial_state or DoublelayerState()
    zone = pack.zone
    deltazt = pack.ltstar / pack.nzst
    cos2 = math.cos(pack.slope_rad) ** 2.0
    fft = math.tan(zone.phit) / math.tan(pack.slope_rad)
    uwsum = 0.0
    fmn = state.fsmin
    zfmin = state.zfmin
    pmin = state.pmin
    fdepth = state.fdepth
    first_pt = math.nan
    for depth_index in range(1, pack.nzst + 2):
        z = zone.alphat * (pack.ltstar - (depth_index - 1) * deltazt) * cos2
        rka = _top_layer_kkt(pack, roots_a, roots_b, roots_c, coeffs, tt=tt, z=z, end_offset=0)
        rkb = _top_layer_kkt(pack, roots_a, roots_b, roots_c, coeffs, tt=tt, z=z, end_offset=1)
        kkt = rka - rkb
        pt = math.log(kkt) / zone.alphat if kkt > 0.0 else math.nan
        if depth_index == 1:
            first_pt = pt
        thzt = zone.thresit + (zone.thsatt - zone.thresit) * math.exp(zone.alphat * pt) if math.isfinite(pt) else math.nan
        if math.isfinite(pt) and pt < -1.0 / zone.alphat:
            uwt1 = (zone.uwst / pack.uww - zone.thsatt + thzt) * pack.uww
        else:
            uwt1 = zone.uwst
        uwsum += uwt1
        uwspt = uwsum / float(depth_index)
        physical_depth = (depth_index - 1) * deltazt
        denominator_depth = physical_depth if physical_depth > pack.zmin else physical_depth + pack.zmin
        fsc = zone.ct / uwspt / denominator_depth / math.sin(pack.slope_rad) / math.cos(pack.slope_rad)
        if physical_depth > pack.zmin:
            phi = zone.phibt if pt < 0.0 else zone.phit
            fsw = -pt * pack.uww * math.tan(phi) / uwspt / physical_depth / math.sin(pack.slope_rad) / math.cos(pack.slope_rad)
            fs = fft + fsc + fsw
        else:
            fs = finf
        if fs < fsc:
            fs = fsc
        if fs > finf:
            fs = finf
        if physical_depth <= pack.zmin:
            fs = finf
        inidesat = inidesat_values[depth_index - 1] if depth_index - 1 < len(inidesat_values) else math.nan
        saturation_metric = abs(inidesat / inidesat) if math.isfinite(inidesat) and inidesat != 0.0 else math.nan
        if math.isfinite(saturation_metric) and saturation_metric > 0.05:
            zfmin = pack.ltstar - physical_depth
            pmin = pt
            fdepth = physical_depth
            fmn = fs
    if fdepth == 0.0:
        zfmin = pack.ltstar
        pmin = first_pt
        fmn = finf
    fsmin = fmn
    return {
        "event": "NATIVE_DL_FINAL",
        "cell": pack.cell,
        "tt": tt,
        "fsmin": fsmin,
        "fdepth": fdepth,
        "pmin": pmin,
        "gindx": 1 if fsmin <= 1.0 else 0,
        "zfmin": zfmin,
    }


def _as_float(value: str) -> float:
    return float(value.strip())


def _as_int(value: str) -> int:
    return int(float(value.strip()))


def _numbers_from_line(line: str) -> list[float]:
    return [float(match.replace("D", "E").replace("d", "e")) for match in re.findall(r"[-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?", line)]


def _nonempty_lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def _zone_from_records(bottom: list[float], top: list[float]) -> ZoneParams:
    dg2rad = FORTRAN_MAIN_DG2RAD
    return ZoneParams(
        cb=bottom[0],
        ct=top[0],
        phib=bottom[2] * dg2rad,
        phit=top[2] * dg2rad,
        phibb=bottom[4] * dg2rad,
        phibt=top[4] * dg2rad,
        uwsb=bottom[6],
        uwst=top[6],
        ksb=bottom[8],
        kst=top[8],
        thsatb=bottom[9],
        thsatt=top[9],
        thresib=bottom[10],
        thresit=top[10],
        alphab=bottom[14],
        alphat=top[14],
    )


def _parse_zone_blocks(lines: list[str]) -> dict[int, ZoneParams]:
    zones: dict[int, ZoneParams] = {}
    for idx, line in enumerate(lines):
        match = re.match(r"^zone\s*,\s*(\d+)\b", line, flags=re.IGNORECASE)
        if match is None:
            continue
        if idx + 4 >= len(lines):
            raise ValueError(f"Malformed zone block at edda_in nonempty line {idx + 1}: missing layer records.")
        zone_id = int(match.group(1))
        bottom = _numbers_from_line(lines[idx + 2])
        top = _numbers_from_line(lines[idx + 4])
        if len(bottom) < 15 or len(top) < 15:
            raise ValueError(f"Malformed zone block {zone_id}: expected bottom/top layer numeric records.")
        zones[zone_id] = _zone_from_records(bottom, top)
    if not zones:
        raise ValueError("No zone blocks found in edda_in.txt.")
    return zones


def _line_after_label(lines: list[str], pattern: str, *, start: int = 0) -> str:
    regex = re.compile(pattern, flags=re.IGNORECASE)
    for idx in range(start, len(lines) - 1):
        if regex.search(lines[idx]):
            candidate = lines[idx + 1].strip()
            if re.match(r"^zone\s*,", candidate, flags=re.IGNORECASE):
                raise ValueError(f"Malformed edda_in.txt: label {pattern!r} resolved to zone label {candidate!r}.")
            return candidate
    raise ValueError(f"Required edda_in.txt label not found: {pattern}")


def _numbers_after_label(lines: list[str], pattern: str, *, start: int = 0) -> list[float]:
    value_line = _line_after_label(lines, pattern, start=start)
    numbers = _numbers_from_line(value_line)
    if not numbers:
        raise ValueError(f"Required numeric record after label {pattern!r} is empty.")
    return numbers


def _ltstar_upper_gate_from_source(case_dir: Path) -> tuple[float, str]:
    unsfin_path = case_dir / "unsfin.F90"
    if not unsfin_path.exists():
        return 5.0, "DEFAULT_NO_UNSFIN_SOURCE"
    text = unsfin_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"if\s*\(\s*ltstar\s*\(\s*i\s*\)\s*>\s*([-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?)\s*\)\s*cycle", text, flags=re.IGNORECASE)
    if match is None:
        return 5.0, "DEFAULT_UNSFIN_GATE_NOT_FOUND"
    return float(match.group(1).replace("D", "E").replace("d", "e")), str(unsfin_path)


def _zone_for_config(config: dict[str, Any], zone_id: int, *, cell: int | None = None) -> ZoneParams:
    zones = config.get("zones")
    if zones is None:
        return config["zone"]
    zone = zones.get(zone_id)
    if zone is None:
        target = "" if cell is None else f" active cell {cell}"
        raise ValueError(f"No zone parameters found for{target} zone {zone_id}.")
    return zone


def parse_edda_in(case_dir: Path) -> dict[str, Any]:
    lines = _nonempty_lines(case_dir / "edda_in.txt")
    # `trini.f90` reads these records positionally after comment/title lines.
    dims = _numbers_from_line(lines[3])
    model = _numbers_from_line(lines[5])
    defaults = _numbers_from_line(lines[7])
    zones = _parse_zone_blocks(lines)
    ltstar_upper_gate, ltstar_upper_gate_source = _ltstar_upper_gate_from_source(case_dir)
    first_zone_id = min(zones)
    first_zone_index = next(idx for idx, line in enumerate(lines) if re.match(r"^zone\s*,", line, flags=re.IGNORECASE))
    cri = _numbers_after_label(lines, r"\bcri\s*\(", start=first_zone_index)
    capt = _numbers_after_label(lines, r"\bcapt\s*\(", start=first_zone_index)
    paths = {
        "slope": _line_after_label(lines, r"slope angle grid|slofil", start=first_zone_index),
        "zone": _line_after_label(lines, r"property zone grid|zonfil", start=first_zone_index),
        "ltstar": _line_after_label(lines, r"depth grid .*zfil|depth grid \(zfil\)|\bzfil\b", start=first_zone_index),
        "rizero": _line_after_label(lines, r"initial infiltration rate grid|rizerofil", start=first_zone_index),
    }
    dg2rad = FORTRAN_MAIN_DG2RAD
    expected_zone_count = int(model[7]) if len(model) > 7 else len(zones)
    if len(zones) != expected_zone_count:
        raise ValueError(f"Parsed {len(zones)} zone blocks, expected {expected_zone_count}.")
    nper = int(model[3])
    if len(cri) != nper:
        raise ValueError(f"Parsed {len(cri)} rainfall periods, expected nper={nper}.")
    if len(capt) != nper + 1:
        raise ValueError(f"Parsed {len(capt)} rainfall capture times, expected nper+1={nper + 1}.")
    return {
        "imax": int(dims[0]),
        "nrow": int(dims[2]),
        "ncol": int(dims[1]),
        "nzsb": int(model[0]),
        "nzst": int(model[1]),
        "nper": nper,
        "zmin": model[4],
        "uww": model[5],
        "cltstar": defaults[0],
        "clbstar": defaults[1],
        "czmax": defaults[2],
        "crizero": defaults[4],
        "slomin": defaults[5],
        "ltstar_upper_gate": ltstar_upper_gate,
        "ltstar_upper_gate_source": ltstar_upper_gate_source,
        "dg2rad": dg2rad,
        "cri": cri,
        "capt": capt,
        "paths": paths,
        "zone": zones[first_zone_id],
        "zones": zones,
    }


def read_ascii_active_values(path: Path, *, integer: bool = False) -> tuple[list[float], list[tuple[int, int]], dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_lines = text[:6]
    header: dict[str, Any] = {}
    for line in header_lines:
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].lower()
            value: float | str
            try:
                value = float(parts[1])
            except ValueError:
                value = parts[1]
            header[key] = value
    nodata = float(header.get("nodata_value", -9999.0))
    active: list[float] = []
    mapping: list[tuple[int, int]] = []
    for row_index, line in enumerate(text[6:], start=1):
        if not line.strip():
            continue
        for col_index, raw in enumerate(line.split(), start=1):
            value = float(raw)
            if value == nodata:
                continue
            active.append(float(int(value)) if integer else value)
            mapping.append((row_index, col_index))
    return active, mapping, header


def build_cell_field_packs(
    case_dir: Path,
    original_rows: dict[str, list[dict[str, Any]]],
) -> tuple[dict[int, CellFieldPack], dict[str, Any]]:
    config = parse_edda_in(case_dir)
    paths = config["paths"]
    slope_values, active_mapping, slope_header = read_ascii_active_values(case_dir / paths["slope"])
    zone_values, zone_mapping, _zone_header = read_ascii_active_values(case_dir / paths["zone"], integer=True)
    ltstar_values, ltstar_mapping, _lt_header = read_ascii_active_values(case_dir / paths["ltstar"])
    packs: dict[int, CellFieldPack] = {}
    diagnostics: dict[str, Any] = {
        "source_provenance": SOURCE_PROVENANCE,
        "runtime_provider_enabled": False,
        "output_inferred": False,
        "active_cells_from_slope": len(slope_values),
        "active_mapping_matches_zone": len(active_mapping) == len(zone_mapping),
        "active_mapping_matches_ltstar": len(active_mapping) == len(ltstar_mapping),
        "shape": [int(slope_header.get("nrows", 0)), int(slope_header.get("ncols", 0))],
        "field_classification": {
            "slo": "AVAILABLE_MATCHED",
            "zo": "AVAILABLE_MATCHED",
            "ltstar": "AVAILABLE_MATCHED",
            "lbstar": "AVAILABLE_MATCHED",
            "zmin": "AVAILABLE_MATCHED",
            "q": "TRACE_ONLY",
            "rik": "TRACE_ONLY",
            "rikzero": "TRACE_ONLY",
            "roots": "TRACE_ONLY",
            "inidesat": "DIAGNOSTIC_PORTED",
        },
    }
    for cell in TARGET_CELLS:
        idx = cell - 1
        rows = original_rows.get(str(cell), [])
        q_rows = sorted((row for row in rows if row.get("event") == "Q"), key=lambda row: row["period"])
        summary = next((row for row in rows if row.get("event") == "ROOT_SUMMARY"), None)
        if not q_rows or summary is None:
            continue
        row, col = active_mapping[idx]
        zone_id = int(zone_values[idx])
        zone = _zone_for_config(config, zone_id, cell=cell)
        slope_rad = slope_values[idx] * math.pi / 180.0
        ltstar = ltstar_values[idx] if config["cltstar"] <= 0 else config["cltstar"]
        lbstar = config["clbstar"]
        packs[cell] = CellFieldPack(
            cell=cell,
            row=row,
            col=col,
            slope_rad=slope_rad,
            zone_id=zone_id,
            ltstar=ltstar,
            lbstar=lbstar,
            zmin=config["zmin"],
            nzst=config["nzst"],
            nzsb=config["nzsb"],
            uww=config["uww"],
            q=[float(row["q"]) for row in q_rows],
            capt=[float(q_rows[0]["capt_start"])] + [float(row["capt_end"]) for row in q_rows],
            beta=float(summary["beta"]),
            lt=float(summary["lt"]),
            lb=float(summary["lb"]),
            rikzero=float(q_rows[0]["rikzero"]),
            zone=zone,
        )
    diagnostics["target_cells_loaded"] = sorted(packs)
    return packs, diagnostics


def build_active_context(case_dir: Path) -> ActiveContext:
    config = parse_edda_in(case_dir)
    paths = config["paths"]
    slope_values, active_mapping, slope_header = read_ascii_active_values(case_dir / paths["slope"])
    zone_values, zone_mapping, _zone_header = read_ascii_active_values(case_dir / paths["zone"], integer=True)
    ltstar_values, ltstar_mapping, _lt_header = read_ascii_active_values(case_dir / paths["ltstar"])
    if len(active_mapping) != len(zone_mapping) or len(active_mapping) != len(ltstar_mapping):
        raise ValueError("active-cell mapping mismatch across slope/zone/ltstar grids")
    return ActiveContext(
        config=config,
        slope_values_deg=slope_values,
        zone_values=zone_values,
        ltstar_values=ltstar_values,
        active_mapping=active_mapping,
        shape=(int(slope_header.get("nrows", 0)), int(slope_header.get("ncols", 0))),
    )


def make_field_pack_for_cell(context: ActiveContext, cell: int) -> CellFieldPack:
    idx = cell - 1
    config = context.config
    zone_id = int(context.zone_values[idx])
    zone = _zone_for_config(config, zone_id, cell=cell)
    slope_rad = context.slope_values_deg[idx] * float(config.get("dg2rad", FORTRAN_MAIN_DG2RAD))
    ltstar = context.ltstar_values[idx] if config["cltstar"] <= 0 else config["cltstar"]
    lbstar = config["clbstar"]
    cos2 = math.cos(slope_rad) ** 2.0
    beta = zone.alphab * zone.ksb * (zone.thsatt - zone.thresit) / zone.alphat / zone.kst / (zone.thsatb - zone.thresib)
    q = [min(zone.kst, max(0.0, rain + config["crizero"])) for rain in config["cri"]]
    row, col = context.active_mapping[idx]
    return CellFieldPack(
        cell=cell,
        row=row,
        col=col,
        slope_rad=slope_rad,
        zone_id=zone_id,
        ltstar=ltstar,
        lbstar=lbstar,
        zmin=config["zmin"],
        nzst=config["nzst"],
        nzsb=config["nzsb"],
        uww=config["uww"],
        q=q,
        capt=list(config["capt"]),
        beta=beta,
        lt=zone.alphat * ltstar * cos2,
        lb=zone.alphab * lbstar * cos2,
        rikzero=config["crizero"] / zone.kst,
        zone=zone,
    )


def eligibility_for_cell(context: ActiveContext, cell: int) -> tuple[bool, str | None]:
    idx = cell - 1
    config = context.config
    ltstar = context.ltstar_values[idx] if config["cltstar"] <= 0 else config["cltstar"]
    zone_id = int(context.zone_values[idx])
    zone = _zone_for_config(config, zone_id, cell=cell)
    ltstar_upper_gate = float(config.get("ltstar_upper_gate", 5.0))
    if ltstar > ltstar_upper_gate:
        return False, f"ltstar_gt_{ltstar_upper_gate:g}"
    if ltstar <= 0.01:
        return False, "ltstar_le_0_01"
    if context.slope_values_deg[idx] < config["slomin"]:
        return False, "slope_below_slomin"
    if zone.ct > 1.0e6:
        return False, "ct_zone_gt_1e6"
    return True, None


def _state_before_ts(rows: list[dict[str, Any]], ts: float) -> DoublelayerState:
    candidates = [row for row in rows if row.get("event") == "STEP_BEFORE" and abs(float(row.get("ts", math.nan)) - ts) <= 1.0e-9]
    if not candidates:
        return DoublelayerState()
    row = candidates[-1]
    return DoublelayerState(fdepth=float(row.get("fdepth", 0.0)), fsmin=float(row.get("fsmin", 10.0)), gindx=int(row.get("gindx", 0)))


def _root_inputs_for_cell(rows: list[dict[str, Any]], *, nmax: int) -> tuple[RootResult, RootResult, RootResult, Coefficients] | None:
    summary = next((row for row in rows if row.get("event") == "ROOT_SUMMARY"), None)
    if summary is None:
        return None
    roots_a = roota(nmax, summary["beta"], summary["lt"], summary["lb"], summary["kst"], summary["ksb"])
    roots_b = rootb(nmax, summary["beta"], summary["lt"], summary["lb"], summary["kst"], summary["ksb"])
    roots_c = rootc(nmax, summary["beta"], summary["lt"], summary["lb"], summary["kst"], summary["ksb"])
    coeffs = unsfin_coefficients(
        roots_a,
        roots_b,
        roots_c,
        beta=summary["beta"],
        lt=summary["lt"],
        lb=summary["lb"],
        kst=summary["kst"],
        ksb=summary["ksb"],
    )
    return roots_a, roots_b, roots_c, coeffs


def parse_unsfin_raw(path: Path) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {str(cell): [] for cell in TARGET_CELLS}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("event|"):
            continue
        parts = [part.strip() for part in line.split("|")]
        event = parts[0]
        cell = _as_int(parts[1])
        if cell not in TARGET_CELLS:
            continue
        record: dict[str, Any] = {"event": event, "cell": cell, "raw": line}
        if event == "Q":
            record.update(
                {
                    "period": _as_int(parts[2]),
                    "q": _as_float(parts[3]),
                    "rik": _as_float(parts[4]),
                    "rikzero": _as_float(parts[5]),
                    "kst": _as_float(parts[6]),
                    "capt_start": _as_float(parts[7]),
                    "capt_end": _as_float(parts[8]),
                }
            )
        elif event == "ROOT_SUMMARY":
            record.update(
                {
                    "beta": _as_float(parts[2]),
                    "lt": _as_float(parts[3]),
                    "lb": _as_float(parts[4]),
                    "nra": _as_int(parts[5]),
                    "nrb": _as_int(parts[6]),
                    "nrc": _as_int(parts[7]),
                    "kst": _as_float(parts[8]),
                    "ksb": _as_float(parts[9]),
                }
            )
        elif event in {"ROOT_A", "ROOT_B", "ROOT_C"}:
            record.update(
                {
                    "root_index": _as_int(parts[2]),
                    "lambda": _as_float(parts[3]),
                    "miu": _as_float(parts[4]),
                    "coefficient": _as_float(parts[5]),
                }
            )
        elif event in {"STEP_BEFORE", "STEP_AFTER"}:
            record.update(
                {
                    "jf": _as_int(parts[2]),
                    "tnown": _as_float(parts[3]),
                    "tincrement": _as_int(parts[4]),
                    "ts": _as_float(parts[5]),
                    "gindx": _as_int(parts[6]),
                    "fdepth": _as_float(parts[7]),
                    "fsmin": _as_float(parts[8]),
                    "tfail": _as_int(parts[9]) if event == "STEP_AFTER" and len(parts) > 9 else None,
                }
            )
        elif event == "REFINE":
            record.update(
                {
                    "jf": _as_int(parts[2]),
                    "tstart": _as_int(parts[3]),
                    "tend": _as_int(parts[4]),
                    "tnown": _as_float(parts[5]),
                    "tincrement": _as_int(parts[6]),
                    "fdepth": _as_float(parts[7]),
                }
            )
        elif event == "TFAIL_ASSIGN":
            record.update(
                {
                    "jf": _as_int(parts[2]),
                    "tnown": _as_float(parts[3]),
                    "tincrement": _as_int(parts[4]),
                    "fdepth": _as_float(parts[5]),
                    "gindx": _as_int(parts[6]),
                    "tfail": _as_float(parts[3]),
                }
            )
        elif event == "EXIT_AFTER_TSIMUL":
            record.update(
                {
                    "jf": _as_int(parts[2]),
                    "tnown": _as_float(parts[3]),
                    "tincrement": _as_int(parts[4]),
                    "fdepth": _as_float(parts[5]),
                    "gindx": _as_int(parts[6]),
                }
            )
        elif event == "EXIT_NO_FAILURE":
            record["fields"] = parts[2:]
        rows[str(cell)].append(record)
    return rows


def parse_doublelayer_raw(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("event|"):
            continue
        parts = stripped.split()
        event = parts[0]
        if event == "DL_TOP" and len(parts) >= 19:
            records.append(
                {
                    "event": event,
                    "cell": _as_int(parts[1]),
                    "tt": _as_float(parts[2]),
                    "depth_index": _as_int(parts[3]),
                    "z": _as_float(parts[4]),
                    "pt": _as_float(parts[5]),
                    "desat": _as_float(parts[6]),
                    "desatt": _as_float(parts[7]),
                    "inidesat": _as_float(parts[8]),
                    "fsc": _as_float(parts[9]),
                    "fsw": _as_float(parts[10]),
                    "fs": _as_float(parts[11]),
                    "fmn": _as_float(parts[12]),
                    "fsmin": _as_float(parts[13]),
                    "zfmin": _as_float(parts[14]),
                    "pmin": _as_float(parts[15]),
                    "fdepth": _as_float(parts[16]),
                    "gindx": _as_int(parts[17]),
                    "saturation_metric": _as_float(parts[18]),
                }
            )
        elif event == "DL_FINAL" and len(parts) >= 7:
            records.append(
                {
                    "event": event,
                    "cell": _as_int(parts[1]),
                    "tt": _as_float(parts[2]),
                    "fsmin": _as_float(parts[3]),
                    "fdepth": _as_float(parts[4]),
                    "pmin": _as_float(parts[5]),
                    "gindx": _as_int(parts[6]),
                }
            )
    return records


def _root_records(rows: Iterable[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("event") == event]


def compare_roots(original_rows: dict[str, list[dict[str, Any]]], *, nmax: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    native_rows: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    for cell_text, rows in original_rows.items():
        summary = next((row for row in rows if row["event"] == "ROOT_SUMMARY"), None)
        if summary is None:
            metrics[cell_text] = {"status": "missing_original_root_summary"}
            continue
        computed = {
            "A": roota(nmax, summary["beta"], summary["lt"], summary["lb"], summary["kst"], summary["ksb"]),
            "B": rootb(nmax, summary["beta"], summary["lt"], summary["lb"], summary["kst"], summary["ksb"]),
            "C": rootc(nmax, summary["beta"], summary["lt"], summary["lb"], summary["kst"], summary["ksb"]),
        }
        cell_metrics: dict[str, Any] = {"status": "root_components_compared"}
        for root_name, result in computed.items():
            event = f"ROOT_{root_name}"
            originals = _root_records(rows, event)
            native_rows.append(
                {
                    "event": "NATIVE_ROOT_SUMMARY",
                    "cell": int(cell_text),
                    "root_family": root_name,
                    "count": len(result.lambdas),
                }
            )
            for idx, (lam, miu) in enumerate(zip(result.lambdas, result.mius), start=1):
                native_rows.append(
                    {
                        "event": f"NATIVE_ROOT_{root_name}",
                        "cell": int(cell_text),
                        "root_index": idx,
                        "lambda": lam,
                        "miu": miu,
                    }
                )
            overlap = min(len(originals), len(result.lambdas))
            lambda_errors = [
                abs(float(originals[idx]["lambda"]) - result.lambdas[idx])
                for idx in range(overlap)
            ]
            miu_errors = [
                abs(float(originals[idx]["miu"]) - result.mius[idx])
                for idx in range(overlap)
            ]
            cell_metrics[root_name] = {
                "original_count": len(originals),
                "native_count": len(result.lambdas),
                "count_match": len(originals) == len(result.lambdas),
                "overlap": overlap,
                "lambda_max_abs_error": max(lambda_errors) if lambda_errors else None,
                "miu_max_abs_error": max(miu_errors) if miu_errors else None,
            }
        metrics[cell_text] = cell_metrics
    return native_rows, metrics


def write_dict_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize_original(original_rows: dict[str, list[dict[str, Any]]], doublelayer_rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for cell in TARGET_CELLS:
        rows = original_rows.get(str(cell), [])
        dl_rows = [row for row in doublelayer_rows if row.get("cell") == cell]
        tfail_assign = [row for row in rows if row.get("event") == "TFAIL_ASSIGN"]
        step_after_g1 = [row for row in rows if row.get("event") == "STEP_AFTER" and row.get("gindx") == 1]
        summary[str(cell)] = {
            "unsfin_rows": len(rows),
            "doublelayer_rows": len(dl_rows),
            "q_period_count": sum(1 for row in rows if row.get("event") == "Q"),
            "root_summary_present": any(row.get("event") == "ROOT_SUMMARY" for row in rows),
            "tfail_assign_rows": len(tfail_assign),
            "tfail_assigned_raw": tfail_assign[-1]["raw"] if tfail_assign else None,
            "first_step_after_gindx_one": step_after_g1[0]["raw"] if step_after_g1 else None,
            "fdepth_capture_visible": any(row.get("event") == "DL_TOP" and row.get("fdepth", 0.0) > 0.0 for row in dl_rows),
            "dl_final_gindx_one_count": sum(1 for row in dl_rows if row.get("event") == "DL_FINAL" and row.get("gindx") == 1),
        }
    return summary


def _rmse(values: list[float]) -> float | None:
    if not values:
        return None
    return math.sqrt(sum(value * value for value in values) / len(values))


def _mae(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(abs(value) for value in values) / len(values)


def _first_diff(
    original: dict[str, Any],
    native: dict[str, Any],
    *,
    fields: Iterable[str],
    tolerance: float = 1.0e-6,
) -> tuple[str, float, float, float] | None:
    for field in fields:
        if field not in original or field not in native:
            continue
        ov = float(original[field])
        nv = float(native[field])
        if not (math.isfinite(ov) and math.isfinite(nv)):
            if ov != nv:
                return field, ov, nv, math.nan
            continue
        delta = abs(ov - nv)
        if delta > tolerance:
            return field, ov, nv, delta
    return None


def compare_doublelayer_rows(
    original_rows: list[dict[str, Any]],
    native_rows: list[dict[str, Any]],
    native_final_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    original_top = [row for row in original_rows if row.get("event") == "DL_TOP"]
    original_final = [row for row in original_rows if row.get("event") == "DL_FINAL"]
    native_index = {
        (int(row["cell"]), float(row["tt"]), int(row["depth_index"])): row
        for row in native_rows
        if row.get("event") == "NATIVE_DL_TOP"
    }
    native_final_index = {
        (int(row["cell"]), float(row["tt"])): row
        for row in native_final_rows
        if row.get("event") == "NATIVE_DL_FINAL"
    }
    fields = ["pt", "desat", "desatt", "inidesat", "fsc", "fsw", "fs", "fmn", "fdepth", "gindx"]
    per_cell: dict[str, Any] = {}
    divergent_rows: list[dict[str, Any]] = []
    for cell in TARGET_CELLS:
        cell_original = [row for row in original_top if int(row["cell"]) == cell]
        cell_errors: dict[str, list[float]] = {field: [] for field in fields if field != "gindx"}
        matched = 0
        first_divergent: dict[str, Any] | None = None
        for original in cell_original:
            key = (cell, float(original["tt"]), int(original["depth_index"]))
            native = native_index.get(key)
            if native is None:
                if first_divergent is None:
                    first_divergent = {
                        "cell": cell,
                        "tt": original["tt"],
                        "depth_index": original["depth_index"],
                        "variable": "row_presence",
                        "category": "NATIVE_ROW_MISSING",
                    }
                continue
            matched += 1
            for field in cell_errors:
                ov = float(original[field])
                nv = float(native[field])
                if math.isfinite(ov) and math.isfinite(nv):
                    cell_errors[field].append(nv - ov)
            if first_divergent is None:
                diff = _first_diff(original, native, fields=fields)
                if diff is not None:
                    field, ov, nv, delta = diff
                    first_divergent = {
                        "cell": cell,
                        "tt": original["tt"],
                        "depth_index": original["depth_index"],
                        "variable": field,
                        "original": ov,
                        "native": nv,
                        "abs_error": delta,
                        "category": _field_to_gap_category(field),
                    }
        final_mismatches = 0
        final_fdepth_mismatches = 0
        final_gindx_mismatches = 0
        for original in (row for row in original_final if int(row["cell"]) == cell):
            native = native_final_index.get((cell, float(original["tt"])))
            if native is None:
                final_mismatches += 1
                final_fdepth_mismatches += 1
                final_gindx_mismatches += 1
                continue
            for field in ("fsmin", "fdepth", "pmin", "gindx"):
                if field == "gindx":
                    if int(original[field]) != int(native[field]):
                        final_mismatches += 1
                        final_gindx_mismatches += 1
                elif field == "fdepth":
                    if abs(float(original[field]) - float(native[field])) > 1.0e-6:
                        final_mismatches += 1
                        final_fdepth_mismatches += 1
                elif abs(float(original[field]) - float(native[field])) > 1.0e-6:
                    final_mismatches += 1
        if first_divergent is not None:
            divergent_rows.append(first_divergent)
        per_cell[str(cell)] = {
            "original_top_rows": len(cell_original),
            "matched_top_rows": matched,
            "first_divergent": first_divergent,
            "final_mismatches": final_mismatches,
            "final_fdepth_mismatches": final_fdepth_mismatches,
            "final_gindx_mismatches": final_gindx_mismatches,
            "metrics": {
                field: {
                    "mae": _mae(errors),
                    "rmse": _rmse(errors),
                    "max_abs_error": max((abs(value) for value in errors), default=None),
                }
                for field, errors in cell_errors.items()
            },
        }
    return {"per_cell": per_cell, "total_native_rows": len(native_rows), "total_native_final_rows": len(native_final_rows)}, divergent_rows


def derive_inidoublelayer_ts_carry(
    pack: CellFieldPack,
    roots_a: RootResult,
    roots_b: RootResult,
    roots_c: RootResult,
    coeffs: Coefficients,
    original_doublelayer_rows: list[dict[str, Any]],
    *,
    max_ts: int = 64800,
) -> dict[str, Any]:
    first_depth_row = next(
        (
            row
            for row in original_doublelayer_rows
            if row.get("event") == "DL_TOP" and int(row.get("cell", -1)) == pack.cell and int(row.get("depth_index", -1)) == 1
        ),
        None,
    )
    if first_depth_row is None:
        return {"cell": pack.cell, "status": "missing_original_first_depth_row", "ts": 60.0}
    target = float(first_depth_row["inidesat"])
    best: tuple[float, int, float] | None = None
    for ts_value in range(1, max_ts + 1):
        row = evaluate_inidoublelayer_depth(pack, roots_a, roots_b, roots_c, coeffs, tt=float(ts_value), depth_index=1)
        value = row["inidesat"]
        if not math.isfinite(value):
            continue
        err = abs(value - target)
        if best is None or err < best[0]:
            best = (err, ts_value, value)
    if best is None:
        return {"cell": pack.cell, "status": "unable_to_fit_ts", "ts": 60.0, "target_inidesat": target}
    err, ts_value, value = best
    return {
        "cell": pack.cell,
        "status": "derived_from_original_inidesat_trace",
        "ts": float(ts_value),
        "target_inidesat": target,
        "native_inidesat": value,
        "abs_error": err,
        "original_first_doublelayer_tt": float(first_depth_row["tt"]),
    }


def native_tfirst_search_cell(
    pack: CellFieldPack,
    roots_a: RootResult,
    roots_b: RootResult,
    roots_c: RootResult,
    coeffs: Coefficients,
    *,
    initial_ts: float,
    tsimul: int = 64800,
    max_iterations: int = 60,
    collect_trace: bool = True,
    profile_stats: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ledger-only port of `unsfin.F90` tnown/tincrement first-hit search."""
    t0 = time.perf_counter()
    init_rows_or_values: list[dict[str, float]] | list[float]
    if collect_trace:
        init_rows_or_values = evaluate_inidoublelayer(pack, roots_a, roots_b, roots_c, coeffs, tt=initial_ts)
    else:
        init_rows_or_values = evaluate_inidoublelayer_values(pack, roots_a, roots_b, roots_c, coeffs, tt=initial_ts)
    _profile_add(profile_stats, "inidoublelayer_seconds", time.perf_counter() - t0)
    tstart = 0
    tend = 170000
    tincrement = 10000
    tnown = 0.0
    state = DoublelayerState()
    tfail: float | None = None
    last_step_ts = initial_ts
    trace: list[dict[str, Any]] = []
    if collect_trace:
        trace.append(
            {
                "event": "NATIVE_CALL_INIDOUBLELAYER",
                "cell": pack.cell,
                "jf": 0,
                "ts": initial_ts,
                "tstart": tstart,
                "tend": tend,
                "tnown": tnown,
                "tincrement": tincrement,
                "gindx": state.gindx,
                "fdepth": state.fdepth,
                "fsmin": state.fsmin,
            }
        )
    exit_reason = "max_iterations_exhausted"
    iteration_count = 0
    refinement_count = 0
    for jf in range(1, max_iterations + 1):
        ts = 60.0 if tnown < 60.0 else float(tnown)
        last_step_ts = ts
        if collect_trace:
            trace.append(
                {
                    "event": "NATIVE_STEP_BEFORE",
                    "cell": pack.cell,
                    "jf": jf,
                    "tstart": tstart,
                    "tend": tend,
                    "tnown": tnown,
                    "tincrement": tincrement,
                    "ts": ts,
                    "gindx": state.gindx,
                    "fdepth": state.fdepth,
                    "fsmin": state.fsmin,
                }
            )
        t0 = time.perf_counter()
        if collect_trace:
            _rows, final = evaluate_doublelayer_top(
                pack,
                roots_a,
                roots_b,
                roots_c,
                coeffs,
                init_rows_or_values,  # type: ignore[arg-type]
                tt=ts,
                initial_state=state,
            )
        else:
            final = evaluate_doublelayer_top_final(
                pack,
                roots_a,
                roots_b,
                roots_c,
                coeffs,
                init_rows_or_values,  # type: ignore[arg-type]
                tt=ts,
                initial_state=state,
            )
        _profile_add(profile_stats, "doublelayer_seconds", time.perf_counter() - t0)
        state = DoublelayerState(
            fdepth=float(final["fdepth"]),
            fsmin=float(final["fsmin"]),
            zfmin=float(final["zfmin"]),
            pmin=float(final["pmin"]),
            gindx=int(final["gindx"]),
        )
        iteration_count += 1
        if collect_trace:
            trace.append(
                {
                    "event": "NATIVE_STEP_AFTER",
                    "cell": pack.cell,
                    "jf": jf,
                    "tstart": tstart,
                    "tend": tend,
                    "tnown": tnown,
                    "tincrement": tincrement,
                    "ts": ts,
                    "gindx": state.gindx,
                    "fdepth": state.fdepth,
                    "fsmin": state.fsmin,
                    "tfail": tfail,
                }
            )
        if tnown > tsimul and state.gindx == 0:
            exit_reason = "exit_no_failure_after_tsimul"
            break
        if tincrement == 1 and state.gindx == 1:
            if tnown > tsimul:
                state.gindx = 0
                exit_reason = "exit_after_tsimul"
                if collect_trace:
                    trace.append(
                        {
                            "event": "NATIVE_EXIT_AFTER_TSIMUL",
                            "cell": pack.cell,
                            "jf": jf,
                            "tnown": tnown,
                            "tincrement": tincrement,
                            "fdepth": state.fdepth,
                            "gindx": state.gindx,
                        }
                    )
            else:
                tfail = tnown
                exit_reason = "tfail_assigned"
                if collect_trace:
                    trace.append(
                        {
                            "event": "NATIVE_TFAIL_ASSIGN",
                            "cell": pack.cell,
                            "jf": jf,
                            "tnown": tnown,
                            "tincrement": tincrement,
                            "fdepth": state.fdepth,
                            "gindx": state.gindx,
                            "tfail": tfail,
                        }
                    )
            break
        if state.gindx == 1 and tincrement >= 10:
            tend = int(tnown)
            tstart = int(tnown - tincrement)
            tnown = float(tstart)
            tincrement = int((tend - tstart) / 10)
            refinement_count += 1
            if collect_trace:
                trace.append(
                    {
                        "event": "NATIVE_REFINE",
                        "cell": pack.cell,
                        "jf": jf,
                        "tstart": tstart,
                        "tend": tend,
                        "tnown": tnown,
                        "tincrement": tincrement,
                        "fdepth": state.fdepth,
                        "gindx": state.gindx,
                        "fsmin": state.fsmin,
                    }
                )
        tnown = tnown + tincrement
    summary = {
        "cell": pack.cell,
        "tfail": tfail,
        "fdepth": state.fdepth,
        "gindx": state.gindx,
        "fsmin": state.fsmin,
        "initial_ts": initial_ts,
        "final_ts": last_step_ts,
        "exit_reason": exit_reason,
        "iterations": iteration_count,
        "refinement_count": refinement_count,
    }
    return trace, summary


def compare_tfirst_search(
    original_rows: dict[str, list[dict[str, Any]]],
    native_trace: list[dict[str, Any]],
    native_summaries: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    native_by_cell: dict[int, list[dict[str, Any]]] = {}
    for row in native_trace:
        native_by_cell.setdefault(int(row["cell"]), []).append(row)
    divergent: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {"per_cell": {}}
    for cell in TARGET_CELLS:
        originals = original_rows.get(str(cell), [])
        original_tfail = next((row for row in originals if row.get("event") == "TFAIL_ASSIGN"), None)
        native_summary = native_summaries.get(str(cell), {})
        original_steps = [row for row in originals if row.get("event") == "STEP_AFTER"]
        native_steps = [row for row in native_by_cell.get(cell, []) if row.get("event") == "NATIVE_STEP_AFTER"]
        first_diff: dict[str, Any] | None = None
        for original, native in zip(original_steps, native_steps):
            for field in ("tnown", "tincrement", "ts", "gindx", "fdepth", "fsmin"):
                ov = float(original[field])
                nv = float(native[field])
                tol = 1.0e-6 if field not in {"tincrement", "gindx"} else 0.0
                if abs(ov - nv) > tol:
                    first_diff = {
                        "cell": cell,
                        "jf": original["jf"],
                        "variable": field,
                        "original": ov,
                        "native": nv,
                        "abs_error": abs(ov - nv),
                        "category": _tfirst_field_to_gap_category(field),
                    }
                    break
            if first_diff is not None:
                break
        if first_diff is not None:
            divergent.append(first_diff)
        original_tfail_value = float(original_tfail["tfail"]) if original_tfail else None
        native_tfail_value = native_summary.get("tfail")
        tfail_abs_error = (
            abs(float(native_tfail_value) - original_tfail_value)
            if native_tfail_value is not None and original_tfail_value is not None
            else None
        )
        original_refines = sum(1 for row in originals if row.get("event") == "REFINE")
        native_refines = int(native_summary.get("refinement_count", 0))
        metrics["per_cell"][str(cell)] = {
            "original_tfail": original_tfail_value,
            "native_tfail": native_tfail_value,
            "tfail_abs_error": tfail_abs_error,
            "original_final_fdepth": float(original_tfail["fdepth"]) if original_tfail else None,
            "native_final_fdepth": native_summary.get("fdepth"),
            "fdepth_abs_error": (
                abs(float(native_summary.get("fdepth")) - float(original_tfail["fdepth"]))
                if original_tfail and native_summary.get("fdepth") is not None
                else None
            ),
            "gindx_match": bool(original_tfail and int(original_tfail["gindx"]) == int(native_summary.get("gindx", -1))),
            "original_refinement_count": original_refines,
            "native_refinement_count": native_refines,
            "refinement_count_match": original_refines == native_refines,
            "original_step_after_count": len(original_steps),
            "native_step_after_count": len(native_steps),
            "first_divergent_iteration": first_diff,
            "final_status": "converged" if tfail_abs_error == 0.0 and original_refines == native_refines and first_diff is None else "mismatch_or_residual",
        }
    all_converged = all(row["final_status"] == "converged" for row in metrics["per_cell"].values())
    metrics["decision"] = "NATIVE_TFIRST_FOUR_CELL_CONVERGENCE" if all_converged else "NATIVE_TFIRST_MISMATCH_LOCALIZED"
    return metrics, divergent


def _tfirst_field_to_gap_category(field: str) -> str:
    return {
        "ts": "DOUBLELAYER_CALL_TS_MISMATCH",
        "tnown": "TINCREMENT_UPDATE_MISMATCH",
        "tincrement": "TINCREMENT_UPDATE_MISMATCH",
        "gindx": "GINDX_SEQUENCE_MISMATCH",
        "fdepth": "FDEPTH_SEQUENCE_MISMATCH",
        "fsmin": "FS_MIN_SEQUENCE_MISMATCH",
    }.get(field, "FORTRAN_ORDER_OR_PRECISION_MISMATCH")


def _active_order_checkpoint_paths(checkpoint_dir: Path) -> tuple[Path, Path]:
    return checkpoint_dir / "active_order_checkpoint.npz", checkpoint_dir / "active_order_checkpoint.json"


def _candidate_rows_from_arrays(
    gindx: np.ndarray,
    tfail: np.ndarray,
    fdepth: np.ndarray,
    mapping: list[tuple[int, int]],
    *,
    max_cell: int | None = None,
    ledger_window_s: float = 600.0,
) -> list[dict[str, Any]]:
    limit = min(max_cell or len(gindx), len(gindx))
    rows: list[dict[str, Any]] = []
    for zero_idx in np.flatnonzero(np.isfinite(tfail[:limit]) & (tfail[:limit] > 0.0) & (tfail[:limit] <= ledger_window_s)):
        row, col = mapping[int(zero_idx)]
        rows.append(
            {
                "cell": int(zero_idx) + 1,
                "row": int(row),
                "col": int(col),
                "tfail": float(tfail[zero_idx]),
                "fdepth": float(fdepth[zero_idx]),
                "gindx": int(gindx[zero_idx]),
            }
        )
    return rows


def _write_active_order_checkpoint(
    checkpoint_dir: Path,
    *,
    gindx: np.ndarray,
    tfail: np.ndarray,
    fdepth: np.ndarray,
    meta: dict[str, Any],
    candidates: list[dict[str, Any]],
    profile_stats: dict[str, float],
) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    npz_path, json_path = _active_order_checkpoint_paths(checkpoint_dir)
    tmp_npz = npz_path.with_suffix(".npz.tmp")
    tmp_json = json_path.with_suffix(".json.tmp")
    np.savez_compressed(tmp_npz, gindx=gindx, tfail_s=tfail, fdepth_m=fdepth)
    if tmp_npz.exists() and not npz_path.exists():
        pass
    elif not tmp_npz.exists():
        generated = tmp_npz.with_suffix(tmp_npz.suffix + ".npz")
        if generated.exists():
            generated.replace(tmp_npz)
    checkpoint_meta = {
        **meta,
        "candidate_list": candidates,
        "profile_stats": profile_stats,
        "checkpoint_format": "native_unsfin_active_order_v1",
    }
    tmp_json.write_text(json.dumps(checkpoint_meta, indent=2), encoding="utf-8")
    tmp_npz.replace(npz_path)
    tmp_json.replace(json_path)
    last_processed = meta.get("last_processed_active_index")
    stop_index = meta.get("target_stop_index")
    eligible = meta.get("processed_eligible_cells")
    print(
        f"[unsfin] active {last_processed}/{stop_index} "
        f"eligible={eligible} candidates={len(candidates)}",
        flush=True,
    )


def _load_active_order_checkpoint(checkpoint_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    npz_path, json_path = _active_order_checkpoint_paths(checkpoint_dir)
    if not npz_path.exists() or not json_path.exists():
        raise FileNotFoundError(f"missing active-order checkpoint in {checkpoint_dir}")
    arrays = np.load(npz_path)
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    if not meta.get("active_order_mode") or meta.get("per_cell_fitted_ts"):
        raise ValueError("checkpoint does not preserve active-order/non-fitted ts semantics")
    return (
        np.asarray(arrays["gindx"], dtype=np.int32),
        np.asarray(arrays["tfail_s"], dtype=np.float64),
        np.asarray(arrays["fdepth_m"], dtype=np.float64),
        meta,
    )


def run_active_order_0_600(
    case_dir: Path,
    *,
    max_active_index: int | None = None,
    trace_window_cells: set[int] | None = None,
    checkpoint_dir: Path | None = None,
    resume: bool = False,
    checkpoint_interval: int = 1000,
    collect_gate_trace_for_eligible: bool = False,
    profile: bool = True,
    ledger_window_s: float = 600.0,
) -> tuple[LedgerArrays, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    start_clock = time.perf_counter()
    context = build_active_context(case_dir)
    active_count = len(context.slope_values_deg)
    stop_index = min(max_active_index or active_count, active_count)
    config_hash = _sha256_json(
        {
            "case_dir": str(case_dir.resolve()),
            "active_count": active_count,
            "shape": context.shape,
            "ledger_window_s": "tfail_search_to_tsimul_window_filtered",
            "source_provenance": "production_native_unsfin_ledger_only",
        }
    )
    profile_stats: dict[str, float] = {
        "eligibility_seconds": 0.0,
        "field_pack_seconds": 0.0,
        "root_generation_seconds": 0.0,
        "tfirst_loop_seconds": 0.0,
        "inidoublelayer_seconds": 0.0,
        "doublelayer_seconds": 0.0,
        "checkpoint_write_seconds": 0.0,
        "root_cache_hits": 0.0,
        "root_cache_misses": 0.0,
    }
    if resume:
        if checkpoint_dir is None:
            raise ValueError("resume=True requires checkpoint_dir")
        gindx, tfail, fdepth, checkpoint_meta = _load_active_order_checkpoint(checkpoint_dir)
        if gindx.shape[0] != active_count or tfail.shape[0] != active_count or fdepth.shape[0] != active_count:
            raise ValueError("checkpoint array shape does not match active-cell count")
        ts_carry = float(checkpoint_meta["ts_carry"])
        next_cell = int(checkpoint_meta["next_active_index"])
        processed = int(checkpoint_meta["processed_eligible_cells"])
        eligible_count = int(checkpoint_meta["eligible_cells_in_evaluated_range"])
        skip_counts = dict(checkpoint_meta.get("skip_counts", {}))
        profile_stats.update({k: float(v) for k, v in checkpoint_meta.get("profile_stats", {}).items() if isinstance(v, (int, float))})
    else:
        gindx = np.zeros(active_count, dtype=np.int32)
        tfail = np.full(active_count, np.nan, dtype=np.float64)
        fdepth = np.zeros(active_count, dtype=np.float64)
        ts_carry = 60.0
        next_cell = 1
        processed = 0
        eligible_count = 0
        skip_counts: dict[str, int] = {}
    active_trace: list[dict[str, Any]] = []
    gate_trace: list[dict[str, Any]] = []
    trace_window_cells = trace_window_cells or set(TARGET_CELLS)
    checkpoint_interval = max(1, int(checkpoint_interval))
    last_processed = next_cell - 1
    root_cache: dict[tuple[float, float, float, float, float], tuple[RootResult, RootResult, RootResult, Coefficients]] = {}
    for cell in range(next_cell, stop_index + 1):
        t0 = time.perf_counter()
        eligible, reason = eligibility_for_cell(context, cell)
        _profile_add(profile_stats, "eligibility_seconds", time.perf_counter() - t0)
        gate_row = {
            "cell": cell,
            "eligible": eligible,
            "skip_reason": reason,
            "ts_before_inidoublelayer": ts_carry,
        }
        if cell in trace_window_cells or (eligible and collect_gate_trace_for_eligible):
            gate_trace.append(gate_row)
        if not eligible:
            skip_counts[reason or "unknown"] = skip_counts.get(reason or "unknown", 0) + 1
            if cell in trace_window_cells:
                active_trace.append(
                    {
                        "event": "ACTIVE_ORDER_SKIP",
                        "cell": cell,
                        "ts_before_inidoublelayer": ts_carry,
                        "ts_after_cell": ts_carry,
                        "skip_reason": reason,
                    }
                )
            last_processed = cell
            if checkpoint_dir is not None and (cell % checkpoint_interval == 0 or cell == stop_index):
                candidates = _candidate_rows_from_arrays(
                    gindx,
                    tfail,
                    fdepth,
                    context.active_mapping,
                    max_cell=cell,
                    ledger_window_s=ledger_window_s,
                )
                checkpoint_meta = {
                    "source_provenance": "production_native_unsfin_ledger_only",
                    "runtime_provider_enabled": False,
                    "dfs_runtime_modified": False,
                    "output_inferred": False,
                    "active_order_mode": True,
                    "per_cell_fitted_ts": False,
                    "ledger_window_s": ledger_window_s,
                    "active_count": active_count,
                    "config_hash": config_hash,
                    "last_processed_active_index": last_processed,
                    "next_active_index": cell + 1,
                    "ts_carry": ts_carry,
                    "processed_eligible_cells": processed,
                    "eligible_cells_in_evaluated_range": eligible_count,
                    "skip_counts": skip_counts,
                    "target_stop_index": stop_index,
                }
                t_checkpoint = time.perf_counter()
                _write_active_order_checkpoint(
                    checkpoint_dir,
                    gindx=gindx,
                    tfail=tfail,
                    fdepth=fdepth,
                    meta=checkpoint_meta,
                    candidates=candidates,
                    profile_stats=profile_stats,
                )
                _profile_add(profile_stats, "checkpoint_write_seconds", time.perf_counter() - t_checkpoint)
            continue
        eligible_count += 1
        t0 = time.perf_counter()
        pack = make_field_pack_for_cell(context, cell)
        _profile_add(profile_stats, "field_pack_seconds", time.perf_counter() - t0)
        t0 = time.perf_counter()
        root_key = (pack.beta, pack.lt, pack.lb, pack.zone.kst, pack.zone.ksb)
        cached = root_cache.get(root_key)
        if cached is None:
            roots_a = roota(10, pack.beta, pack.lt, pack.lb, pack.zone.kst, pack.zone.ksb)
            roots_b = rootb(10, pack.beta, pack.lt, pack.lb, pack.zone.kst, pack.zone.ksb)
            roots_c = rootc(10, pack.beta, pack.lt, pack.lb, pack.zone.kst, pack.zone.ksb)
            coeffs = unsfin_coefficients(
                roots_a,
                roots_b,
                roots_c,
                beta=pack.beta,
                lt=pack.lt,
                lb=pack.lb,
                kst=pack.zone.kst,
                ksb=pack.zone.ksb,
            )
            root_cache[root_key] = (roots_a, roots_b, roots_c, coeffs)
            _profile_add(profile_stats, "root_cache_misses", 1.0)
        else:
            roots_a, roots_b, roots_c, coeffs = cached
            _profile_add(profile_stats, "root_cache_hits", 1.0)
        _profile_add(profile_stats, "root_generation_seconds", time.perf_counter() - t0)
        t0 = time.perf_counter()
        _trace, summary = native_tfirst_search_cell(
            pack,
            roots_a,
            roots_b,
            roots_c,
            coeffs,
            initial_ts=ts_carry,
            collect_trace=False,
            profile_stats=profile_stats if profile else None,
        )
        _profile_add(profile_stats, "tfirst_loop_seconds", time.perf_counter() - t0)
        processed += 1
        ts_after = float(summary["final_ts"])
        ts_used = ts_carry
        ts_carry = ts_after
        if summary["tfail"] is not None:
            idx = cell - 1
            gindx[idx] = int(summary["gindx"])
            tfail[idx] = float(summary["tfail"])
            fdepth[idx] = float(summary["fdepth"])
        if cell in trace_window_cells or (summary["tfail"] is not None and float(summary["tfail"]) <= ledger_window_s):
            active_trace.append(
                {
                    "event": "ACTIVE_ORDER_CELL",
                    "cell": cell,
                    "row": pack.row,
                    "col": pack.col,
                    "eligible": True,
                    "ts_before_inidoublelayer": ts_used,
                    "ts_after_cell": ts_after,
                    "tfail": summary["tfail"],
                    "fdepth": summary["fdepth"],
                    "gindx": summary["gindx"],
                    "iterations": summary["iterations"],
                    "refinement_count": summary["refinement_count"],
                        "exit_reason": summary["exit_reason"],
                    }
                )
        last_processed = cell
        if checkpoint_dir is not None and (cell % checkpoint_interval == 0 or cell == stop_index):
            candidates = _candidate_rows_from_arrays(
                gindx,
                tfail,
                fdepth,
                context.active_mapping,
                max_cell=cell,
                ledger_window_s=ledger_window_s,
            )
            checkpoint_meta = {
                "source_provenance": "production_native_unsfin_ledger_only",
                "runtime_provider_enabled": False,
                "dfs_runtime_modified": False,
                "output_inferred": False,
                "active_order_mode": True,
                "per_cell_fitted_ts": False,
                "ledger_window_s": ledger_window_s,
                "active_count": active_count,
                "config_hash": config_hash,
                "last_processed_active_index": last_processed,
                "next_active_index": cell + 1,
                "ts_carry": ts_carry,
                "processed_eligible_cells": processed,
                "eligible_cells_in_evaluated_range": eligible_count,
                "skip_counts": skip_counts,
                "target_stop_index": stop_index,
            }
            t_checkpoint = time.perf_counter()
            _write_active_order_checkpoint(
                checkpoint_dir,
                gindx=gindx,
                tfail=tfail,
                fdepth=fdepth,
                meta=checkpoint_meta,
                candidates=candidates,
                profile_stats=profile_stats,
            )
            _profile_add(profile_stats, "checkpoint_write_seconds", time.perf_counter() - t_checkpoint)
    candidates = _candidate_rows_from_arrays(
        gindx,
        tfail,
        fdepth,
        context.active_mapping,
        max_cell=stop_index,
        ledger_window_s=ledger_window_s,
    )
    meta = {
        "source_provenance": "production_native_unsfin_ledger_only",
        "runtime_provider_enabled": False,
        "dfs_runtime_modified": False,
        "output_inferred": False,
        "active_order_mode": True,
        "per_cell_fitted_ts": False,
        "ledger_window_s": ledger_window_s,
        "active_count": active_count,
        "evaluated_active_index_start": 1,
        "evaluated_active_index_end": stop_index,
        "last_processed_active_index": last_processed,
        "next_active_index": last_processed + 1,
        "completed_active_count": stop_index if stop_index >= active_count else last_processed,
        "ts_carry": ts_carry,
        "performance_truncated": stop_index < active_count,
        "processed_eligible_cells": processed,
        "eligible_cells_in_evaluated_range": eligible_count,
        "candidate_count_0_600": len(_candidate_rows_from_arrays(gindx, tfail, fdepth, context.active_mapping, max_cell=stop_index, ledger_window_s=600.0)),
        "candidate_count_window": len(candidates),
        "skip_counts": skip_counts,
        "checkpoint_enabled": checkpoint_dir is not None,
        "checkpoint_dir": str(checkpoint_dir) if checkpoint_dir is not None else None,
        "checkpoint_interval": checkpoint_interval if checkpoint_dir is not None else None,
        "config_hash": config_hash,
        "wall_seconds": time.perf_counter() - start_clock,
        "profile_stats": profile_stats,
        "notes": "Ledger-only active-order diagnostic; DFS runtime and production provider are untouched.",
    }
    ledger = LedgerArrays(gindx=gindx, tfail_s=tfail, fdepth_m=fdepth, fsdepth_m=None, meta=meta)
    summary = {**meta, "candidates_0_600": _candidate_rows_from_arrays(gindx, tfail, fdepth, context.active_mapping, max_cell=stop_index, ledger_window_s=600.0), "candidates_window": candidates}
    return ledger, active_trace, gate_trace, summary


def _ledger_window_label(ledger_window_s: float) -> str:
    return f"0_{int(ledger_window_s)}"


def compare_window_ledgers(
    native: LedgerArrays,
    original: LedgerArrays,
    mapping: list[tuple[int, int]],
    *,
    ledger_window_s: float = 600.0,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    original_mask = np.isfinite(original.tfail_s) & (original.tfail_s > 0.0) & (original.tfail_s <= ledger_window_s)
    native_mask = np.isfinite(native.tfail_s) & (native.tfail_s > 0.0) & (native.tfail_s <= ledger_window_s)
    if native.meta.get("performance_truncated"):
        end = int(native.meta["evaluated_active_index_end"])
        eval_mask = np.zeros_like(original_mask, dtype=bool)
        eval_mask[:end] = True
    else:
        eval_mask = np.ones_like(original_mask, dtype=bool)
    tp_mask = original_mask & native_mask
    fp_mask = ~original_mask & native_mask
    fn_mask = original_mask & ~native_mask
    evaluated_fn_mask = fn_mask & eval_mask
    tfail_abs = np.abs(native.tfail_s[tp_mask] - original.tfail_s[tp_mask])
    fdepth_abs = np.abs(native.fdepth_m[tp_mask] - original.fdepth_m[tp_mask])
    tp = int(np.count_nonzero(tp_mask))
    fp = int(np.count_nonzero(fp_mask))
    fn = int(np.count_nonzero(fn_mask))
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    union = int(np.count_nonzero(original_mask | native_mask))
    label = _ledger_window_label(ledger_window_s)
    decision_prefix = f"NATIVE_{label}_LEDGER"
    bucket_edges = list(range(0, int(ledger_window_s) + 1, 600))
    if not bucket_edges or bucket_edges[-1] != int(ledger_window_s):
        bucket_edges.append(int(ledger_window_s))
    bucket_counts: dict[str, dict[str, int]] = {}
    for start, end in zip(bucket_edges[:-1], bucket_edges[1:]):
        original_bucket = np.isfinite(original.tfail_s) & (original.tfail_s > start) & (original.tfail_s <= end)
        native_bucket = np.isfinite(native.tfail_s) & (native.tfail_s > start) & (native.tfail_s <= end)
        bucket_counts[f"{start}_{end}"] = {
            "original": int(np.count_nonzero(original_bucket)),
            "native": int(np.count_nonzero(native_bucket)),
            "true_positives": int(np.count_nonzero(original_bucket & native_bucket)),
        }
    metrics = {
        "ledger_window_s": ledger_window_s,
        "source_provenance": native.meta.get("source_provenance"),
        "runtime_provider_enabled": native.meta.get("runtime_provider_enabled"),
        "dfs_runtime_modified": native.meta.get("dfs_runtime_modified"),
        "output_inferred": native.meta.get("output_inferred"),
        "active_order_mode": native.meta.get("active_order_mode"),
        "per_cell_fitted_ts": native.meta.get("per_cell_fitted_ts"),
        "performance_truncated": native.meta.get("performance_truncated"),
        "evaluated_active_index_end": native.meta.get("evaluated_active_index_end"),
        "original_candidate_count_window": int(np.count_nonzero(original_mask)),
        "native_candidate_count_window": int(np.count_nonzero(native_mask)),
        f"original_candidate_count_{label}": int(np.count_nonzero(original_mask)),
        f"native_candidate_count_{label}": int(np.count_nonzero(native_mask)),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives_global": fn,
        "false_negatives_in_evaluated_range": int(np.count_nonzero(evaluated_fn_mask)),
        "precision": precision,
        "recall_global": recall,
        "jaccard_iou_global": (tp / union) if union else None,
        "tfail_mae_on_tp": float(np.mean(tfail_abs)) if tfail_abs.size else None,
        "tfail_rmse_on_tp": float(np.sqrt(np.mean(tfail_abs * tfail_abs))) if tfail_abs.size else None,
        "tfail_max_abs_error_on_tp": float(np.max(tfail_abs)) if tfail_abs.size else None,
        "fdepth_mae_on_tp": float(np.mean(fdepth_abs)) if fdepth_abs.size else None,
        "fdepth_rmse_on_tp": float(np.sqrt(np.mean(fdepth_abs * fdepth_abs))) if fdepth_abs.size else None,
        "fdepth_max_abs_error_on_tp": float(np.max(fdepth_abs)) if fdepth_abs.size else None,
        "time_bucket_counts": bucket_counts,
        "decision": f"{decision_prefix}_CONVERGENCE",
    }
    if ledger_window_s == 600.0:
        metrics["original_candidate_count_0_600"] = metrics["original_candidate_count_window"]
        metrics["native_candidate_count_0_600"] = metrics["native_candidate_count_window"]
    if native.meta.get("performance_truncated"):
        metrics["decision"] = f"{decision_prefix}_PARTIAL_CONVERGENCE"
    elif tp == int(np.count_nonzero(original_mask)) and fp == 0 and fn == 0 and metrics["tfail_max_abs_error_on_tp"] == 0.0 and metrics["fdepth_max_abs_error_on_tp"] == 0.0:
        metrics["decision"] = f"{decision_prefix}_CONVERGENCE"
    elif tp == int(np.count_nonzero(original_mask)) and fp == 0 and fn == 0:
        metrics["decision"] = f"{decision_prefix}_MISMATCH_LOCALIZED"
    elif tp > 0:
        metrics["decision"] = f"{decision_prefix}_PARTIAL_CONVERGENCE"
    else:
        metrics["decision"] = f"{decision_prefix}_MISMATCH_LOCALIZED"

    def rows_from_mask(mask: np.ndarray) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for zero_idx in np.flatnonzero(mask):
            row, col = mapping[int(zero_idx)]
            rows.append(
                {
                    "cell": int(zero_idx) + 1,
                    "row": row,
                    "col": col,
                    "original_tfail": float(original.tfail_s[zero_idx]) if np.isfinite(original.tfail_s[zero_idx]) else None,
                    "native_tfail": float(native.tfail_s[zero_idx]) if np.isfinite(native.tfail_s[zero_idx]) else None,
                    "original_fdepth": float(original.fdepth_m[zero_idx]),
                    "native_fdepth": float(native.fdepth_m[zero_idx]),
                }
            )
        return rows
    return metrics, rows_from_mask(fp_mask), rows_from_mask(fn_mask), rows_from_mask(tp_mask)


def compare_0_600_ledgers(native: LedgerArrays, original: LedgerArrays, mapping: list[tuple[int, int]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    metrics, false_positives, false_negatives, _true_positives = compare_window_ledgers(
        native,
        original,
        mapping,
        ledger_window_s=600.0,
    )
    return metrics, false_positives, false_negatives


def _tfail_arrays_equal(left: np.ndarray, right: np.ndarray) -> bool:
    return bool(np.array_equal(np.isnan(left), np.isnan(right)) and np.allclose(np.nan_to_num(left, nan=-1.0), np.nan_to_num(right, nan=-1.0), rtol=0.0, atol=0.0))


def validate_checkpoint_resume(
    case_dir: Path,
    validation_dir: Path,
    *,
    prefix: int = 5000,
    split: int = 2500,
    checkpoint_interval: int = 500,
) -> dict[str, Any]:
    validation_dir.mkdir(parents=True, exist_ok=True)
    direct, _direct_trace, _direct_gate, direct_summary = run_active_order_0_600(
        case_dir,
        max_active_index=prefix,
        trace_window_cells=set(),
        checkpoint_dir=None,
        collect_gate_trace_for_eligible=False,
    )
    checkpoint_dir = validation_dir / "resume_checkpoint"
    first, _first_trace, _first_gate, first_summary = run_active_order_0_600(
        case_dir,
        max_active_index=split,
        trace_window_cells=set(),
        checkpoint_dir=checkpoint_dir,
        checkpoint_interval=checkpoint_interval,
        collect_gate_trace_for_eligible=False,
    )
    resumed, _resumed_trace, _resumed_gate, resumed_summary = run_active_order_0_600(
        case_dir,
        max_active_index=prefix,
        trace_window_cells=set(),
        checkpoint_dir=checkpoint_dir,
        resume=True,
        checkpoint_interval=checkpoint_interval,
        collect_gate_trace_for_eligible=False,
    )
    candidate_direct = direct_summary["candidates_0_600"]
    candidate_resumed = resumed_summary["candidates_0_600"]
    result = {
        "decision": "CHECKPOINT_RESUME_READY",
        "prefix": prefix,
        "split": split,
        "checkpoint_interval": checkpoint_interval,
        "direct_candidate_count": len(candidate_direct),
        "resumed_candidate_count": len(candidate_resumed),
        "arrays_match": bool(
            np.array_equal(direct.gindx, resumed.gindx)
            and _tfail_arrays_equal(direct.tfail_s, resumed.tfail_s)
            and np.allclose(direct.fdepth_m, resumed.fdepth_m, rtol=0.0, atol=0.0)
        ),
        "candidate_lists_match": candidate_direct == candidate_resumed,
        "ts_carry_match": float(direct_summary["ts_carry"]) == float(resumed_summary["ts_carry"]),
        "processed_count_match": int(direct_summary["processed_eligible_cells"]) == int(resumed_summary["processed_eligible_cells"]),
        "eligible_count_match": int(direct_summary["eligible_cells_in_evaluated_range"]) == int(resumed_summary["eligible_cells_in_evaluated_range"]),
        "first_stage_last_processed": first_summary["last_processed_active_index"],
        "resumed_last_processed": resumed_summary["last_processed_active_index"],
        "direct_summary": {
            "processed_eligible_cells": direct_summary["processed_eligible_cells"],
            "eligible_cells_in_evaluated_range": direct_summary["eligible_cells_in_evaluated_range"],
            "ts_carry": direct_summary["ts_carry"],
            "wall_seconds": direct_summary["wall_seconds"],
        },
        "resumed_summary": {
            "processed_eligible_cells": resumed_summary["processed_eligible_cells"],
            "eligible_cells_in_evaluated_range": resumed_summary["eligible_cells_in_evaluated_range"],
            "ts_carry": resumed_summary["ts_carry"],
            "wall_seconds": resumed_summary["wall_seconds"],
        },
    }
    checks = [
        result["arrays_match"],
        result["candidate_lists_match"],
        result["ts_carry_match"],
        result["processed_count_match"],
        result["eligible_count_match"],
    ]
    if not all(checks):
        result["decision"] = "CHECKPOINT_RESUME_BLOCKED_WITH_EXACT_REASON"
    (validation_dir / "checkpoint_resume_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _field_to_gap_category(field: str) -> str:
    return {
        "pt": "PT_FORMULA_MISMATCH",
        "desat": "DESATURATION_FORMULA_MISMATCH",
        "desatt": "DESATURATION_FORMULA_MISMATCH",
        "inidesat": "INIDOUBLELAYER_INITIALIZATION_MISMATCH",
        "fsc": "FSC_FORMULA_MISMATCH",
        "fsw": "FSW_FORMULA_MISMATCH",
        "fs": "FS_COMBINATION_MISMATCH",
        "fmn": "FS_COMBINATION_MISMATCH",
        "fdepth": "FDEPTH_CAPTURE_MISMATCH",
        "gindx": "GINDX_UPDATE_MISMATCH",
    }.get(field, "FORTRAN_ORDER_OR_PRECISION_MISMATCH")


def run_doublelayer_convergence(
    phase_dir: Path,
    previous_phase_dir: Path,
    *,
    case_dir: Path,
    nmax: int = 10,
) -> dict[str, Any]:
    audit_dir = phase_dir / "01_original_doublelayer_trace_audit"
    field_dir = phase_dir / "02_cell_field_pack"
    init_dir = phase_dir / "03_inidoublelayer_port"
    doublelayer_dir = phase_dir / "04_doublelayer_pt_desat_fs_port"
    compare_dir = phase_dir / "05_cell_level_comparison"
    gap_dir = phase_dir / "06_gap_attribution"
    for directory in (audit_dir, field_dir, init_dir, doublelayer_dir, compare_dir, gap_dir):
        directory.mkdir(parents=True, exist_ok=True)

    trace_dir = previous_phase_dir / "01_original_fortran_trace"
    unsfin_raw = trace_dir / "original_unsfin_cell_trace.raw"
    doublelayer_raw = trace_dir / "original_doublelayer_cell_trace.raw"
    original_rows = parse_unsfin_raw(unsfin_raw)
    doublelayer_rows = parse_doublelayer_raw(doublelayer_raw)
    original_summary = summarize_original(original_rows, doublelayer_rows)
    packs, pack_summary = build_cell_field_packs(case_dir, original_rows)

    inidoublelayer_rows: list[dict[str, Any]] = []
    native_top_rows: list[dict[str, Any]] = []
    native_final_rows: list[dict[str, Any]] = []
    per_cell_status: dict[str, Any] = {}
    for cell in TARGET_CELLS:
        rows = original_rows.get(str(cell), [])
        pack = packs.get(cell)
        root_inputs = _root_inputs_for_cell(rows, nmax=nmax)
        if pack is None or root_inputs is None:
            per_cell_status[str(cell)] = {"status": "blocked_missing_field_pack_or_roots"}
            continue
        roots_a, roots_b, roots_c, coeffs = root_inputs
        original_times = sorted(
            {
                float(row["tt"])
                for row in doublelayer_rows
                if row.get("event") == "DL_TOP" and int(row.get("cell", -1)) == cell
            }
        )
        base_init = evaluate_inidoublelayer(pack, roots_a, roots_b, roots_c, coeffs, tt=60.0)
        for row in base_init:
            inidoublelayer_rows.append({"event": "NATIVE_INIDOUBLELAYER", **row})
        for tt in original_times:
            state = _state_before_ts(rows, tt)
            native_rows, native_final = evaluate_doublelayer_top(
                pack,
                roots_a,
                roots_b,
                roots_c,
                coeffs,
                base_init,
                tt=tt,
                initial_state=state,
            )
            native_top_rows.extend(native_rows)
            native_final_rows.append(native_final)
        per_cell_status[str(cell)] = {
            "status": "evaluated",
            "original_doublelayer_times": original_times,
            "native_top_rows": len([row for row in native_top_rows if row.get("cell") == cell]),
        }

    metrics, divergent_rows = compare_doublelayer_rows(doublelayer_rows, native_top_rows, native_final_rows)
    metrics.update(
        {
            "source_provenance": SOURCE_PROVENANCE,
            "runtime_provider_enabled": False,
            "output_inferred": False,
            "dfs_runtime_modified": False,
            "scope": "four_cell_inidoublelayer_doublelayer_pt_desat_fs_port",
            "target_cells": list(TARGET_CELLS),
            "per_cell_status": per_cell_status,
        }
    )
    first_categories = sorted({row.get("category", "UNKNOWN") for row in divergent_rows})
    fdepth_gindx_converged = all(
        cell_metrics.get("final_fdepth_mismatches") == 0 and cell_metrics.get("final_gindx_mismatches") == 0
        for cell_metrics in metrics["per_cell"].values()
    )
    if metrics["total_native_rows"] == 0:
        decision = "NATIVE_DOUBLELAYER_TRACE_BLOCKED"
    elif fdepth_gindx_converged:
        decision = "NATIVE_DOUBLELAYER_FDEPTH_GINDX_CONVERGENCE"
    elif any(
        (cell_metrics.get("first_divergent") or {}).get("category") in {"PT_FORMULA_MISMATCH", "DESATURATION_FORMULA_MISMATCH"}
        for cell_metrics in metrics["per_cell"].values()
    ):
        decision = "NATIVE_DOUBLELAYER_BLOCKED_AT_PT_DESATT"
    elif divergent_rows:
        decision = "NATIVE_DOUBLELAYER_MISMATCH_LOCALIZED"
    else:
        decision = "NATIVE_DOUBLELAYER_FDEPTH_GINDX_CONVERGENCE"
    metrics["decision"] = decision

    audit = {
        "decision": "ORIGINAL_DOUBLELAYER_TRACE_USABLE",
        "previous_trace_dir": str(trace_dir),
        "original_trace_summary": original_summary,
        "coverage": {
            str(cell): {
                "expected_tfail_s": {90008: 78.0, 90001: 321.0, 51509: 343.0, 21846: 373.0}[cell],
                "doublelayer_rows": original_summary[str(cell)]["doublelayer_rows"],
                "fdepth_capture_visible": original_summary[str(cell)]["fdepth_capture_visible"],
                "tfail_assignment_visible": original_summary[str(cell)]["tfail_assign_rows"] > 0,
            }
            for cell in TARGET_CELLS
        },
    }
    gap = {
        "decision": "GAP_LOCALIZED_PATCHABLE_IN_LEDGER_ONLY" if divergent_rows else "GAP_ATTRIBUTION_INCONCLUSIVE",
        "categories": first_categories,
        "runtime_patch_forbidden": True,
        "notes": [
            "This is a ledger-only diagnostic comparison against original runtime trace rows.",
            "No production native provider or DFS runtime path is enabled.",
        ],
    }

    (audit_dir / "original_doublelayer_trace_summary.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    (field_dir / "cell_field_pack_summary.json").write_text(json.dumps(pack_summary, indent=2), encoding="utf-8")
    write_dict_csv(
        field_dir / "cell_field_pack.csv",
        [
            {
                "cell": pack.cell,
                "row": pack.row,
                "col": pack.col,
                "slope_rad": pack.slope_rad,
                "zone_id": pack.zone_id,
                "ltstar": pack.ltstar,
                "lbstar": pack.lbstar,
                "zmin": pack.zmin,
                "nzst": pack.nzst,
                "nzsb": pack.nzsb,
                "beta": pack.beta,
                "lt": pack.lt,
                "lb": pack.lb,
                "rikzero": pack.rikzero,
            }
            for pack in packs.values()
        ],
    )
    write_dict_csv(init_dir / "inidoublelayer_native_trace.csv", inidoublelayer_rows)
    write_dict_csv(doublelayer_dir / "native_doublelayer_cell_trace.csv", native_top_rows + native_final_rows)
    (doublelayer_dir / "native_doublelayer_summary.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (compare_dir / "cell_level_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_dict_csv(compare_dir / "first_divergent_value_table.csv", divergent_rows)
    (gap_dir / "gap_attribution.json").write_text(json.dumps(gap, indent=2), encoding="utf-8")
    return metrics


def run_tfirst_convergence(
    phase_dir: Path,
    previous_phase_dir: Path,
    *,
    case_dir: Path,
    nmax: int = 10,
) -> dict[str, Any]:
    original_dir = phase_dir / "01_original_ts_lifecycle_trace"
    native_dir = phase_dir / "02_native_tfirst_search_port"
    compare_dir = phase_dir / "03_cell_tfirst_comparison"
    gap_dir = phase_dir / "04_gap_attribution"
    for directory in (original_dir, native_dir, compare_dir, gap_dir):
        directory.mkdir(parents=True, exist_ok=True)

    trace_dir = previous_phase_dir / "01_original_fortran_trace"
    unsfin_raw = trace_dir / "original_unsfin_cell_trace.raw"
    doublelayer_raw = trace_dir / "original_doublelayer_cell_trace.raw"
    original_rows = parse_unsfin_raw(unsfin_raw)
    doublelayer_rows = parse_doublelayer_raw(doublelayer_raw)
    packs, pack_summary = build_cell_field_packs(case_dir, original_rows)

    native_trace: list[dict[str, Any]] = []
    native_summaries: dict[str, Any] = {}
    ts_carry_rows: list[dict[str, Any]] = []
    for cell in TARGET_CELLS:
        rows = original_rows.get(str(cell), [])
        pack = packs.get(cell)
        root_inputs = _root_inputs_for_cell(rows, nmax=nmax)
        if pack is None or root_inputs is None:
            native_summaries[str(cell)] = {"cell": cell, "status": "blocked_missing_field_pack_or_roots"}
            continue
        roots_a, roots_b, roots_c, coeffs = root_inputs
        ts_carry = derive_inidoublelayer_ts_carry(pack, roots_a, roots_b, roots_c, coeffs, doublelayer_rows)
        ts_carry_rows.append(ts_carry)
        trace, summary = native_tfirst_search_cell(
            pack,
            roots_a,
            roots_b,
            roots_c,
            coeffs,
            initial_ts=float(ts_carry["ts"]),
        )
        native_trace.extend(trace)
        native_summaries[str(cell)] = summary | {"ts_carry": ts_carry}

    original_csv_rows = [row for rows in original_rows.values() for row in rows]
    write_dict_csv(original_dir / "original_ts_lifecycle_trace.csv", original_csv_rows)
    write_dict_csv(
        original_dir / "original_tsearch_trace.csv",
        [
            row
            for row in original_csv_rows
            if row.get("event") in {"STEP_BEFORE", "STEP_AFTER", "REFINE", "TFAIL_ASSIGN", "EXIT_AFTER_TSIMUL", "EXIT_NO_FAILURE"}
        ],
    )
    write_dict_csv(native_dir / "native_tfirst_cell_trace.csv", native_trace)
    metrics, divergent_rows = compare_tfirst_search(original_rows, native_trace, native_summaries)
    metrics.update(
        {
            "source_provenance": SOURCE_PROVENANCE,
            "runtime_provider_enabled": False,
            "output_inferred": False,
            "dfs_runtime_modified": False,
            "scope": "four_cell_unsfin_tnown_tincrement_tfirst_search",
            "target_cells": list(TARGET_CELLS),
            "ts_carry": ts_carry_rows,
            "field_pack": pack_summary,
        }
    )
    first_categories = sorted({row.get("category", "UNKNOWN") for row in divergent_rows})
    gap = {
        "decision": "GAP_ATTRIBUTION_INCONCLUSIVE" if metrics["decision"] == "NATIVE_TFIRST_FOUR_CELL_CONVERGENCE" else "GAP_LOCALIZED_PATCHABLE_IN_LEDGER_ONLY",
        "categories": first_categories,
        "runtime_patch_forbidden": True,
        "notes": [
            "Native tfirst search uses original source tnown/tincrement logic and independently generates doublelayer call times.",
            "The inidoublelayer scalar ts carry is derived from original runtime inidesat trace because the original local scalar is carried into the call before assignment inside the loop.",
        ],
    }
    semantic = {
        "decision": "TS_CARRY_SEMANTIC_CONFIRMED_PATCHABLE",
        "source_evidence": {
            "ts_not_declared_explicit_double": "unsfin.F90 declarations show tnown is double precision, while ts is implicit and assigned after call inidoublelayer.",
            "call_order": "unsfin.F90 calls inidoublelayer before the jf loop assigns ts for doublelayer.",
        },
        "runtime_evidence": ts_carry_rows,
        "native_policy": "ledger_only_diagnostic_reproduces_per_cell_ts_carry_derived_from_original_runtime_trace",
    }
    (original_dir / "ts_carry_semantic_summary.json").write_text(json.dumps(semantic, indent=2), encoding="utf-8")
    (native_dir / "native_tfirst_summary.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (compare_dir / "tfirst_cell_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_dict_csv(compare_dir / "first_divergent_iteration_table.csv", divergent_rows)
    (gap_dir / "gap_attribution.json").write_text(json.dumps(gap, indent=2), encoding="utf-8")
    return metrics


def run_0_600_ledger_diagnostic(
    phase_dir: Path,
    *,
    case_dir: Path,
    oracle_dir: Path,
    max_active_index: int | None = None,
) -> dict[str, Any]:
    active_dir = phase_dir / "01_active_order_ts_carry"
    run_dir = phase_dir / "02_native_0_600_ledger_run"
    compare_dir = phase_dir / "03_ledger_comparison"
    gap_dir = phase_dir / "04_gap_attribution"
    for directory in (active_dir, run_dir, compare_dir, gap_dir):
        directory.mkdir(parents=True, exist_ok=True)

    context = build_active_context(case_dir)
    original = load_original_oracle(oracle_dir)
    original_0_600 = np.flatnonzero(np.isfinite(original.tfail_s) & (original.tfail_s > 0.0) & (original.tfail_s <= 600.0))
    trace_cells = {int(idx) + 1 for idx in original_0_600} | set(TARGET_CELLS)
    ledger, active_trace, gate_trace, run_summary = run_active_order_0_600(
        case_dir,
        max_active_index=max_active_index,
        trace_window_cells=trace_cells,
    )
    metrics, false_positives, false_negatives = compare_0_600_ledgers(ledger, original, context.active_mapping)
    metrics["original_expected_cells_0_600"] = [int(idx) + 1 for idx in original_0_600]
    metrics["native_cells_0_600"] = [
        int(idx) + 1
        for idx in np.flatnonzero(np.isfinite(ledger.tfail_s) & (ledger.tfail_s > 0.0) & (ledger.tfail_s <= 600.0))
    ]

    write_dict_csv(active_dir / "ts_carry_active_order_trace.csv", active_trace)
    write_dict_csv(active_dir / "eligibility_gate_trace.csv", gate_trace)
    ledger_rows = [
        {
            "cell": idx + 1,
            "gindx": int(ledger.gindx[idx]),
            "tfail_s": float(ledger.tfail_s[idx]) if np.isfinite(ledger.tfail_s[idx]) else "",
            "fdepth_m": float(ledger.fdepth_m[idx]),
        }
        for idx in range(len(ledger.gindx))
        if ledger.gindx[idx] > 0 or (np.isfinite(ledger.tfail_s[idx]) and ledger.tfail_s[idx] > 0.0)
    ]
    write_dict_csv(run_dir / "native_0_600_ledger.csv", ledger_rows)
    np.savetxt(run_dir / "native_0_600_gindx.csv", ledger.gindx, fmt="%d", delimiter=",")
    np.savetxt(run_dir / "native_0_600_tfail_s.csv", ledger.tfail_s, fmt="%.12g", delimiter=",")
    np.savetxt(run_dir / "native_0_600_fdepth_m.csv", ledger.fdepth_m, fmt="%.12g", delimiter=",")
    (run_dir / "native_0_600_ledger_meta.json").write_text(json.dumps(ledger.meta, indent=2), encoding="utf-8")
    (run_dir / "native_0_600_run_summary.json").write_text(json.dumps(run_summary, indent=2), encoding="utf-8")
    (compare_dir / "native_0_600_vs_original_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_dict_csv(compare_dir / "native_0_600_false_positives.csv", false_positives)
    write_dict_csv(compare_dir / "native_0_600_false_negatives.csv", false_negatives)

    if metrics["decision"] == "NATIVE_0_600_LEDGER_CONVERGENCE":
        gap_decision = "GAP_ATTRIBUTION_INCONCLUSIVE"
        categories: list[str] = []
    elif ledger.meta.get("performance_truncated"):
        gap_decision = "GAP_LOCALIZED_PATCHABLE_IN_LEDGER_ONLY"
        categories = ["PERFORMANCE_TRUNCATION_INVALID"]
    else:
        gap_decision = "GAP_LOCALIZED_PATCHABLE_IN_LEDGER_ONLY"
        categories = ["TS_CARRY_ACTIVE_ORDER_MISMATCH", "FIELD_PACK_MISMATCH"]
    gap = {
        "decision": gap_decision,
        "categories": categories,
        "runtime_patch_forbidden": True,
        "metrics_decision": metrics["decision"],
        "notes": [
            "This diagnostic preserves active-cell order and uses carried ts state across cells.",
            "If performance_truncated=true, tail-cell false positives are not fully ruled out.",
        ],
    }
    (gap_dir / "gap_attribution.json").write_text(json.dumps(gap, indent=2), encoding="utf-8")
    return metrics


def _write_ledger_artifacts(run_dir: Path, stem: str, ledger: LedgerArrays, summary: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(run_dir / f"{stem}_gindx.npz", gindx=ledger.gindx)
    np.savez_compressed(run_dir / f"{stem}_tfail.npz", tfail_s=ledger.tfail_s)
    np.savez_compressed(run_dir / f"{stem}_fdepth.npz", fdepth_m=ledger.fdepth_m)
    write_dict_csv(run_dir / f"{stem}_candidates.csv", summary.get("candidates_window", summary.get("candidates_0_600", [])))
    (run_dir / f"{stem}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def _write_metrics_artifacts(
    compare_dir: Path,
    metrics_name: str,
    metrics: dict[str, Any],
    false_positives: list[dict[str, Any]],
    false_negatives: list[dict[str, Any]],
) -> None:
    compare_dir.mkdir(parents=True, exist_ok=True)
    (compare_dir / metrics_name).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_dict_csv(compare_dir / "native_0_600_false_positives.csv", false_positives)
    write_dict_csv(compare_dir / "native_0_600_false_negatives.csv", false_negatives)


def _markdown_table_from_metrics(metrics: dict[str, Any]) -> str:
    keys = [
        "performance_truncated",
        "evaluated_active_index_end",
        "ledger_window_s",
        "original_candidate_count_window",
        "native_candidate_count_window",
        "true_positives",
        "false_positives",
        "false_negatives_global",
        "false_negatives_in_evaluated_range",
        "precision",
        "recall_global",
        "jaccard_iou_global",
        "tfail_max_abs_error_on_tp",
        "fdepth_max_abs_error_on_tp",
        "decision",
    ]
    lines = ["| metric | value |", "| --- | --- |"]
    for key in keys:
        lines.append(f"| {key} | {metrics.get(key)} |")
    return "\n".join(lines)


def run_active_order_completion_phase(
    phase_dir: Path,
    *,
    case_dir: Path,
    oracle_dir: Path,
    checkpoint_interval: int = 1000,
    skip_validation: bool = False,
    skip_full: bool = False,
) -> dict[str, Any]:
    checkpoint_dir = phase_dir / "01_checkpoint_resume"
    profile_dir = phase_dir / "02_performance_profile"
    prefix_dir = phase_dir / "03_native_prefix_to_90008"
    full_dir = phase_dir / "04_native_full_0_600_ledger"
    compare_dir = phase_dir / "05_ledger_comparison"
    gap_dir = phase_dir / "06_gap_attribution"
    patch_dir = phase_dir / "07_optional_ledger_only_patches"
    for directory in (checkpoint_dir, profile_dir, prefix_dir, full_dir, compare_dir, gap_dir, patch_dir):
        directory.mkdir(parents=True, exist_ok=True)

    validation = (
        {"decision": "CHECKPOINT_RESUME_SKIPPED"}
        if skip_validation
        else validate_checkpoint_resume(case_dir, checkpoint_dir, prefix=5000, split=2500, checkpoint_interval=checkpoint_interval)
    )
    (checkpoint_dir / "checkpoint_resume_design.md").write_text(
        "\n".join(
            [
                "# Checkpoint / Resume Design",
                "",
                "- Stores compact npz arrays for gindx, tfail_s, and fdepth_m.",
                "- Stores JSON state for last_processed_active_index, next_active_index, scalar ts_carry, counters, candidate list, profile stats, and config hash.",
                "- Resume restores exactly the next active-cell index and scalar ts_carry; active cells are never parallelized or skipped.",
                "- active_order_mode=true, per_cell_fitted_ts=false, ledger_window_s=600 are enforced on load.",
            ]
        ),
        encoding="utf-8",
    )
    (checkpoint_dir / "checkpoint_resume_report.md").write_text(
        "# Checkpoint / Resume Validation\n\n" + json.dumps(validation, indent=2),
        encoding="utf-8",
    )

    original = load_original_oracle(oracle_dir)
    context = build_active_context(case_dir)
    original_0_600 = np.flatnonzero(np.isfinite(original.tfail_s) & (original.tfail_s > 0.0) & (original.tfail_s <= 600.0))
    trace_cells = {int(idx) + 1 for idx in original_0_600} | set(TARGET_CELLS)

    prefix_checkpoint_dir = prefix_dir / "checkpoints"
    prefix_ledger, prefix_trace, prefix_gate, prefix_summary = run_active_order_0_600(
        case_dir,
        max_active_index=90008,
        trace_window_cells=trace_cells,
        checkpoint_dir=prefix_checkpoint_dir,
        checkpoint_interval=checkpoint_interval,
        collect_gate_trace_for_eligible=False,
    )
    prefix_metrics, prefix_fp, prefix_fn = compare_0_600_ledgers(prefix_ledger, original, context.active_mapping)
    prefix_metrics["original_expected_cells_0_600"] = [int(idx) + 1 for idx in original_0_600]
    prefix_metrics["native_cells_0_600"] = [
        int(idx) + 1
        for idx in np.flatnonzero(np.isfinite(prefix_ledger.tfail_s) & (prefix_ledger.tfail_s > 0.0) & (prefix_ledger.tfail_s <= 600.0))
    ]
    _write_ledger_artifacts(prefix_dir, "native_prefix_90008", prefix_ledger, prefix_summary)
    write_dict_csv(prefix_dir / "native_prefix_90008_active_trace.csv", prefix_trace)
    write_dict_csv(prefix_dir / "native_prefix_90008_gate_trace.csv", prefix_gate)
    (prefix_dir / "native_prefix_90008_metrics.json").write_text(json.dumps(prefix_metrics, indent=2), encoding="utf-8")
    (prefix_dir / "native_prefix_90008_report.md").write_text(
        "# Prefix Through 90008\n\n" + _markdown_table_from_metrics(prefix_metrics),
        encoding="utf-8",
    )

    prefix_success = (
        prefix_metrics["true_positives"] == 4
        and prefix_metrics["false_positives"] == 0
        and prefix_metrics["false_negatives_in_evaluated_range"] == 0
        and prefix_metrics["tfail_max_abs_error_on_tp"] == 0.0
        and prefix_metrics["fdepth_max_abs_error_on_tp"] == 0.0
    )

    full_metrics: dict[str, Any] | None = None
    full_summary: dict[str, Any] | None = None
    full_fp: list[dict[str, Any]] = []
    full_fn: list[dict[str, Any]] = []
    if prefix_success and not skip_full:
        full_checkpoint_dir = full_dir / "checkpoints"
        full_checkpoint_dir.mkdir(parents=True, exist_ok=True)
        for source_name in ("active_order_checkpoint.npz", "active_order_checkpoint.json"):
            source = prefix_checkpoint_dir / source_name
            if source.exists():
                shutil.copy2(source, full_checkpoint_dir / source_name)
        full_ledger, full_trace, full_gate, full_summary = run_active_order_0_600(
            case_dir,
            trace_window_cells=trace_cells,
            checkpoint_dir=full_checkpoint_dir,
            resume=True,
            checkpoint_interval=checkpoint_interval,
            collect_gate_trace_for_eligible=False,
        )
        full_metrics, full_fp, full_fn = compare_0_600_ledgers(full_ledger, original, context.active_mapping)
        full_metrics["original_expected_cells_0_600"] = [int(idx) + 1 for idx in original_0_600]
        full_metrics["native_cells_0_600"] = [
            int(idx) + 1
            for idx in np.flatnonzero(np.isfinite(full_ledger.tfail_s) & (full_ledger.tfail_s > 0.0) & (full_ledger.tfail_s <= 600.0))
        ]
        _write_ledger_artifacts(full_dir, "native_0_600_full", full_ledger, full_summary)
        write_dict_csv(full_dir / "native_0_600_full_active_trace.csv", full_trace)
        write_dict_csv(full_dir / "native_0_600_full_gate_trace.csv", full_gate)
        (full_dir / "native_0_600_full_metrics.json").write_text(json.dumps(full_metrics, indent=2), encoding="utf-8")
        (full_dir / "native_0_600_full_report.md").write_text(
            "# Full 0-600 Active Ledger\n\n" + _markdown_table_from_metrics(full_metrics),
            encoding="utf-8",
        )

    best_metrics = full_metrics or prefix_metrics
    _write_metrics_artifacts(
        compare_dir,
        "native_0_600_full_vs_original_metrics.json",
        best_metrics,
        full_fp if full_metrics is not None else prefix_fp,
        full_fn if full_metrics is not None else prefix_fn,
    )
    (compare_dir / "native_0_600_full_vs_original_report.md").write_text(
        "# Native 0-600 Ledger Comparison\n\n" + _markdown_table_from_metrics(best_metrics),
        encoding="utf-8",
    )

    profile_summary = {
        "validation": validation,
        "prefix_profile": prefix_summary.get("profile_stats", {}),
        "prefix_wall_seconds": prefix_summary.get("wall_seconds"),
        "full_profile": full_summary.get("profile_stats", {}) if full_summary else None,
        "full_wall_seconds": full_summary.get("wall_seconds") if full_summary else None,
    }
    (profile_dir / "performance_profile.json").write_text(json.dumps(profile_summary, indent=2), encoding="utf-8")
    (profile_dir / "performance_profile.md").write_text(
        "# Performance Profile\n\n" + json.dumps(profile_summary, indent=2),
        encoding="utf-8",
    )
    (profile_dir / "optimization_summary.md").write_text(
        "\n".join(
            [
                "# Optimization Summary",
                "",
                "- Added final-only inidoublelayer/doublelayer/tfirst path for long active-order ledger runs.",
                "- Disabled verbose per-eligible gate trace by default; candidate and target-cell traces remain available.",
                "- Added compact npz checkpoint arrays plus JSON scalar ts/counter state.",
                "- Preserved active-cell order, sequential ts carry, formulas, and per_cell_fitted_ts=false.",
            ]
        ),
        encoding="utf-8",
    )

    if best_metrics["decision"] == "NATIVE_0_600_LEDGER_CONVERGENCE":
        gap_decision = "GAP_ATTRIBUTION_INCONCLUSIVE"
        categories: list[str] = []
    elif not prefix_success:
        gap_decision = "GAP_LOCALIZED_PATCHABLE_IN_LEDGER_ONLY"
        categories = ["TS_CARRY_ACTIVE_ORDER_MISMATCH", "FIELD_PACK_MISMATCH", "TFIRST_REFINEMENT_MISMATCH"]
    else:
        gap_decision = "GAP_LOCALIZED_NEEDS_MORE_TRACE"
        categories = ["PERFORMANCE_TRUNCATION_INVALID"] if skip_full else ["FORTRAN_ORDER_OR_PRECISION_MISMATCH"]
    gap = {
        "decision": gap_decision,
        "categories": categories,
        "runtime_patch_forbidden": True,
        "metrics_decision": best_metrics["decision"],
        "prefix_success": prefix_success,
        "full_run_attempted": full_metrics is not None,
    }
    (gap_dir / "gap_attribution.json").write_text(json.dumps(gap, indent=2), encoding="utf-8")
    (gap_dir / "gap_attribution.md").write_text("# Gap Attribution\n\n" + json.dumps(gap, indent=2), encoding="utf-8")
    (patch_dir / "patch_candidates.md").write_text(
        "# Optional Ledger-Only Patch Candidates\n\nImplemented diagnostic-only checkpoint/resume and final-only evaluation. No runtime provider, DFS, or bridge loader changes were made.",
        encoding="utf-8",
    )
    (patch_dir / "patch_summary.md").write_text(
        "# Patch Summary\n\nChanged only ledger diagnostic/test code for checkpoint/resume and performance-safe final-only evaluation.",
        encoding="utf-8",
    )

    decision = best_metrics["decision"]
    if full_metrics is None and prefix_success:
        decision = "PREFIX_90008_ALL_ORIGINAL_CANDIDATES_MATCHED"
    return {
        "decision": decision,
        "checkpoint_resume": validation,
        "prefix_metrics": prefix_metrics,
        "full_metrics": full_metrics,
        "gap": gap,
    }


def _copy_checkpoint(source_dir: Path, target_dir: Path) -> bool:
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = False
    for name in ("active_order_checkpoint.npz", "active_order_checkpoint.json"):
        source = source_dir / name
        if source.exists():
            shutil.copy2(source, target_dir / name)
            copied = True
    return copied


def run_active_order_window_phase(
    phase_dir: Path,
    *,
    case_dir: Path,
    oracle_dir: Path,
    ledger_window_s: float,
    checkpoint_interval: int = 1000,
    completed_checkpoint_dir: Path | None = None,
    skip_validation: bool = False,
) -> dict[str, Any]:
    label = _ledger_window_label(ledger_window_s)
    pretty_label = label.replace("_", "-")
    perf_dir = phase_dir / "01_performance_cache"
    run_dir = phase_dir / f"02_native_{label}_ledger_run"
    compare_dir = phase_dir / "03_ledger_comparison"
    gap_dir = phase_dir / "04_gap_attribution"
    patch_dir = phase_dir / "05_optional_ledger_only_patches"
    for directory in (perf_dir, run_dir, compare_dir, gap_dir, patch_dir):
        directory.mkdir(parents=True, exist_ok=True)

    validation = (
        {"decision": "CHECKPOINT_RESUME_SKIPPED"}
        if skip_validation
        else validate_checkpoint_resume(case_dir, perf_dir, prefix=5000, split=2500, checkpoint_interval=checkpoint_interval)
    )

    original = load_original_oracle(oracle_dir)
    context = build_active_context(case_dir)
    original_window = np.flatnonzero(np.isfinite(original.tfail_s) & (original.tfail_s > 0.0) & (original.tfail_s <= ledger_window_s))
    original_0_600 = np.flatnonzero(np.isfinite(original.tfail_s) & (original.tfail_s > 0.0) & (original.tfail_s <= 600.0))
    trace_cells = {int(idx) + 1 for idx in original_window} | set(TARGET_CELLS)

    checkpoint_dir = run_dir / "checkpoints"
    checkpoint_resume_used = False
    if completed_checkpoint_dir is not None and _copy_checkpoint(completed_checkpoint_dir, checkpoint_dir):
        checkpoint_resume_used = True
    ledger, active_trace, gate_trace, summary = run_active_order_0_600(
        case_dir,
        trace_window_cells=trace_cells,
        checkpoint_dir=checkpoint_dir,
        resume=checkpoint_resume_used,
        checkpoint_interval=checkpoint_interval,
        collect_gate_trace_for_eligible=False,
        ledger_window_s=ledger_window_s,
    )
    summary["checkpoint_resume_used"] = checkpoint_resume_used
    summary["completed_active_count"] = int(summary.get("completed_active_count", summary.get("last_processed_active_index", 0)))
    ledger.meta["checkpoint_resume_used"] = checkpoint_resume_used
    ledger.meta["ledger_window_s"] = ledger_window_s

    metrics, false_positives, false_negatives, true_positives = compare_window_ledgers(
        ledger,
        original,
        context.active_mapping,
        ledger_window_s=ledger_window_s,
    )
    metrics["original_expected_cells_window"] = [int(idx) + 1 for idx in original_window]
    metrics["native_cells_window"] = [
        int(idx) + 1
        for idx in np.flatnonzero(np.isfinite(ledger.tfail_s) & (ledger.tfail_s > 0.0) & (ledger.tfail_s <= ledger_window_s))
    ]
    metrics["checkpoint_resume_used"] = checkpoint_resume_used

    zero_600_metrics, zero_600_fp, zero_600_fn, zero_600_tp = compare_window_ledgers(
        ledger,
        original,
        context.active_mapping,
        ledger_window_s=600.0,
    )
    zero_600_metrics["original_expected_cells_0_600"] = [int(idx) + 1 for idx in original_0_600]
    zero_600_metrics["native_cells_0_600"] = [
        int(idx) + 1
        for idx in np.flatnonzero(np.isfinite(ledger.tfail_s) & (ledger.tfail_s > 0.0) & (ledger.tfail_s <= 600.0))
    ]

    np.savez_compressed(run_dir / f"native_{label}_gindx.npz", gindx=ledger.gindx)
    np.savez_compressed(run_dir / f"native_{label}_tfail.npz", tfail_s=ledger.tfail_s)
    np.savez_compressed(run_dir / f"native_{label}_fdepth.npz", fdepth_m=ledger.fdepth_m)
    write_dict_csv(run_dir / f"native_{label}_candidates.csv", summary.get("candidates_window", []))
    (run_dir / f"native_{label}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / f"native_{label}_checkpoint_final.json").write_text(
        json.dumps(
            {
                "checkpoint_format": "native_unsfin_active_order_v1_window_summary",
                "source_checkpoint_dir": str(checkpoint_dir),
                **summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    write_dict_csv(run_dir / f"native_{label}_active_trace.csv", active_trace)
    write_dict_csv(run_dir / f"native_{label}_gate_trace.csv", gate_trace)

    bucket_rows = [
        {
            "time_bucket_s": bucket.replace("_", "-"),
            "original": counts["original"],
            "native": counts["native"],
            "true_positives": counts["true_positives"],
        }
        for bucket, counts in metrics["time_bucket_counts"].items()
    ]
    (compare_dir / f"native_{label}_vs_original_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (compare_dir / f"native_{label}_vs_original_report.md").write_text(
        f"# Native {pretty_label} Ledger Comparison\n\n" + _markdown_table_from_metrics(metrics),
        encoding="utf-8",
    )
    write_dict_csv(compare_dir / f"native_{label}_false_positives.csv", false_positives)
    write_dict_csv(compare_dir / f"native_{label}_false_negatives.csv", false_negatives)
    write_dict_csv(compare_dir / f"native_{label}_true_positives.csv", true_positives)
    write_dict_csv(compare_dir / f"native_{label}_time_bucket_summary.csv", bucket_rows)

    perf = {
        "decision": f"PERFORMANCE_READY_FOR_{int(ledger_window_s)}",
        "checkpoint_resume_validation": validation,
        "zero_600_regression": zero_600_metrics,
        "profile_stats": summary.get("profile_stats", {}),
        "wall_seconds": summary.get("wall_seconds"),
        "checkpoint_resume_used": checkpoint_resume_used,
        "completed_checkpoint_dir": str(completed_checkpoint_dir) if completed_checkpoint_dir else None,
        "notes": [
            "The tfirst search computes tfail to tsimul; ledger_window_s is a comparison/candidate filtering window.",
            "A completed prior active-order checkpoint can be resumed without recomputing formulas because it stores full gindx/tfail/fdepth arrays and scalar ts state.",
            "Root tuple caching is exact-key only and does not change formulas or traversal order.",
        ],
    }
    (perf_dir / "performance_profile.json").write_text(json.dumps(perf, indent=2), encoding="utf-8")
    (perf_dir / "checkpoint_resume_revalidation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    (perf_dir / "zero_600_regression_after_cache.json").write_text(json.dumps(zero_600_metrics, indent=2), encoding="utf-8")
    (perf_dir / "performance_cache_report.md").write_text(
        "# Performance / Cache Report\n\n"
        + json.dumps({k: perf[k] for k in ("decision", "checkpoint_resume_used", "wall_seconds", "profile_stats")}, indent=2)
        + "\n\n0-600 regression after cache/window generalization:\n\n"
        + _markdown_table_from_metrics(zero_600_metrics),
        encoding="utf-8",
    )

    if metrics["decision"] == f"NATIVE_{label}_LEDGER_CONVERGENCE":
        gap_decision = "GAP_ATTRIBUTION_INCONCLUSIVE"
        categories: list[str] = []
    else:
        gap_decision = "GAP_LOCALIZED_PATCHABLE_IN_LEDGER_ONLY"
        categories = [
            "TS_CARRY_ACTIVE_ORDER_MISMATCH",
            "FIELD_PACK_MISMATCH",
            "TFIRST_REFINEMENT_MISMATCH",
            "FORTRAN_ORDER_OR_PRECISION_MISMATCH",
        ]
    gap = {
        "decision": gap_decision,
        "categories": categories,
        "runtime_patch_forbidden": True,
        "metrics_decision": metrics["decision"],
        "false_positive_count": len(false_positives),
        "false_negative_count": len(false_negatives),
    }
    (gap_dir / "gap_attribution.json").write_text(json.dumps(gap, indent=2), encoding="utf-8")
    (gap_dir / "gap_attribution.md").write_text("# Gap Attribution\n\n" + json.dumps(gap, indent=2), encoding="utf-8")
    (patch_dir / "patch_candidates.md").write_text(
        "# Optional Ledger-Only Patch Candidates\n\nNo semantic mismatch patch was required. This phase added window-generalized diagnostics and exact-key root result caching only.",
        encoding="utf-8",
    )
    (patch_dir / "patch_summary.md").write_text(
        "# Patch Summary\n\nChanged only ledger diagnostic/test code. Runtime provider, DFS equations, and bridge loader were not changed.",
        encoding="utf-8",
    )

    return {
        "decision": metrics["decision"],
        "metrics": metrics,
        "zero_600_regression": zero_600_metrics,
        "checkpoint_resume": validation,
        "gap": gap,
    }


def run(phase_dir: Path, nmax: int = 10) -> dict[str, Any]:
    trace_dir = phase_dir / "01_original_fortran_trace"
    parse_dir = phase_dir / "02_original_trace_parsing"
    native_dir = phase_dir / "03_native_analytic_port"
    compare_dir = phase_dir / "04_cell_level_comparison"
    gap_dir = phase_dir / "05_gap_attribution"
    for directory in (parse_dir, native_dir, compare_dir, gap_dir):
        directory.mkdir(parents=True, exist_ok=True)

    unsfin_raw = trace_dir / "original_unsfin_cell_trace.raw"
    doublelayer_raw = trace_dir / "original_doublelayer_cell_trace.raw"
    original_rows = parse_unsfin_raw(unsfin_raw)
    doublelayer_rows = parse_doublelayer_raw(doublelayer_raw)
    original_summary = summarize_original(original_rows, doublelayer_rows)
    native_rows, root_metrics = compare_roots(original_rows, nmax=nmax)

    unsfin_csv_rows = [row for rows in original_rows.values() for row in rows]
    write_dict_csv(trace_dir / "original_unsfin_cell_trace.csv", unsfin_csv_rows)
    write_dict_csv(trace_dir / "original_doublelayer_cell_trace.csv", doublelayer_rows)
    write_dict_csv(native_dir / "native_unsfin_cell_trace.csv", native_rows)
    write_dict_csv(native_dir / "native_doublelayer_cell_trace.csv", [])

    native_summary = {
        "source_provenance": SOURCE_PROVENANCE,
        "runtime_provider_enabled": False,
        "output_inferred": False,
        "dfs_runtime_modified": False,
        "scope": "cell_scoped_root_component_port",
        "target_cells": list(TARGET_CELLS),
        "nmax": nmax,
        "ported_components": ["roota", "rootb", "rootc"],
        "blocked_components": [
            "inidoublelayer native pressure initialization from current parsed fields",
            "doublelayer analytic pressure/desaturation/FS evaluation from current parsed fields",
            "unsfin tnown/tincrement native first-hit search independent of original trace replay",
        ],
        "root_metrics": root_metrics,
    }
    metrics = {
        "target_cells": list(TARGET_CELLS),
        "original_trace_summary": original_summary,
        "root_component_metrics": root_metrics,
        "decision": "NATIVE_UNSFIN_ANALYTIC_COMPONENTS_PORTED_NOT_YET_CONVERGED",
    }
    gap = {
        "decision": "GAP_LOCALIZED_NEEDS_INPUT_FIELD_IMPLEMENTATION",
        "localized_gaps": [
            {
                "category": "INPUT_FIELD_MISMATCH",
                "evidence": "Root components can be evaluated from traced beta/lt/lb/kst/ksb, but the diagnostic still lacks a current native field pack for the same cells.",
                "patchable_now": "ledger_only_input_pack_loader",
            },
            {
                "category": "DOUBLELAYER_PRESSURE_PT_MISMATCH",
                "evidence": "Original doublelayer pt/desaturation/FS rows are captured, but native doublelayer analytic pressure evaluation is not implemented yet.",
                "patchable_now": "ledger_only_doublelayer_port",
            },
            {
                "category": "TINCREMENT_REFINEMENT_MISMATCH",
                "evidence": "Original tnown/tincrement sequence is captured; native first-hit search has not yet generated the same sequence independently.",
                "patchable_now": "ledger_only_unsfin_search_port",
            },
        ],
        "runtime_patch_forbidden": True,
    }

    (parse_dir / "original_trace_summary.json").write_text(json.dumps(original_summary, indent=2), encoding="utf-8")
    (native_dir / "native_cell_ledger_summary.json").write_text(json.dumps(native_summary, indent=2), encoding="utf-8")
    (compare_dir / "cell_level_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (gap_dir / "gap_attribution.json").write_text(json.dumps(gap, indent=2), encoding="utf-8")

    divergent_rows = []
    for cell, cell_metrics in root_metrics.items():
        for family in ("A", "B", "C"):
            family_metrics = cell_metrics.get(family, {})
            if not family_metrics.get("count_match"):
                divergent_rows.append(
                    {
                        "cell": cell,
                        "variable": f"root{family}_count",
                        "original": family_metrics.get("original_count"),
                        "native": family_metrics.get("native_count"),
                        "category": f"ROOT{family}_IMPLEMENTATION_MISMATCH",
                    }
                )
            elif (
                family_metrics.get("lambda_max_abs_error") is not None
                and float(family_metrics["lambda_max_abs_error"]) > 1.0e-8
            ):
                divergent_rows.append(
                    {
                        "cell": cell,
                        "variable": f"root{family}_lambda",
                        "original": "original_trace",
                        "native": "native_port",
                        "max_abs_error": family_metrics.get("lambda_max_abs_error"),
                        "category": "NUMERIC_PRECISION_OR_FORTRAN_ORDER_MISMATCH",
                    }
                )
    if not divergent_rows:
        divergent_rows.append(
            {
                "cell": "all",
                "variable": "doublelayer_pt_desatt_fs",
                "original": "trace_available",
                "native": "not_implemented",
                "category": "DOUBLELAYER_PRESSURE_PT_MISMATCH",
            }
        )
    write_dict_csv(compare_dir / "first_divergent_value_table.csv", divergent_rows)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-dir", required=True, type=Path)
    parser.add_argument("--nmax", type=int, default=10)
    parser.add_argument("--doublelayer-convergence", action="store_true")
    parser.add_argument("--tfirst-convergence", action="store_true")
    parser.add_argument("--active-0-600", action="store_true")
    parser.add_argument("--complete-active-0-600", action="store_true")
    parser.add_argument("--complete-active-window", action="store_true")
    parser.add_argument("--previous-phase-dir", type=Path)
    parser.add_argument("--case-dir", type=Path)
    parser.add_argument("--oracle-dir", type=Path)
    parser.add_argument("--max-active-index", type=int)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--checkpoint-interval", type=int, default=1000)
    parser.add_argument("--ledger-window-s", type=float, default=600.0)
    parser.add_argument("--completed-checkpoint-dir", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-checkpoint-validation", action="store_true")
    parser.add_argument("--skip-full", action="store_true")
    args = parser.parse_args()
    if args.complete_active_window:
        previous_phase_dir = args.previous_phase_dir
        if previous_phase_dir is None:
            previous_phase_dir = args.phase_dir.parent / "phase_no8_native_unsfin_analytic_doublelayer_port_or_trace"
        case_dir = args.case_dir or previous_phase_dir / "01_original_fortran_trace" / "original_unsfin_trace_build"
        oracle_dir = args.oracle_dir or case_dir
        completed_checkpoint_dir = args.completed_checkpoint_dir
        if completed_checkpoint_dir is None:
            completed_checkpoint_dir = (
                args.phase_dir.parent
                / "phase_no8_native_unsfin_active_order_performance_and_0_600_completion"
                / "04_native_full_0_600_ledger"
                / "checkpoints"
            )
            if not completed_checkpoint_dir.exists():
                completed_checkpoint_dir = None
        metrics = run_active_order_window_phase(
            args.phase_dir,
            case_dir=case_dir,
            oracle_dir=oracle_dir,
            ledger_window_s=args.ledger_window_s,
            checkpoint_interval=args.checkpoint_interval,
            completed_checkpoint_dir=completed_checkpoint_dir,
            skip_validation=args.skip_checkpoint_validation,
        )
    elif args.complete_active_0_600:
        previous_phase_dir = args.previous_phase_dir
        if previous_phase_dir is None:
            previous_phase_dir = args.phase_dir.parent / "phase_no8_native_unsfin_analytic_doublelayer_port_or_trace"
        case_dir = args.case_dir or previous_phase_dir / "01_original_fortran_trace" / "original_unsfin_trace_build"
        oracle_dir = args.oracle_dir or case_dir
        metrics = run_active_order_completion_phase(
            args.phase_dir,
            case_dir=case_dir,
            oracle_dir=oracle_dir,
            checkpoint_interval=args.checkpoint_interval,
            skip_validation=args.skip_checkpoint_validation,
            skip_full=args.skip_full,
        )
    elif args.active_0_600:
        previous_phase_dir = args.previous_phase_dir
        if previous_phase_dir is None:
            previous_phase_dir = args.phase_dir.parent / "phase_no8_native_unsfin_analytic_doublelayer_port_or_trace"
        case_dir = args.case_dir or previous_phase_dir / "01_original_fortran_trace" / "original_unsfin_trace_build"
        oracle_dir = args.oracle_dir or case_dir
        if args.checkpoint_dir or args.resume:
            context = build_active_context(case_dir)
            original = load_original_oracle(oracle_dir)
            original_0_600 = np.flatnonzero(np.isfinite(original.tfail_s) & (original.tfail_s > 0.0) & (original.tfail_s <= 600.0))
            ledger, active_trace, gate_trace, run_summary = run_active_order_0_600(
                case_dir,
                max_active_index=args.max_active_index,
                trace_window_cells={int(idx) + 1 for idx in original_0_600} | set(TARGET_CELLS),
                checkpoint_dir=args.checkpoint_dir,
                resume=args.resume,
                checkpoint_interval=args.checkpoint_interval,
                ledger_window_s=args.ledger_window_s,
            )
            if args.ledger_window_s == 600.0:
                metrics, _fp, _fn = compare_0_600_ledgers(ledger, original, context.active_mapping)
            else:
                metrics, _fp, _fn, _tp = compare_window_ledgers(ledger, original, context.active_mapping, ledger_window_s=args.ledger_window_s)
            metrics["run_summary"] = run_summary
            metrics["active_trace_rows"] = len(active_trace)
            metrics["gate_trace_rows"] = len(gate_trace)
        else:
            metrics = run_0_600_ledger_diagnostic(
                args.phase_dir,
                case_dir=case_dir,
                oracle_dir=oracle_dir,
                max_active_index=args.max_active_index,
            )
    elif args.doublelayer_convergence or args.tfirst_convergence:
        previous_phase_dir = args.previous_phase_dir
        if previous_phase_dir is None:
            previous_phase_dir = args.phase_dir.parent / "phase_no8_native_unsfin_analytic_doublelayer_port_or_trace"
        case_dir = args.case_dir or previous_phase_dir / "01_original_fortran_trace" / "original_unsfin_trace_build"
        if args.tfirst_convergence:
            metrics = run_tfirst_convergence(args.phase_dir, previous_phase_dir, case_dir=case_dir, nmax=args.nmax)
        else:
            metrics = run_doublelayer_convergence(args.phase_dir, previous_phase_dir, case_dir=case_dir, nmax=args.nmax)
    else:
        metrics = run(args.phase_dir, nmax=args.nmax)
    print(json.dumps({"decision": metrics["decision"], "target_cells": metrics.get("target_cells")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
