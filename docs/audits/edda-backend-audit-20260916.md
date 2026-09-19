# EDDA 计算后端审计与修复记录

## 范围与结论

审计基线 `gpt-edda-switch-parity@506aa0571693b37a8d1f09139e6f1b62ced20dfa`；原版来源 `CG-Chaoguoguo/EDDA-Fortran@8b0b7cf4b64266f941ae87daaae7f86eaf7d7630`。修复分支 `audit/edda-parity-pro-20260916`，PR #3 指向 `Pro-Quick-Chat`。后者起点 `e159f266` 较旧，因此 PR 包含已有工作台改造；本次增量应与 `506aa057` 比较，不能把全部继承改动当作新修复。

数值及测试提交：`1f65a62b5cc5cb1663a221160947084a31d78bfe`。依赖修补提交：`0c23f4d06b2719583e61dce4f6bfbb554cf31b59`。未强推、未改写原分支、未合并或部署。

发现并修复五类可复现缺陷，但没有证据证明它们是历史残差的全部或唯一原因。上传的 FIX2/FIX3 汇总早于基线中已经存在的 F1–F8 修复；最新代码缺少新的完整轨迹指标。本次取得源码与汇总 CSV，没有取得对应冻结输入、原始逐帧 ASC、完整中间状态和原版可执行文件。局部契约通过不代表完整 Chamoli/NO8 收敛，更不代表已完成网格收敛研究。

## 历史残差复核

| 运行/末帧 | 结果族 | NSE | RMSE | 体积或总量比 |
|---|---|---:|---:|---:|
| FIX3 / 900 s | Erosion | 0.472846589 | 0.430723688 m | 1.675615102 |
| FIX3 / 900 s | Velocity | 0.875789432 | 1.453899450 m/s | 1.313553208 |
| FIX2 / 14400 s | Erosion | -9.153731847 | 2.206886933 m | 3.214363637 |
| FIX2 / 14400 s | Velocity | -11.708248384 | 1.402793280 m/s | 5.560641137 |

以上重新聚合自用户汇总 CSV，不是本次重新运行结果。FIX3 的侵蚀/速度 ratio 在 225 s 的采样帧已超出 0.9–1.1；45 s 采样间隔不能定位真正首次错误时间。历史预算接近机器精度仍伴随明显空间误差，说明“预算闭合”和“与参照轨迹相同”必须独立验收。change_ledger 与 github_change_ledger 内容哈希相同，不能重复计证据。原始输出几何/NoData 通过是既有报告结论，不是此次从原始栅格重验。

## N1：拒步后源项 Cv 未传入下一次入渗（P1，已修复）

原 Chamoli `dfs.F90:312` 用 `fh*(1-cv/cvstar)` 计算可入渗水；357–359 在 erosion OR separate-deposition 开关下写入 `cv`。此写入发生在后续拒步跳转前，因此下一次尝试读取的是保留的源项 Cv，而不一定是已提交 h/rho 对应的 Cv。原 Python 路径只保留局部 Cv，下一次从 accepted `fields.Cv` 读取，混淆了两个生命周期。

修复增加 `source_cv_carry` 及 valid Taichi fields，统一直接源项、普通入渗、Green-Ampt 路径的 Cv 选择。源项开启时记录 epsilon 截断后的 Cv，拒步保留，成功 commit 后失效；不提前改写 accepted Cv。

独立 gfortran 片段与实际 Taichi 源项测试：h=1、Cv=0.325、cvstar=0.65、rho=1536.25、Ks=10，dt 从 0.1 拒步缩至 0.05。Fortran 两次 `(hpred,Cv)` 分别 `(0.5,0.65)`、`(1.0,0.325)`；旧 Python 第二次仍为 hpred=0.5；修复为 1.0。高 Ks 只是刺激分支的合成测试参数，不是实测材料值。

因果边界：只有实际开启相关入渗/源项、发生拒步且可用水分支受到 Cv 影响，才能将其归因到某一历史运行。必须核对 effective config 和逐次尝试日志。

## N2：提前拒步仍执行后续阶段（P1，已修复）

原版 CFL 拒步与 depth 拒步分别在约 800/1056 行，早于 stormdrain 和分类最大值写入；volume 拒步约 1242–1247 行，晚于分类最大值。旧默认路径在 CFL/depth 失败后仍走后续计算。

修复在 CFL、depth 检查点立即返回，共用拒步清理辅助方法，保留合法的 Fortran 历史状态。volume 拒步仍保留此前分类最大值写入，避免把已正确修复的 F5 反向破坏。记录 `rejected_stage=cfl/depth/volume`，早返回不再依赖实验开关。测试分别验证三种阶段，不是所有拒步统一回滚。

未启用 drain 时，此项主要可能影响分类最大值；不能据此单独解释所有瞬时速度和侵蚀偏差。barrier 的首个失败面前缀副作用仍需专项 fixture。

## N3：checkpoint 遗漏 host 持久状态（P1，已修复）

只遍历 Taichi fields 无法保存 Python 标量和 NumPy 调度状态。已复现 `legacy_previous_face_cvbar_scalar=0.275` 保存后恢复为 0。slide1、一次性滑坡触发标记、调度 fired mask 等同样不应静默丢失。

新增独立 `edda/solver/restart_metadata.py`，使用无 pickle 的版本化 metadata 保存 face cvbar、触发标记、时间和调度数组/策略。恢复前验证 host metadata、配置摘要、形状和合法标记；恢复后使 host cache 失效，保留 accepted/rejected 计数。配置哈希不是输入文件内容哈希，仍必须绑定冻结的 Input Revision。

**兼容性变化：缺少新 metadata 的旧 DFS checkpoint 明确拒绝恢复，需要从冻结初始条件重跑。不能用猜测的默认值承诺等价续算。** 连续运行与完整分段续算的真实案例对照仍是后续验收门。

## N4：达到尝试次数上限却报完成（P1，已修复）

旧循环达到 max_nts 后正常返回，可能被既有服务层当作成功。修复使用 TimeStepper 的真实 dt_min 与恢复后的尝试计数；保存必要诊断后对未达终点的运行抛出 `max_nts_exhausted` 或 `incomplete_simulation`。沿用 API 既有 failed 通道，不改 UI 组件/状态协议。始终拒步的合成测试验证不会在 t=0 被报为完成。

## N5：分区加载失败静默退回均质土层（P1，已修复）

启用分区却缺少路径，或加载过程抛错，旧路径会退回均质材料，悄悄改变问题定义。现在明确抛出带原异常链的错误；明确选择均质模式的有效配置不受影响。历史报告分区检查已通过，因此此项是配置安全缺陷，不冒认为那些旧运行的已证实根因。

## 测试与构建证据

- 修复前，同一组修正后的复现测试：7 failed / 1 passed（另 5 项未纳入该基线选择）。
- 本地 Python 3.13 CPU：新增 13 项测试加既有 checkpoint 测试，共 14 passed，89.45 s。
- GitHub Actions Python 3.11 CPU：同一冻结补丁在 runs 35123467871、35123845897 分别通过 14 项。这两次 run 的总失败来自 npm 依赖更新，不是数值测试失败。
- Run 35124296266：已发布源码及依赖修复；前端测试、desktop 逻辑测试、`tsc -b && vite build` 均成功，npm audit 返回 0 条已知告警。此为 Web 生产包及 desktop 单元测试，不是 Windows 安装器、真实 Electron UI 验收或 CUDA 全案例验证。
- 本文落盘时更广泛的最终 PR 分片 CI 尚待检查；最终状态以 PR #3 的检查及 JUnit 为准，不将聚焦 14 项冒称全量测试通过。

## 构建失败分析与修复方案

1. 单进程扩大 Taichi 测试时本地 OOM/137。field/kernel 生命周期超出 Python 对象作用域，测试共用 Program 会积累状态。新增 autouse fixture 在测试前后调用项目 runtime reset 并 GC；只用于测试，不在生产步骤中 reset。最终 CI 按测试文件分四片、fail-fast=false、保存选择清单/JUnit，防止内存问题或局部成功遮蔽失败。
2. npm 10.9.8 更新锁文件出现 Arborist `edgesOut` null；只先执行 npm ci 后更新也复现。升级构建工具到 **npm 11.19.1** 后，针对 Vitest 的修补、兼容范围内 audit fix、重新 npm ci、测试及构建全部成功。永久 CI 固定该 npm 版本。未使用 --force、legacy-peer-deps 或删除锁文件绕过约束。
3. 原锁文件报告 3 个受影响包，涉及 Vitest/mocker 与 transitive nanoid；修补后的实际审计结果为 0。不是对应用完全无漏洞的保证，也与数值残差无直接因果关系。
4. 初期审计 workflow 自身出现上下文/YAML/补丁传输配置错误，属于本次 CI 搭建问题，不计入用户原项目漏洞。最终清理临时写权限流程/传输文件，只保留只读权限的常规 PR 构建。

## 架构与下一阶段验收

遵守 Project → Input Revision → Scenario → Simulation Run → Result Family/Export Job。物理改动只在 edda/solver，新增序列化模块独立于 UI，失败状态走既有 FastAPI 异常通道；React 组件、路由、样式未改写。原 F1–F8 已在审计基线中，不重复认领。

G0：固定输入哈希、effective config、代码 SHA、原版源码族/二进制/编译选项与输出口径。G1：运行本次三类拒步及重启测试，扩展 drain/barrier/出流/开关组合。G2：先跑 <=900 s，对 225 s 之前逐次细化 forcing → source → face → accumulate → classify → volume → commit 的首次分歧，记录候选/接受 dt、Cv/carry、cvbar、rhodepo、erodithick、fv 及预算。G3：通过后再跑完整 14400 s/NO8 历时，并对比连续与分段续算。G4：再验证 CUDA 性能和真实桌面界面/打包。

非有限值输入的全入口保护、barrier 首个 CFL 失败面的并行前缀、预算/快照积分口径、跨源码族及 GPU 规约差异仍需专项证明。无完整新运行数据时，不声称本次已提高历史 NSE 或消除全部残差。保持 PR 草稿，不自动合并。

## 复现

```bash
python -m pip install -r requirements.txt
python -m compileall -q edda api
python -m pytest -q tests/test_dfs_retry_state_audit.py tests/test_checkpoint_restart.py
cd frontend/taichi-flow
npm install --global npm@11.19.1
npm ci
npm test
npm run test:desktop
npm run build
npm audit
```

Fortran 片段测试需 gfortran；缺少时明确 skip。原版依据为固定 EDDA-Fortran 提交中的 Chamoli dfs.F90，尤其 312–359、782–800、1041–1056、1124–1132、1240–1247；Taichi reset 依据官方 https://docs.taichi-lang.org/api/taichi/#taichi.reset；Vitest 公告 https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9；npm 相似上游错误记录 https://github.com/npm/cli/issues/8261。
