# Taichi-Flow 安装与验证指南

## 环境要求

- Python 3.9–3.13（Taichi 1.7.4；Python 3.14 目前不在支持范围）。
- Windows 10/11 是当前受管桌面工作流的已验证平台。Linux/macOS 可手动
  运行 FastAPI 和 Vite，但本仓库的 PowerShell/Electron 启动器尚未承诺跨平台。
- Node.js 22.12+、npm，以及 Electron 43.2.0（默认 UI 使用
  `frontend/taichi-flow`）。
- GPU 不是运行前提；无 CUDA 时使用 CPU 后端即可。大规模模拟建议至少
  8 GB RAM，并为结果目录预留额外空间。

## Python 安装

Windows 示例：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

开发和示例工具按需安装：

```powershell
pip install -e ".[dev]"
pip install -e ".[examples]"
```

也可以使用 `pip install -r requirements.txt` 安装核心依赖。GDAL 不属于
核心安装；只有需要额外的 GDAL/OGR 命令或特定矢量驱动时才安装：

```powershell
pip install -e ".[geospatial]"
```

核心栅格读写由 Rasterio 完成。

## 前端与服务

在仓库根目录执行：

```powershell
cd frontend\taichi-flow
npm ci
cd ..\..
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1
```

默认受管启动器会启动 FastAPI（`127.0.0.1:8000`）、Vite HMR
（`127.0.0.1:3000`）并打开 Electron。可选模式：

```powershell
# 在浏览器中展示 Vite 页面
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1 -Browser

# 只启动服务，不打开 UI；-NoBrowser 仍是兼容别名
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1 -ServicesOnly

# 停止由启动器创建的服务
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-dev.ps1
```

手动启动时，Vite 默认端口是 5173；如需与受管启动器一致，请显式指定
3000：

```powershell
# 终端 1
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000

# 终端 2
cd frontend\taichi-flow
npm run dev -- --host 127.0.0.1 --port 3000
```

API 健康检查：`http://127.0.0.1:8000/api/health`。浏览器入口通常为
`http://127.0.0.1:3000/projects`。

## 运行最小示例

仓库提供可跟踪的小型输入：

```text
examples/data/dev_tiny_dem.asc
examples/data/dev_rainfall.csv
```

配置文件可直接解析；正式模拟入口为：

```powershell
python -m edda.solver.edda_solver config_example.yaml
```

示例和测试产生的 `output/`、`output_example/` 属于本地生成目录，已由
`.gitignore` 排除。`artifacts/`、`outputs/`、`uploads/` 和 `.runtime/`
可能包含科研结果或运行证据，不能因为被忽略就递归删除。

## 验证

安装后运行：

```powershell
python -m pytest -q

cd frontend\taichi-flow
npm test
npm run test:desktop
npm run build
```

测试数量会随版本变化；验收以命令退出码和失败详情为准，不预设固定的
通过、跳过或容许失败数量。需要真实 CUDA 时再单独执行 GPU 探针；CPU
路径是公开支持的验证路径：

```powershell
python -c "import taichi as ti; ti.init(arch=ti.cpu); print('Taichi CPU initialized')"
```

## 常见问题

### Python/Taichi 版本不匹配

确认 `python --version` 在 3.9–3.13 范围内，并重新创建虚拟环境。Python
3.14 不应强行安装 Taichi 1.7.4。

### Windows 缺少 GDAL 驱动

核心模拟不要求单独安装 GDAL。只有使用 GDAL/OGR 特定驱动时才执行
`pip install -e ".[geospatial]"`，并按平台安装对应的系统库。

### CUDA 初始化失败

检查 NVIDIA 驱动和 `nvidia-smi`；若当前任务不要求 GPU，可在配置中选择
`compute.backend: cpu`，或在代码中使用 `ti.cpu`。

### 中文配置读取失败

`SimulationConfig.from_yaml` 和 `to_yaml` 均按 UTF-8 读写。若外部编辑器
仍保存为本地代码页，请将文件重新保存为 UTF-8；Windows 临时排查可设置
`PYTHONUTF8=1`，但不应依赖该环境变量替代正确编码。

### 构建后出现 Git 脏文件

确认使用 `npm run build` 而不是手工把 TypeScript 输出写回源目录。Vite
配置的编译产物位于忽略的 `node_modules/.cache/taichi-flow-tsc`，`dist/`
和 tsbuildinfo 也不应被提交。

## 可选开发工具

```powershell
pip install -e ".[dev]"
black edda tests
mypy edda
flake8 edda tests
```

本项目当前不安装或维护 Git pre-push hook；推送前请按仓库验收清单手动
检查索引、未跟踪文件和 clean archive。

## 版本边界

| 组件 | 支持/约束 |
| --- | --- |
| Python | 3.9–3.13 |
| Taichi | `>=1.7.4,<1.8.0` |
| NumPy | `>=1.24,<3` |
| Node.js | `>=22.12`（前端/桌面） |
| Electron | 43.2.0 |
| CUDA | 可选；CPU 为受支持后端 |

---

最后更新：2026-09-03
