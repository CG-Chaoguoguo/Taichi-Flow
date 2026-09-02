# Chamoli 优化科学性与可靠度审阅

- **日期**：2026-08-29
- **对象**：相对 HEAD `aa34929` 的未提交求解器热路径 / 输出管线 / 运行时参数改动
- **口径**：**不声称 CUDA–Fortran 数值对等。** 本报告审的是「优化是否改科学语义」以及「同代码开关回退下 GPU 占用是否上升」。
- **子审阅**：Grok 4.6 xHigh 并行三路——[DFS 热路径](b340d756-4623-4b4c-81de-5efb8115f52e)、[异步输出](9d8f17a0-baff-4cae-8c65-e5c5fd52dafd)、[EDDA 方法学](1623073a-3362-473c-b888-7e215557e1ee)。主审阅交叉核验 Fortran 行号后写入下表。

## 结论先行

1. **科学性**：本次优化不改变 Chamoli CUDA 的物理方程、接受/拒绝门、体积账本累积，以及五个 Chamoli 变体公式。A/B 两跑 4 帧 × 16 族 ASCII **逐格完全一致**（`n_diff=0`）。
2. **GPU 利用率**：同代码开关回退的 t=180 CUDA fp64 窗口上，OPT 与 BASELINE 墙钟与 GPU% **几乎相同**（419 s / 中位 38% vs 414 s / 中位 37%）。本窗口瓶颈是 **kernel 粒度与 host 发射间隙**，不是磁盘 I/O。
3. **方法学符合性**：五个 Chamoli 变体、`cvero→rhoero`、入流出流账本、`fssimul=F` 门禁仍对照 Chamoli `dfs.F90` 对应行。这是方法符合，不是数值 parity。
4. **未发现必须立刻修复的正确性缺陷。** 观测层有两处已知缺口（接受路径 `first_reject={}`；stride 会稀释诊断极值），不影响求解。

---

## 1. 审阅范围

| 项 | 值 |
|---|---|
| 仓库 | `C:\Users\Administrator\Desktop\Taichi-Flow` |
| Python | 3.11.9（`Python311\python.exe`） |
| GPU | NVIDIA GeForce RTX 3080 Ti，12 GB |
| Fortran 参照 | `...\Chamoli-EDDA file\dfs.F90`、`edda main program.F90` |
| 核心 diff | `dfs_dynamic_wave.py` +227、`edda_solver.py` +387、`async_result_writer.py` 新增、`result_exporter.py`、`sim_config.py` |
| A/B 窗口 | `t_end=180`、`tout=45`、4 帧、**fp64**（与 `_run_chamoli_window.py` 相同；UI 生产 t=900 为 fp32） |
| 不做 | 14400 s 全长；不改求解器功能 |

OPT：`async_output=on`、`stride=20`、depo-velocity / legacy 方向速度同步关闭。  
BASELINE 仿真：`async_output=off`、`stride=1`、`EDDA_CAPTURE_DEPO_VELOCITY=1`、`EDDA_SYNC_LEGACY_DIRECTIONAL_VELOCITY=1`。

---

## 2. DFS 热路径判定

| 改动 | 判定 | Fortran 证据 | 风险 | 说明 |
|---|---|---|---|---|
| `step_result_pack` 打包读回 | 数值不变 | `dfs.F90:797-801`、`1242-1247`（`goto 1000`） | 低 | 一次 `to_numpy` 读 `reject_flag` / `suggested_dt` / `max_wave_speed`，公式未改 |
| `volume_snapshot_pack` | 数值不变 | `dfs.F90:1137-1258`、`1240-1247` | 低 | 观测读回；不进入接受/拒绝 |
| `_finalize_volume_balance` 持久化误差标量 | 数值不变 | `dfs.F90:1240-1247` | 低 | 写给审计；重试仍用 `\|rel\|>0.001` |
| `_reset_candidate_step_scalars` | 数值不变 | `dfs.F90:797-801` | 低 | 融合原标量清零 + first-reject 复位 |
| 体积清零折入 `_accumulate_volume_balance` | 仅比特级 | `dfs.F90:1137-1235`（先 `tempvolume=0` 再累加） | 低 | 同序零化 + 单元累加；两 kernel 合一 |
| 体积计数折入 `_commit_step` | 仅比特级 | `dfs.F90:1251-1257` 后 `1274-1276` | 低 | 七个 total 拷贝再提交单元态 |
| depo-velocity 捕获默认关 | 数值不变 | Fortran 无此快照；生产速度是 `fv`（`:210-212`、`:1276`） | 低 | 只写诊断数组，不改 `fv_fortran` |
| 跳过 `_sync_legacy_directional_velocity` | 数值不变 | Fortran 无 `vdir_legacy` | 低 | 该场只写不读；`fv_fortran` 仍提交 |
| 接受路径 `first_reject={}` | 数值不变 | Fortran 无诊断 dict | 低 | 拒步仍调用 `get_first_reject_diagnostics()` |
| `_rholimit_seeded` / 降雨一次清零 / probe 宿主缓存 | 数值不变 | 降雨 `dfs.F90:231-249`；rholimit 每步重算是**既有**偏差（`:371`） | 低 | Chamoli `rainsimul=F` 下降雨保持零 |

**热路径总评**：优化不改变 Chamoli CUDA 科学语义。折叠体积 kernel 最多引入 IEEE 发射融合差异；本次 A/B 网格未出现任何非零差。

---

## 3. 输出管线判定

| 项 | 判定 | 证据 | 说明 |
|---|---|---|---|
| D2H 快照与写脏帧 | 安全 | `get_full_state` → `to_numpy`；入队再 `np.array(..., copy=True)`（`edda_solver.py:3249-3253`） | 写线程不复用 GPU/求解器缓冲 |
| 帧序与 flush | 安全 | 单写线程 FIFO；`run()` `finally` `close()` join | 队列满则反压，不覆盖 |
| 直接 `_output_results` | 安全 | writer 为 `None` 时同步落盘 | 单测路径不变 |
| `numerical_observe_stride` | 安全（物理） | 账本在 kernel 每候选步累积；stride 只决定 `get_volume_balance_snapshot()` | 拒步 / 输出帧 / 收尾强制观测 |
| 诊断极值 | 仅报告层风险 | `numerical_max_abs_relative_error` 只在采样步更新 | 可能漏记未采样接受步的中间超限；期末全局账本仍读 live kernel |
| ASCII `%.6f` | 数值安全 | 缓冲二进制 `np.savetxt` | Windows 可能 LF vs 旧 CRLF，解析值不变 |
| `PERIODIC_OUTPUT_FIELDS` 瘦身 | 安全 | 磁盘族仍读 `h/Cv/z/fv/max_*/fdepth/...` | 少拉诊断场，不改 EDDA ASCII |

---

## 4. Chamoli 变体与执行条件

| 项 | 判定 | Fortran | CUDA |
|---|---|---|---|
| `arithmetic_mean_chamoli` | 符合 | `:623` 面积加权 `hbar`；`:634` 面积均 `cvbar`（无水深权）；`:672` `frhobar=0.5*(ρi+ρnq)` | 同；两边薄层门仍在 |
| `debrisflowmanning_cvtol` | 符合 | 侵蚀 `:417-421` `cv>cvtol` 用 `debrisflowmanning`；面通量 `:667-670` 为空操作 | 侵蚀核同样切换；面通量跳过 BJ 指数 |
| `zero_dry_face_chamoli` | 符合 | `:735-737` 在符号翻转前把干上游速度置零 | 同序，`TOL=0.01` |
| `velocity_ratio_chamoli` | 符合 | `:720-732` `0.02|Δv|/(|vnq|+|vi|+1)`，对角 `/√2` | 同权同模板 |
| `signed_mean_chamoli` | 符合 | `:209-212` 由原始 `fv` 还原有符号 `vx,vy`，对角字面量 `0.707` | 无 `fvpredi2` 半缩放 |
| `cvero` → `rhoero` | 符合 | `:444`、`:572`；`:112` `cvglacier` 已注释；`rhodepo` 仍从 `cvstar` | 分区 `cvero_field`，`<0` 回退 `cvstar` |
| 入流/出流账本 | 符合（活动项） | 入流 `/cellareacal`；出流先采样后清空；`:1176-1241` | 同公式、相对误差 0.001 重试 |
| 四区双层土 | 符合 | 顶层 `kero/ctao/cvero/φ`；`ltstar<0` 用 `zfil`；`fssimul=F` 时底层不进 DFS | 区参数映射；DFS 只消耗可蚀厚度 |
| `fssimul=F` | 符合 | `unsfin` 仅当 `fssimul`（主程序 `:503`）；`triggerslide` 仍读入并一次注入 | Auto 关闭 failure-source；`triggerslide` 与 `fssimul` 解耦 |

HEAD 求解器 diff **没有改写**上述变体算术。既有 quirk（侵蚀屈服里残留标量 `cvbar`，`dfs.F90:394`）由默认兼容钩子模拟，不是本轮回归。

---

## 5. GPU 利用率 A/B（同代码开关）

脚本：`docs/audit/_run_chamoli_perf_ab.py`（1 s `nvidia-smi`）。产物：

- OPT：`artifacts/chamoli_ab_opt_t180/`
- BASELINE：`artifacts/chamoli_ab_baseline_t180/`
- 逐格 diff：`artifacts/chamoli_ab_opt_vs_baseline_t180.json`

| 指标 | OPT | BASELINE 仿真 | Δ |
|---|---|---|---|
| 墙钟 | **419.4 s** | **414.0 s** | OPT +1.3%（噪声量级） |
| GPU min / mean / median / p90 / max | 1 / 37.6 / **38** / 42 / 49 | 2 / 36.1 / **37** / 41 / 56 | 中位 +1 个百分点 |
| 显存 mean / max | 5234 / 5529 MiB | 5414 / 5743 MiB | OPT 略低（少诊断捕获） |
| 输出体积 | 435 MB（76 文件） | 435 MB | 同 |
| 接受步（time stepper） | 3985 步 / 4 帧 | 同窗口 | — |
| 写盘突发（约） | t≈164、250、332、414 s | t≈162、246、327、410 s | 均在输出时刻突增 |

**解释**：t=180 只有 4 个输出帧，磁盘时间远小于 400 s 求解。开关回退打开的 depo-velocity 全场拷贝与逐候选步体积读回，没有把 GPU 从「发射间隙」里救出来。1 s 采样下两跑都稳定在 **36–38%**，说明占用低的主因是 **短 kernel + host 生命周期**，不是 I/O。

对照：UI 生产 t=900 fp32 曾用 15 s 采样得到中位 7%——过粗，且含帧间空窗。本窗口 1 s 采样更接近真实计算段占用。历史 t=900 墙钟 2057 s → 1607 s 的缩短，**不能**用本次 t=180 开关 A/B 单独归因于 GPU 利用率上升；该缩短更可能来自多帧 I/O 重叠、fp32 路径或其他测量条件，而不是「kernel 更饱」。

对 Fortran t=45 `Flow_depth`：两跑 `max_abs=0.075856`，与历史双精度窗口一致。这是相对 Fortran 的残差，**不是** OPT–BASELINE 差。

---

## 6. 数值等价取证

`docs/audit/_diff_chamoli_ab_grids.py` 对 t=45/90/135/180 × 16 族逐格比较：

| 项 | 结果 |
|---|---|
| 缺失族-帧 | **0** |
| 非零差族-帧 | **0** |
| 判定 | **identical** |

「无数值影响」在本窗口的 ASCII 写出值上成立。热路径判定里「仅比特级」的体积 kernel 融合，**未**在 6 位 ASCII 网格上留下可测差。

---

## 7. 回归测试

复跑（Python 3.11）：

- `tests/test_dfs_dynamic_wave.py`
- `tests/test_numerical_diagnostics.py`
- `tests/test_dfs_boundary_outflow_audit.py`
- `tests/test_zone_double_layer_independence.py`
- `tests/test_runtime_io_optimizations.py`

完整套件：**101 passed**，1 warning（Taichi locale 弃用），耗时 1385 s。

---

## 8. 浏览器核验

开发栈：`TAICHI_FLOW_PYTHON=Python311`，`scripts/start-dev.ps1 -NoBrowser -SkipNpmInstall`。  
健康：`GET /api/health` → `healthy`，`active_simulations=0`。前端 `http://127.0.0.1:3000` HTTP 200。

方案：`chamoli_opt_ui_case_20260828` / `Chamoli opt t900`（已完成，参数只读属预期）。

| 核验 | 结果 |
|---|---|
| 「运行时」分组 3 项 | 可见。`异步写盘=true`，`守恒诊断采样间隔=20 步`，`写出中间 GeoTIFF=true` |
| 完成态可编辑 | 否（方案已完成，控件 disabled）。草稿方案上目录仍暴露为可编辑 catalog 项 |
| 数值运行诊断卡 | 渲染正常：cuda / f32，14682 接受 / 1451 拒绝，全局账本 −8.92e−7 通过 |
| 截图 | `docs/audit/screenshots/chamoli_opt_review_runtime_params.png`、`chamoli_opt_review_diagnostics_card.png` |

未改 UI 形态。

---

## 9. 总评

**优化是否影响科学性？** 否。方法学分支仍在；账本仍每步累积；A/B ASCII 全同。

**GPU 利用率是否因这些开关上升？** 在本次 t=180 同代码 A/B 上 **没有实质上升**。占用停留在约 37%。成因是 host 间隙与 kernel 粒度，不是磁盘。若要再抬占用，需要合并物理 kernel 或减少逐步 host 同步，而不是再关 I/O——后者已经不是本窗口的主项。

**计算后端是否达到可研究使用的方法学对齐？** 对 Chamoli **活动开关与命名变体**，CUDA 路径与 `dfs.F90` 引用行对齐。残差场（例如 t=45 流速 `max_abs≈27.7`）是既有离散/实现差距，不是本轮优化引入。继续使用「不声称 parity」口径。

**正确性缺陷（不修，仅列出）**

1. 接受路径不再返回完整 `first_reject` 字典——仅观测。
2. `numerical_observe_stride>1` 会稀释接受步守恒诊断极值；期末全局账本不受影响。
3. rholimit 一次播种 vs Fortran 每步重算（`dfs.F90:371`）是既有差异。

---

## 10. 测试结果

```
101 passed, 1 warning in 1385.38s (0:23:05)
```

警告仅 Taichi `locale.getdefaultlocale` 弃用，与本轮优化无关。
