# EDDA 后端审计续篇：剩余 CI 故障、输入身份与数值诊断

## 范围与证据边界

继续 PR #3（`audit/edda-parity-pro-20260916` → `Pro-Quick-Chat`），不另开 PR、不改写 `gpt-edda-switch-parity`、不自动合并。调查基线仍是 `506aa0571693b37a8d1f09139e6f1b62ced20dfa`；本次续审起点为 `c468af227834101eff8b99610d62e1612a9ae16c`。原版来源固定为 `EDDA-Fortran@8b0b7cf4b64266f941ae87daaae7f86eaf7d7630`。

上次 N1–N5（拒步 Cv carry、拒步阶段边界、checkpoint host 状态、未完成误报、分区失败静默回退）已经提交。本次不重复认领它们，详见同目录 `edda-backend-audit-20260916.md`。本次从 GitHub Actions 源码归档恢复 PR merge snapshot `e3f34589`，校验 SHA256 后在 Linux/Python 3.13/Taichi 1.7.4/CPU 上继续复现；没有 CUDA 设备。

用户上传 FIX2/FIX3 CSV 是历史运行，不能据此推导本次修复后的 NSE、RMSE 或速度提升。EDDA-Fortran 归档提供源码，没有完整冻结案例输入、原版可执行文件或逐帧输出。没有执行完整 Chamoli 900/14400 s、NO8 或 GPU 对照。本报告的“已修复”指具体反例及实现契约，不等于完整轨迹 parity。

## 上次 CI 的最终清点

Run `35124907573` 四片 JUnit 最终合计 **506 passed / 25 failed / 41 skipped，执行 572 项**。当时收集 587 项；第 3 片遇到 `--maxfail=10` 提前停止，因此不能把 572 当成全套测试数量，也不能把先前三片的 298/15/23 当最终总计。

新增两个机制复现集：输入身份测试修复前 **12 failed / 1 passed**；面所有权/通量诊断/分类的既有测试修复前 **6 failed / 2 passed**。这两组基线在当前环境实际运行并保存 JUnit，不仅依靠静态猜测。

## N6：native 输入路径与空间身份（P1/P2）

### 缺陷与修复

`native_unsfin/analytic_cell.py` 的两个入口直接用 `case_dir / paths[...]`。POSIX 不把 Windows 反斜线当分隔符，导致原版相对路径 `Data\\tutorial\\slope.asc` 无法读取。这是跨平台可运行性缺陷（P2），并非 Windows 历史残差的直接证明。

更重要的是，原代码只比较 slope、zone、ltstar 的有效值**数量**。数量相同但掩膜位置不同，依然可能将材料分区或土层厚度关联到错误的活动单元。原来的 probe packs 入口甚至只把这个数量比较写进诊断而不拒绝。空间错配属于科学输入身份缺陷（P1）。原读取器还会将 1.5 截断成 zone 1，接受 NaN 和不匹配的声明行列数。

新增独立 `edda/solver/native_unsfin/input_grid.py`：

- 仅在文件系统边界转换旧相对路径分隔符，保留解析配置原文及其 provenance；支持空格、成对引号、native 绝对路径。
- 拒绝空路径、NUL、含混 drive-relative/root-relative 路径、UNC，以及 POSIX 上需要显式映射的 Windows 盘符；不存在的文件明确报错，不寻找同名替代文件、不回退默认值。
- 严格验证六行 ASCII header、有限数值、矩形 payload、声明尺寸、正 cellsize、完整 origin；支持 UTF-8 BOM。整数分区不能被截断。
- 按一基 `(row,col)` 返回活动顺序。两个消费入口共享同一加载函数，同时比较有序活动坐标和物理网格几何；`xllcenter/yllcenter` 先转换为 corner 进行身份比较。
- 不重采样、不填洞、不改变任何有效输入的数值或物理参数。

这是比旧 Fortran 中部分仅用 cell count 的检查更严格的输入保护，**不是声称原版已有完全相同的检查**。合法原版数据的值与顺序保持不变；无法证明同一网格的输入明确拒绝。该修复只覆盖 native UNSFIN 的两个加载入口，不冒称通用 DEM、全部 API 或所有外部栅格入口已完成同类治理。

### 验证

同数量不同 mask、错位 origin、同数量不同 shape、非整数 zone、NaN、声明尺寸不符均有失败先行测试；覆盖两个消费者、两种分隔符、空格、BOM、等价 center/corner、缺文件、含混路径与外来盘符。既有 analytic 解析测试同时通过，原始路径字符串的断言保留。

## N7：面所有权模式的 host/kernel 顺序冲突（P2，条件性）

内核支持默认较小 cell ID 和显式实验性较大 cell ID 两种面所有权。host `_ensure_legacy_fortran_order_face_pairs()` 却总按较小 ID 建索引，且比较不严格。反向 owner 内核给出 `assignment_order=22`，host 仅记录另一方向的 `10`，于是抛出 `Kernel cvbar assignment order 22 has no unique Fortran face pair`。

修复使 host 使用与实际 kernel 完全相同的严格比较及 frozen owner flag，排除 self-edge，保持 `source_cell_id*8+direction` 编号。默认生产面的选取规则不变，不吞掉未知 assignment order 异常。

验证包括既有实际 step 回归，以及两种 owner 的方向、编号、CFL stop 之前不应写 carry、合法 assignment 的 Cvbar 和非法编号仍报错。**没有证据表明历史 FIX2/FIX3 开启了反向 owner；不能将本项说成全部历史残差根因。**

## N8：f64 字段下的通量诊断仍以 f32 局部变量累加（P2，条件性）

`_diagnostic_qnet_qmassnet_accumulation_kernel` 使用 `qnet=0.0`、`qmassnet=0.0`。当 Taichi 默认标量精度为 f32 时，即使输入字段和输出 scratch 为 f64，局部变量仍可按 f32 累加。主计算 `_accumulate_and_check` 已明确使用 f64，导致观测路径和可选 mutation gate 不能逐位闭合。

修复只把两个局部累加器显式类型设为 `ti.f64`，与主计算一致。没有放宽 mismatch 检查或科学容差、没有启用实验 mutation、没有改变主计算的默认算法。

四个既有诊断/mutation 回归通过，包含 blocked/weighted faces 和最终状态不变；新增默认 f32/显式 f64 字段的消去误差反例 `[1e8,1,-1e8,0.1,0.2,...]`，与独立 Python 双精度串行顺序求和逐项精确相等。此处的 Python 求和是 dtype/顺序契约，不被包装成完整 Fortran oracle。

## 不是通过修改生产物理来“修好”的测试问题

| 失败类 | 证据与处理 | 明确没有做什么 |
|---|---|---|
| 源项调度 | 原 1 m 合成格上 dt=1 s 真实 CFL 拒步，阈值约 0.303 s。成功路径 fixture 改为一致 30 m 合成格；新增保留 1 m 的真实拒步 → 更小候选步测试，只在接受后推进时间，最终两源各提交一次，深度累计 0.6、质量与规定密度一致 | 未禁用 CFL、未强制接受、未放宽阈值、未把 consumed_count 当 committed_fired_count |
| 时间推进 harness | 构造真实最小 SimulationConfig 并调用基类 __init__；physics/output/probe I/O 为明确测试替身。保留 used_dt、next_dt、tempdt、retry、输出边界及无重复终帧断言 | 未修改生产 run()/完成门禁 |
| 目录 API | 更新到当前目录/文件分列的 kind/size/files 合约及 path_not_found；继续验证越界、UNC、文件非目录和 PermissionError | 未删除 UI 使用的字段或恢复旧接口 |
| 分区表 | 按 28 列命名顺序逐列检查，新增 ctao/cvero 的不同值与缺省 sentinel；保留 f64 与转置约定 | 未截掉最后两列、未仅改 shape 数字 |
| 时间浮点 | 十次 0.1 的统计值改用绝对容差 1e-15，rel=0 | 未修改物理时间控制、CFL、NSE 或质量容差 |
| SF/DF 分类 | 已在 F5 移到 pre-outflow，旧测试错误地搜索 commit 源码。改为实际调用分类内核并断言 commit 不覆盖既有 SF/DF/FF 结果 | 未把分类再移回提交之后 |

新 1 m 重试测试的步长缩减属于受控测试驱动，不冒称逐步重放生产时间控制器；生产时间控制器仍由独立时间 harness 和既有测试约束。

## CI 完整性改进

新增 `scripts/edda_audit_ci.py`，按收集到的完整 pytest node ID 排序分为四个互斥分片，不再让整个大 DFS 文件挤在一片，也不再 `--maxfail=10` 截断。每片保存源码 SHA、完整收集集合、选择集合、真正完成的 node ID、outcome、exit code 与 JUnit。

独立 inventory job 要求：四片齐全、同一源码/收集集合、每项恰好执行一次、JUnit 数量一致、无失败或 error。缺失/重复/提前终止/混合版本证据有独立单元测试。skip 保留为 skip，不算通过；没有将任何失败改成 xfail/skip。

永久 PR CI 保持 `contents: read`，前端依然 npm ci → tests → desktop-logic tests → tsc/Vite build → npm audit，固定先前实际验证的 npm 11.19.1。另加入 Windows 原生输入及目录接口回归。临时依赖取回及补丁传输工作流已清理，不保留自动写分支的流程。

## 本地复核与最终验收状态

本地已通过：原失败相关 DFS 8 项；schedule 成功路径 4 项；新增 real-retry/owner/dtype 4 项；native 25 项（随后增加路径边界案例）；时间 harness 4 项；CI inventory 8 项。各选择有重叠，**不能简单相加称为独立总数**。最终全套数字、源码 SHA 和构建链接以 PR #3 的本轮完成评论及覆盖清单为准。

本轮九个已有文件的修改通过 SHA256 校验与本地已测字节一致，提交 `02ffdb92ee20cd8d5cd32f6686722068eccc4b40`。一次临时压缩补丁传输校验失败，未写入科学代码；改用可读迁移并逐文件校验成功。这是本次交付工具链问题，不归因于仓库求解器。

```bash
python -m compileall -q edda api scripts
python scripts/edda_audit_ci.py run --index 0 --count 4 --output audit-ci
# 其余三个分片分别 index=1,2,3；汇总各片产物后：
python scripts/edda_audit_ci.py verify audit-ci --count 4
```

本地 CPU 回归和跨平台 CI 是工程门，不替代科学门。继续冻结 source family/输入内容哈希/effective config/编译器与二进制，先在 <=900 s 捕获 **首次不同的候选阶段**，同时导出 Cv/carry、rhodepo、erodible carry、cvbar 来源、八面通量、CFL/depth/volume 判据和接受/拒绝事件。900 s 的同口径全族门通过后才开展 14400 s；另验连续/重启及 CUDA。在没有这些真实运行证据前保持 PR draft，不声称数值全收敛。
