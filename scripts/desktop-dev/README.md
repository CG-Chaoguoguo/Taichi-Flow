# Taichi-Flow Electron 前端开发入口

本目录是正式打包前的桌面开发入口。它组合现有 FastAPI、本库 React/Vite 前端和 Electron，不修改 `edda/` 或求解语义，也不创建桌面专用 UI 分支。

## 使用

- 在仓库根目录执行 `scripts\start-dev.ps1`：默认启动 Electron 开发窗口和 Vite HMR，不会打开外部浏览器。
- 需要旧的浏览器 presentation 时执行 `scripts\start-dev.ps1 -Browser`；只启动服务执行 `-ServicesOnly`（`-NoBrowser` 仍兼容）。
- 双击 `Start-Taichi-Flow-Desktop-Dev.bat`：启动 `dev` 模式（FastAPI + Vite HMR + Electron）。
- 命令行执行 `Start-Taichi-Flow-Desktop-Dev.bat preview`：先构建 `dist`，再通过 `app://taichi-flow` 加载编译产物，不启动 Vite。
- 异常退出后执行 `Stop-DesktopDev.ps1`：只处理状态文件中标记为本次入口拥有、且 PID、创建时间与命令指纹仍全部匹配的进程。

也可以在 `frontend\taichi-flow` 中运行 `npm run desktop`、`npm run desktop:dev`、`npm run desktop:preview` 或 `npm run desktop:smoke`。高级参数（端口、超时、DevTools、Smoke 证据路径）直接传给 `Start-DesktopDev.ps1`。

## 启动契约

启动器按以下顺序查找 Python：`TAICHI_FLOW_PYTHON`、仓库 `.venv`、当前 Conda 环境、`py -3.11`、其余可发现解释器。每个候选都必须是 Python 3.9–3.13，并通过 FastAPI、Uvicorn、Taichi 导入探针；Python 3.14 会被明确拒绝。API 进程启动时会设置 `PYTHONUTF8=1`，避免 Windows 默认代码页损坏中文方案名。

Electron 使用四个环境变量：

- `TAICHI_FLOW_DESKTOP_MODE=dev|preview`
- `TAICHI_FLOW_DESKTOP_URL`（仅 `dev`）
- `TAICHI_FLOW_API_URL`
- `TAICHI_FLOW_OPEN_DEVTOOLS=1`（可选）

端口只有在健康响应、API 契约、checkout 指纹、渲染器 CORS 和监听进程来源都一致时才会复用；Vite 的 `/api/health` 代理也必须指向选定 API。无关占用不会被结束，启动器会选择后续 100 个空闲回环端口中的一个。会话、PID 身份、创建时间、命令指纹、源版本、所有权和日志位于仓库 `.runtime\desktop-dev\`；陈旧记录不会被当作杀进程依据。

## 安全和验证

桌面窗口启用 `contextIsolation`、禁用 `nodeIntegration`、启用 renderer sandbox，只允许当前回环开发源或 `app://taichi-flow`。目录选择 IPC 会检查发送者，导航限制在当前应用，外链仅允许 HTTPS，权限请求默认拒绝。

运行启动器自测：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\desktop-dev\Test-DesktopDevLauncher.ps1
```

`-Smoke` 会验证真实 `/api/health`、桌面 bridge、HashRouter、API 契约，并输出 1024×768、1280×800、1440×900 三组截图及布局数据。

## 未来打包边界

正式发布仍按两个产物构建：Electron 客户端与独立的 Python/Taichi/GDAL 本地计算服务。两者通过 `runtime-contract.json` 的 API 契约版本组合发布；Python 环境、GDAL 和求解器不得进入 ASAR。

本阶段不接入 Forge，也不生成 ZIP、安装器或更新包。完成正式图标、Windows 代码签名和服务兼容矩阵后，再引入 Electron Forge，依次执行 package、内部 ZIP、签名安装器与更新发布。
