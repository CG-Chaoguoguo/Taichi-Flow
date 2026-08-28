# Taichi-Flow

[English](README.md) | [简体中文](README.zh-CN.md)

Taichi-Flow 是一个面向地形驱动流动与泥石流模拟的本地科研工作台。它由
React/Vite 的桌面导向界面、FastAPI 领域服务和基于 Taichi 的数值执行组成；
内部计算链保留原始 EDDA 文本算例语义，同时让项目、输入、方案、运行和结果
具备可追溯性。

## 当前状态

Taichi-Flow 处于 research preview 阶段。当前公开工作流用于本地、证据驱动的
模型配置和运行，不宣称与原 Fortran EDDA 实现数值等价。

当前仓库已在 Windows、Python 3.11、Taichi 1.7.4 和支持 CUDA 的 NVIDIA GPU
上验证 Chamoli 参考算例工作流。CPU 通过相同的运行时架构可用。

## 工作台能力

| 领域 | 能力 |
| --- | --- |
| 参考算例 | 只读预览和原子导入原始 EDDA 算例目录 |
| 输入 | 不可变 SHA-256 地址化上传、输入修订、活动绑定检查和运行时溯源 |
| 方案 | 版本化参数补丁、冻结的 EDDA 控制、参考算例归属、复制和队列 |
| 数值运行时 | Taichi CUDA 或 CPU 执行、预检、进度、终态和输出清单 |
| 结果 | 结果族浏览、单文件下载、zip 导出和元数据/审计 sidecar |
| 前端 | 项目工作台、地图化输入检查、Chamoli 控制暴露、分区编辑和结果导航 |

对导入的参考算例，配置归属是显式的：reference_case 方案保留已解析的 EDDA
控制快照，不会静默继承为其他案例族准备的全局默认值。

## Chamoli 参考算例支持

Chamoli 工作流是案例专属的兼容路径，并不承诺每个历史 EDDA 功能都可自由编辑。

| 状态 | Chamoli 行为 |
| --- | --- |
| 生产路径 | EDDA 配置预览/导入、活动栅格绑定、4 分区双层数据、触发滑坡栅格、输入指纹、方案控制、队列、CUDA/CPU 运行、输出清单和结果下载 |
| 运行时已消费 sidecar | 当冻结控制处于活动状态时，inflow.txt 与 outflow.txt 会被带入独立项目并记录为已消费 |
| 只读审计 | 原始开关与不应在工作台中任意修改的数值变体保持可见，作为审计信息 |
| 案例专属禁用路径 | Chamoli 关闭浅层滑坡模拟；触发滑坡源独立表示，而预计算 UNSFIN 路径对该源配置保持禁用 |
| 部分路径 | 部分泥石流/WFS 行为明确标记为 partial，而非表示为完整的原 EDDA 等价 |
| 未支持 | 障碍物模拟未支持；建筑物开关保留为已解析审计元数据，而不是生产求解器功能 |

隔离的 Chamoli 验收运行使用 748 x 715 网格和 41,069 个有效单元。CUDA 运行至
90 秒后完成 2,090 个步长，在 45 秒和 90 秒生成输出，并产生 42 个结果文件和
完整元数据清单。这证明了端到端工作台路径；它不是 14,400 秒全时长验收，也不是
网格单元级数值 parity 声明。

对于没有声明坐标参考系统的原始 ASCII 输入，导出会回退到 EPSG:4326。原生仿射
网格变换会被保留，但在将该回退视为权威地理配准前，用户必须提供经过验证的 CRS
元数据。

请参阅受版本控制的 [Chamoli 能力矩阵](docs/audit/chamoli_capability_matrix.md)，
了解从原始输入到运行时的覆盖范围和已知边界。

## 参考算例数据流

~~~text
原始 EDDA 算例目录（只读）
  -> 预览：解析 edda_in.txt、检查活动输入、计算指纹
  -> 提交：复制到独立项目目录并登记不可变输入
  -> 输入修订 + reference-case 参数模板
  -> 方案：冻结控制、稀疏案例本地覆盖、预检
  -> 队列 + Taichi 运行时配置（CUDA 或 CPU）
  -> 结果族、runtime-input manifest、provenance、下载和导出
~~~

预览或导入不会修改源目录，源目录路径也不会作为运行时参数保留。

## Windows 快速开始

### 前置条件

- Windows 10 或 Windows 11
- 推荐 Python 3.11；Taichi 1.7.4 支持 Python 3.9 至 3.13
- Node.js 20.19 或更高版本
- 推荐使用 NVIDIA CUDA 硬件加速；浏览器工作台本身不依赖 GPU

### 安装与启动

~~~powershell
git clone https://github.com/CG-Chaoguoguo/Taichi-Flow.git
cd Taichi-Flow

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Push-Location frontend\taichi-flow
npm ci
Pop-Location

.\scripts\start-dev.ps1
~~~

受管脚本会启动 FastAPI：
[http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)，
并启动工作台：[http://127.0.0.1:3000/projects](http://127.0.0.1:3000/projects)。

~~~powershell
.\scripts\stop-dev.ps1
~~~

如果需要指定运行时解释器，请在启动前设置 TAICHI_FLOW_PYTHON：

~~~powershell
$env:TAICHI_FLOW_PYTHON = "C:\Python311\python.exe"
.\scripts\start-dev.ps1 -NoBrowser
~~~

## 典型工作流

1. 打开项目页，选择“导入兼容算例”。
2. 选择包含 edda_in.txt 的原始 EDDA 目录，生成只读预览。
3. 确认活动输入、sidecar、分区、数值变体和导入指纹；提交到独立目标目录。
4. 查看导入方案；如需实验，先复制方案，再编辑该参考算例允许暴露的控制。
5. 运行预检，将方案加入队列，并选择 CUDA 或 CPU 运行时配置。
6. 在结果面板中检查运行溯源并下载结果族。

## 公共 API 摘要

REST 服务挂载在 /api 下，主要入口如下：

| 端点 | 用途 |
| --- | --- |
| POST /api/cases/imports/preview | 读取并审计兼容 EDDA 算例，不写入源目录 |
| POST /api/cases/imports/commit | 从已验证预览指纹原子创建独立项目 |
| GET /api/projects | 列出工作台项目 |
| POST /api/projects/{project_id}/scenarios | 使用参数补丁和可选 control_overrides 创建方案 |
| PATCH /api/projects/{project_id}/scenarios/{scenario_id} | 使用乐观版本控制更新方案 |
| GET /api/projects/{project_id}/results/{simulation_id} | 浏览模拟结果元数据和文件 |
| GET /api/health | 检查服务身份和就绪状态 |

[API 参考](docs/api_reference.md) 与
[架构说明](docs/architecture.md) 介绍完整的项目、修订、队列、模拟、结果、导出
和 WebSocket 契约。

## 仓库结构

~~~text
api/                         FastAPI 领域服务、算例导入、队列和运行时协调
edda/                        内部 EDDA 兼容数值实现
frontend/taichi-flow/        React/Vite 工作台和 Electron 集成表面
docs/                        架构、API、用户、开发和审计文档
examples/                    示例配置材料
scripts/                     受管本地开发辅助脚本
tests/                       回归与领域测试
~~~

## 贡献者验证

请在仓库根目录运行命令。执行会构造 FastAPI 应用的测试时，请使用可写的隔离状态
目录：

~~~powershell
$env:TAICHI_FLOW_STATE_DIR = "$PWD\.runtime\pytest-local"
python -m pytest tests\test_workbench_domain_api.py tests\test_workbench_scheduler.py tests\test_workbench_run_controls.py -q

Push-Location frontend\taichi-flow
npm test
npm run build
Pop-Location
~~~

进行 Chamoli 专项分析时，请先阅读
[能力矩阵](docs/audit/chamoli_capability_matrix.md)，再通过导入、预检、队列和结果
工作流验证同一算例。

## 文档

- [用户指南](docs/user_guide.md)
- [开发者指南](docs/developer_guide.md)
- [安装指南](INSTALL.md)
- [架构说明](docs/architecture.md)
- [API 参考](docs/api_reference.md)
- [Chamoli 能力矩阵](docs/audit/chamoli_capability_matrix.md)

## 科学边界

Taichi-Flow 保留并审计了部分原始 EDDA 语义，但功能可用性不等于科学等价性。不能
从解析器覆盖、完成的队列项、索引对齐输出数组或成功的 GPU 运行中推断 Fortran
parity。可复现比较需要匹配的算例、时长、输出步长、参考输出和明确的残差分析。
