# Chamoli 性能优化与 t=900 s 闭合测试报告

- **日期**：2026-08-28
- **范围**：仅 `t_end=900 s`、`tout=45 s`（20 帧）。完整 `simul=14400 s` 未跑，另行安排。
- **结论先行**：UI 生产路径 CUDA 跑完 900 s，体积守恒通过（相对误差 \(8.92\times10^{-7}\)）。**不声称 CUDA–Fortran 数值对等。** 墙钟约 1607 s，相对历史 CUDA t=900（2057.5 s）缩短约 22%。GPU 采样占用仍低（中位 7%）。侵蚀深度场相对 Fortran 体积比 1.27（历史窗口曾为 1.72）。

---

## 1. 测试环境与配置

| 项 | 值 |
|---|---|
| 主机 | Windows 10，Python 3.11.9（`Python311\python.exe`） |
| GPU | NVIDIA GeForce RTX 3080 Ti，12 GB |
| 后端 | `cuda_production_default`，Taichi 1.7.4，**fp32**（`default_fp=f32`，`fallback_active=false`） |
| 案例 | `C:\Users\Administrator\Desktop\EDDA_test_project\Chamoli-EDDA file\Chamoli-EDDA file\` |
| UI 项目 | `artifacts\chamoli_opt_ui_case_20260828` |
| 方案 / 模拟 | `Chamoli opt t900` / `sim-d74dcf626b4148ec9a3dee25925c1064` |
| 网格 | 748 × 715，41069 活动单元 |

### 1.1 与 Fortran `edda_in.txt` 对照（本窗口）

| 键 | Fortran | 本次 effective |
|---|---|---|
| `time.t_end` / simul | 14400 | **900**（窗口覆盖） |
| `time.dt_output` / tout | 45 | 45 |
| dtmin / dtmax / toldh / toldhp / wavemax | 1e-5 / 2 / 1 / 0.1 / 0.25 | 同 |
| rainsimul / infilsimul / fssimul | F / F / F | F / F / F（Auto → disabled） |
| inflow / outflow / debris / erosion / sepdepo | T | T |
| `compute.async_output` | — | True |
| `compute.numerical_observe_stride` | — | 20 |
| `compute.write_geotiff_frames` | — | True |

### 1.2 Chamoli 五变种（非 BJ 默认）

| 键 | 值 |
|---|---|
| `hydrology.dfs_face_flux_variant` | `arithmetic_mean_chamoli` |
| `hydrology.dfs_manningbar_variant` | `debrisflowmanning_cvtol` |
| `hydrology.dfs_dry_face_velocity_variant` | `zero_dry_face_chamoli` |
| `hydrology.dfs_artivis_variant` | `velocity_ratio_chamoli` |
| `hydrology.dfs_absubar_variant` | `signed_mean_chamoli` |

### 1.3 四区双层土

| 区 | 顶层 cvero | 顶层 K_sat | 底层 K_sat |
|---|---|---|---|
| 1 | 0.6 | 8e-6 | **2e-7** |
| 2 | 0.3 | 4e-6 | 9e-7 |
| 3 | 0.4 | 4e-6 | 9e-7 |
| 4 | 0.55 | 4e-6 | 9e-7 |

运行前 API 与日志核验：`spatial_zones` 四区已绑定；`fastapi.err.log` 出现 `Spatial zone system initialized successfully`、`Double-layer soil model initialized`、`Async result writer started (bounded queue=4)`、`TimeStepper initialized: t_end=900.0s … dt_output=45.0s`。

绑定资产：DEM / slope / zones / glacier / landslide / inflow / outflow / `edda_in.txt`。

---

## 2. 本轮性能优化（已合入代码）

无数值意图的优化：异步写盘线程（有界队列 4）、周期性输出 D2H 瘦身、守恒诊断按 `numerical_observe_stride=20` 采样、降雨 `from_numpy` 短路、标量读回打包。

热路径：短 kernel 合并、depo-velocity 捕获默认关闭、reject 诊断仅在拒步时展开。参数入口走现有 catalog + `ParameterModule`「运行时」分组。

CLI 对照（优化后、双精度窗口脚本 `_run_chamoli_window.py`）：t=45 CUDA 墙钟 **194.5 s**，Flow_depth max_abs **0.075856** / RMSE 0.00188，与历史 A/B 基线 0.076 一致，**无回归**。该脚本显式 `use_double_precision=True`，与 UI 生产 fp32 路径不同。

---

## 3. UI 正式跑：墙钟与占用

| 指标 | 优化前历史 CUDA t=900 | 本次 UI 生产 t=900 |
|---|---|---|
| 墙钟 | 2057.5 s（`chamoli_cuda_t900_zones`） | **1607 s**（15:51:17–16:18:04） |
| 接受 / 拒绝步 | — | 14682 / 1451（全部 `depth_change`） |
| 平均接受 dt | ~0.062 s | **0.0613 s** |
| 输出帧 | 20 | 20（16 族 ASCII + 中间 GeoTIFF） |
| 输出目录体积 | — | **2.18 GB**（约 109 MB/帧文本） |
| nvidia-smi GPU% | 诊断约 30%（优化前主循环） | 采样 min/mean/median/max = **0 / 8.6 / 7 / 44** |
| 显存 | — | 运行中约 3464 MiB |

异步写盘生效：输出体积随 `tout` 阶跃增加（约每 45 s 模拟时间 +108 MB），主循环未同步堵在 `np.savetxt`。GPU 中位占用仍低：后期接受 dt 增大后 kernel 发射密度下降，且 nvidia-smi 15 s 采样会抹平短脉冲。磁盘仍是文本 ASCII 主导；`write_geotiff_frames=True` 额外写了 20×3 张小 GeoTIFF。

---

## 4. 测试过程问题清单

1. **导入对话框字段互清**：先填目标目录/名称会清空源路径（React 受控输入），需回填源路径后再预览。未阻断导入。
2. **运行中检视器未切到进度视图**：方案徽章与底栏队列显示「运行中」，右侧「运行」页仍停在禁用的「加入模拟队列」。底栏队列可用。
3. **终端坞无日志**：UI 显示「暂无日志输出」，求解器 INFO 只在 `fastapi.err.log`。
4. **诊断卡截图视口**：检视器在宽布局最右侧，全页截图以 DEM 为主；闭合留档使用元素裁剪。
5. **CLI 双精度 t=45 与 UI fp32 t=45 残差不可直接对比**：见第 6 节。监控脚本首次因 CSV 列名失败，已修后重跑，不影响模拟。

---

## 5. 闭合：体积账本与守恒

来源：`numerical_diagnostics.json`，门槛 1e-3。

| 项 | UI 账本 (m³) | 说明 |
|---|---|---|
| 入流 | 42750 | 过程线 47.5 m³/s × 900 s。Fortran 全长 14400 s 积分为 **684000**；本窗口应对 42750。**一致。** |
| 侵蚀 | 9.607×10⁶ | 账本项；ASC 深度×30² 得到 6.958×10⁶，口径不同，不以账本/ASC 互代 |
| 沉积通量 / 沉积存储 | 7.241×10⁶ / 7.241×10⁶ | |
| 出流 | 0 | 至 900 s 波前未达出流单元（Fortran 同期 ASC 出流亦为后期量） |
| 降雨 / 入渗 | 0 / 0 | 开关关闭 |
| failure_source | 2.846×10⁷ | `fssimul=F`；等于触发滑坡库存诊断项，**不是** UNSFIN 注入 |
| 洪泛/流场存储 | 3.087×10⁷ | 含触发滑坡一次注入后的存水 |
| 源项合计 | 3.811×10⁷ | |
| 汇+存储 | 3.811×10⁷ | |
| 残差 / 相对误差 | −34 m³ / **−8.92×10⁻⁷** | **通过**（逐步最大相对误差 1.36×10⁻⁶，超限接受步 0） |
| 非有限值 | 全 0 | |
| 离散收敛 | `not_assessed` | 本轮未做网格加密 |

ASC 深度积分（cell 30 m × 30 m，相对 Fortran `results\`）：

| t (s) | 侵蚀体积比 | 沉积体积比 | 流深体积比 |
|---|---|---|---|
| 45 | 0.862 | 0.525 | 1.000 |
| 900 | **1.265** | 0.800 | 1.159 |

历史 `signed_mean_chamoli` 窗口 t=900 侵蚀比约 **1.72**。本次 UI 场积分侵蚀比为 1.27，方向仍是过侵蚀，幅度低于该历史点。沉积偏少（0.80）。流深体积比 1.16 含波前/峰值位置差，不是守恒失败。

---

## 6. 逐帧 ASC 残差（相对 Fortran `results\`）

全部 16 族、20 帧 `missing_count=0`。LS_Scar / faildph 全程 **pass**（`fssimul=F`）。**不声称 parity。**

### 6.1 流深焦点

| t (s) | Flow_depth max_abs (m) | RMSE | wet | pass 族数 |
|---|---|---|---|---|
| 45 | 65.87 | 1.108 | 2048 | 4 |
| 90 | 42.45 | 0.524 | 3278 | 4 |
| 315 | 55.86 | 0.779 | 6098 | 2 |
| 450 | 68.32 | 0.915 | 7000 | 2 |
| 540 | **71.92** | 0.824 | 7454 | 2 |
| 765 | 39.97 | 0.969 | 8425 | 2 |
| 900 | 36.27 | 0.933 | 8993 | 2 |

本窗口流深 max_abs 峰值在 **t=540 s，71.92 m**（位置/峰值滞后，非整场均匀偏差）。

对比：优化后 CLI 双精度 t=45 Flow_depth max_abs **0.076 m**。UI 生产 fp32 同帧为 65.87 m。二者求解器开关、精度与 native unsfin 注入路径不同，**不能**把 65.87 读成「优化引入回归」。

历史 CUDA t=900 全族流深曾报 51.05 / 35.02（不同变种批次）。本次 UI t=900 流深 36.27 / RMSE 0.933，落在同一量级。

### 6.2 t=900 十六族

| 族 | 状态 | max_abs | RMSE | wet |
|---|---|---|---|---|
| Flow_depth | residual | 36.27 | 0.933 | 8993 |
| Flow_velocity | residual | 21.68 | 1.644 | 6432 |
| Max_flow_depth | residual | 37.73 | 0.990 | 8993 |
| Max_flow_velocity | residual | 18.70 | 0.566 | 9016 |
| Erosion_depth | residual | 6.39 | 0.428 | 7747 |
| Deposit_depth | residual | 6.01 | 0.266 | 5354 |
| Total_depth | residual | 36.36 | 1.256 | 8993 |
| Cv | residual | 0.600 | 0.058 | 8883 |
| LS_Scar | pass | 0 | 0 | 0 |
| faildph | pass | 0 | 0 | 0 |
| SFdepth | residual | 51.05 | 3.429 | 4921 |
| DFdepth | residual | 52.56 | 3.755 | 5155 |
| FFdepth | residual | 0.141 | 0.002 | 234 |
| MaxSFdepth | residual | 51.05 | 2.424 | 8637 |
| MaxDFdepth | residual | 59.68 | 5.322 | 5199 |
| MaxFFdepth | residual | 5.94 | 0.120 | 8958 |

机器可读：`artifacts/chamoli_opt_ui_t900_grid_diff.json`。

---

## 7. 不收敛 / 未对等项（如实）

1. **CUDA ≠ Fortran 数值解**。流深/速度/侵蚀/分类场均有数十米级 max_abs。成因复合：fp32、平均接受 dt 0.061 vs Fortran ~0.377、面通量/干面/人工粘性虽已切 Chamoli 变种但仍有离散差、侵蚀–沉积源汇时序。
2. **过侵蚀**。t=900 ASC 侵蚀体积比 1.27（历史 1.72）。t=45 该比为 0.86（偏少），随后翻转到过侵蚀——与「前期贴合、后期发散」的既有判断一致。
3. **波前 / 峰值滞后**。流深 max_abs 在 t=45 已 65.9 m，t=540 达 71.9 m；湿单元数与 Fortran 不同。MaxDFdepth / SFdepth 同量级。
4. **平均 dt 偏小**。0.061 s vs Fortran 约 0.377 s；1451 次水深变化拒步。更小 dt 增加墙钟，且不能自动保证场对齐。
5. **入流过程线 `partial`**。五单元常流量已积到正确的 42750 m³，但单元注入与 Fortran 侧实现仍标为部分语义；全长 684000 m³ 只在 14400 s 才有意义。
6. **failure_source 账本语义**。`fssimul=F` 时 2.85×10⁷ m³ 是触发滑坡库存，不是失稳源通量。守恒用该项做闭合项，解读时不得当成「浅层滑坡被打开」。
7. **离散收敛未评估**。
8. **GPU 仍未吃满**。异步 I/O 去掉了同步写盘尖峰，但 15 s 采样 GPU 中位 7%。下一刀应针对 host 间隙与 kernel 粒度，而不是再加写盘线程。
9. **完整 14400 s 未跑**。出流体积、后期侵蚀比、入流 684000 m³ 对账都还没有正式窗口。

---

## 8. 建议

- 生产默认继续 **fp32 CUDA**；需要与 CLI 窗口脚本比残差时必须声明精度，或提供 fp64 对照档。
- 关闭或按族精简 `write_geotiff_frames`（ASCII 已占 ~109 MB/帧）。
- 修运行页状态机，使 `running` 显示进度；把求解器 INFO 接到终端坞。
- 侵蚀后期发散仍是数值主债，不在本次 I/O 优化范围内。
- 安排 14400 s 正式闭合时沿用本报告的账本口径（入流用过程线积分，不用 684000 硬套短窗口）。

---

## 9. 产物路径

| 产物 | 路径 |
|---|---|
| 本报告 Markdown | `docs/audit/20260828_chamoli_opt_t900_closure.md` |
| 本报告 HTML | `docs/audit/20260828_chamoli_opt_t900_closure.html` |
| 诊断 JSON | `…/outputs/sim-d74dcf626b4148ec9a3dee25925c1064/numerical_diagnostics.json` |
| 帧残差 | `artifacts/chamoli_opt_ui_t900_grid_diff.json` |
| GPU/磁盘采样 | `artifacts/chamoli_opt_ui_perf_monitor.csv` |
| 截图 | `docs/audit/screenshots/chamoli_opt_*.png` |
