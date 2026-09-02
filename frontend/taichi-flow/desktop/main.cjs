const { app, BrowserWindow, dialog, ipcMain, protocol, session, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { createDirectoryPickerHandler } = require("./directoryPicker.cjs");
const {
  contract,
  resolveDesktopMode,
  resolveRendererTarget,
  validateApiUrl,
  isTrustedRendererUrl,
  isAllowedExternalUrl,
} = require("./runtimePolicy.cjs");
const packageMetadata = require("../package.json");

const rootDir = path.resolve(__dirname, "..");
const distDir = path.join(rootDir, "dist");
const preloadPath = path.join(__dirname, "preload.cjs");
const iconPath = path.join(__dirname, "assets", "taichi-flow-dev.ico");
const desktopMode = resolveDesktopMode(process.env);
const rendererTarget = resolveRendererTarget(desktopMode, process.env);
const apiUrl = validateApiUrl(process.env.TAICHI_FLOW_API_URL);
const openDevTools = process.env.TAICHI_FLOW_OPEN_DEVTOOLS === "1";
const smokeMode = process.env.TAICHI_FLOW_DESKTOP_SMOKE === "1";
const smokeReportPath = process.env.TAICHI_FLOW_DESKTOP_SMOKE_REPORT || path.join(rootDir, "artifacts", "desktop-smoke-report.json");
const smokeScreenshotPath = process.env.TAICHI_FLOW_DESKTOP_SMOKE_SCREENSHOT || path.join(rootDir, "artifacts", "desktop-smoke.png");
const desktopExitReportPath = process.env.TAICHI_FLOW_DESKTOP_EXIT_REPORT || "";
const runtimeErrors = [];

let mainWindow = null;
let previewProtocolRegistered = false;
let requestedExitCode = 0;

protocol.registerSchemesAsPrivileged([
  {
    scheme: contract.desktopScheme,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
      stream: true,
    },
  },
]);

app.enableSandbox();
// The workbench's numerical CUDA path is independent of Chromium rendering.
// Prefer deterministic software composition so the desktop shell also starts
// on Windows hosts without a compatible Electron GPU DLL/driver.
app.disableHardwareAcceleration();

function recordRuntimeError(kind, details) {
  const entry = { kind, details, at: new Date().toISOString() };
  runtimeErrors.push(entry);
  process.stderr.write(`[Taichi-Flow desktop] ${kind}: ${details}\n`);
}

function exitApplication(code) {
  requestedExitCode = code;
  writeDesktopExitReport();
  app.exit(code);
}

function writeDesktopExitReport() {
  if (!desktopExitReportPath) return;
  fs.mkdirSync(path.dirname(desktopExitReportPath), { recursive: true });
  fs.writeFileSync(desktopExitReportPath, JSON.stringify({
    generatedAt: new Date().toISOString(),
    success: requestedExitCode === 0 && runtimeErrors.length === 0,
    exitCode: requestedExitCode,
    mode: desktopMode,
    runtimeErrors,
  }, null, 2), "utf8");
}

function previewContentType(filePath) {
  const extension = path.extname(filePath).toLowerCase();
  return {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".ico": "image/x-icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml; charset=utf-8",
    ".webp": "image/webp",
  }[extension] || "application/octet-stream";
}

function resolvePreviewFile(requestUrl) {
  try {
    const parsed = new URL(requestUrl);
    if (parsed.protocol !== `${contract.desktopScheme}:` || parsed.host !== contract.desktopHost) return null;
    const requestPath = decodeURIComponent(parsed.pathname || "/index.html");
    const relativePath = requestPath === "/" ? "index.html" : requestPath.replace(/^\/+/, "");
    const candidate = path.resolve(distDir, relativePath);
    const resolvedDist = fs.realpathSync(distDir);
    const rootPrefix = `${resolvedDist}${path.sep}`;
    if (candidate !== path.resolve(distDir) && !candidate.startsWith(`${path.resolve(distDir)}${path.sep}`)) return null;
    if (!fs.existsSync(candidate) || !fs.statSync(candidate).isFile()) return null;
    const realCandidate = fs.realpathSync(candidate);
    if (realCandidate !== resolvedDist && !realCandidate.startsWith(rootPrefix)) return null;
    return realCandidate;
  } catch {
    return null;
  }
}

function previewContentSecurityPolicy() {
  const apiOrigin = new URL(apiUrl).origin;
  const websocketOrigin = apiOrigin.replace(/^http:/, "ws:");
  return [
    "default-src 'self'",
    "base-uri 'none'",
    `connect-src 'self' ${apiOrigin} ${websocketOrigin}`,
    `img-src 'self' data: blob: ${apiOrigin}`,
    "font-src 'self' data:",
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "worker-src 'self' blob:",
  ].join("; ");
}

async function registerPreviewProtocol() {
  await protocol.handle(contract.desktopScheme, async (request) => {
    const filePath = resolvePreviewFile(request.url);
    if (!filePath) return new Response("Not found", { status: 404 });
    const headers = { "Content-Type": previewContentType(filePath) };
    if (path.extname(filePath).toLowerCase() === ".html") {
      headers["Content-Security-Policy"] = previewContentSecurityPolicy();
    }
    return new Response(fs.readFileSync(filePath), { status: 200, headers });
  });
  previewProtocolRegistered = true;
}

function senderUrl(event) {
  return event.senderFrame?.url || event.sender?.getURL?.() || "";
}

function assertTrustedSender(event) {
  const sourceUrl = senderUrl(event);
  if (!isTrustedRendererUrl(sourceUrl, desktopMode, rendererTarget)) {
    throw new Error(`Rejected desktop IPC sender: ${sourceUrl || "unknown"}`);
  }
}

async function fetchApiHealth(window) {
  const healthUrl = `${apiUrl}/api/health`;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const result = await window.webContents.executeJavaScript(`fetch(${JSON.stringify(healthUrl)})
      .then(async (response) => ({ ok: response.ok, status: response.status, body: await response.json() }))
      .catch((error) => ({ ok: false, status: 0, error: error instanceof Error ? error.message : String(error) }))`);
    if (result.ok) return result;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return { ok: false, status: 0, error: "API health did not become ready." };
}

async function fetchApiProjects(window) {
  const projectsUrl = `${apiUrl}/api/projects`;
  return window.webContents.executeJavaScript(`fetch(${JSON.stringify(projectsUrl)})
    .then(async (response) => ({ ok: response.ok, status: response.status, body: await response.json() }))
    .catch((error) => ({ ok: false, status: 0, error: error instanceof Error ? error.message : String(error) }))`);
}

async function waitForRendererReady(window, expectedProjectNames) {
  let snapshot = { ready: false, textLength: 0, serviceOnline: false, projectsReady: false };
  const startedAt = Date.now();
  let stableReadySamples = 0;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    snapshot = await window.webContents.executeJavaScript(`(() => {
      const text = document.body?.innerText || "";
      const expectedProjectNames = ${JSON.stringify(expectedProjectNames)};
      const projectsReady = expectedProjectNames.length > 0
        ? expectedProjectNames.every((name) => text.includes(name))
        : text.includes("暂无项目");
      const serviceOnline = Boolean(document.querySelector(".tf-service-status.online"));
      return {
        ready: serviceOnline && projectsReady && text.trim().length > 100,
        textLength: text.trim().length,
        serviceOnline,
        projectsReady
      };
    })()`);
    stableReadySamples = snapshot.ready ? stableReadySamples + 1 : 0;
    if (Date.now() - startedAt >= 3500 && stableReadySamples >= 4) {
      return { ...snapshot, stableReadySamples };
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return { ...snapshot, stableReadySamples };
}

async function runSmoke(window) {
  try {
    await new Promise((resolve) => setTimeout(resolve, 500));
    const apiHealth = await fetchApiHealth(window);
    const apiProjects = await fetchApiProjects(window);
    const expectedProjectNames = Array.isArray(apiProjects.body?.projects)
      ? apiProjects.body.projects.map((project) => String(project.name || "")).filter(Boolean)
      : [];
    const rendererReady = await waitForRendererReady(window, expectedProjectNames);
    const renderer = await window.webContents.executeJavaScript(`({
      title: document.title,
      url: location.href,
      textLength: document.body?.innerText?.trim().length || 0,
      desktopRuntime: Boolean(window.taichiFlowDesktop),
      desktopMode: window.taichiFlowDesktop?.mode || null,
      desktopVersion: window.taichiFlowDesktop?.version || null,
      apiUrl: window.taichiFlowDesktop?.apiUrl || null,
      apiContractVersion: window.taichiFlowDesktop?.apiContractVersion || null,
      directoryPickerBridge: typeof window.taichiFlowDesktop?.selectDirectory === "function",
      routeMode: location.hash ? "hash" : "browser"
    })`);
    fs.mkdirSync(path.dirname(smokeReportPath), { recursive: true });
    fs.mkdirSync(path.dirname(smokeScreenshotPath), { recursive: true });
    const screenshotParts = path.parse(smokeScreenshotPath);
    const viewports = [];
    for (const size of [{ width: 1024, height: 768 }, { width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
      window.setSize(size.width, size.height);
      await new Promise((resolve) => setTimeout(resolve, 250));
      const layout = await window.webContents.executeJavaScript(`({
        innerWidth,
        innerHeight,
        horizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        verticalOverflow: document.documentElement.scrollHeight - document.documentElement.clientHeight
      })`);
      const sizeScreenshot = path.join(screenshotParts.dir, `${screenshotParts.name}_${size.width}x${size.height}${screenshotParts.ext || ".png"}`);
      fs.writeFileSync(sizeScreenshot, (await window.webContents.capturePage()).toPNG());
      viewports.push({ requested: size, screenshot: sizeScreenshot, ...layout });
    }
    const apiContractMatches = apiHealth.body?.service_id === contract.serviceId
      && apiHealth.body?.api_contract_version === contract.apiContractVersion;
    const success = renderer.desktopRuntime
      && renderer.directoryPickerBridge
      && renderer.desktopMode === desktopMode
      && renderer.routeMode === "hash"
      && apiHealth.ok
      && apiProjects.ok
      && apiContractMatches
      && rendererReady.ready
      && runtimeErrors.length === 0
      && viewports.every((viewport) => viewport.horizontalOverflow <= 0);
    const report = {
      generatedAt: new Date().toISOString(),
      success,
      mode: desktopMode,
      target: rendererTarget,
      apiHealth,
      apiProjects: { ok: apiProjects.ok, status: apiProjects.status, count: expectedProjectNames.length },
      apiContractMatches,
      rendererReady,
      runtimeErrors,
      viewports,
      ...renderer,
    };
    fs.writeFileSync(smokeReportPath, JSON.stringify(report, null, 2), "utf8");
    exitApplication(success ? 0 : 1);
  } catch (error) {
    recordRuntimeError("smoke-failed", error instanceof Error ? error.stack || error.message : String(error));
    fs.mkdirSync(path.dirname(smokeReportPath), { recursive: true });
    fs.writeFileSync(
      smokeReportPath,
      JSON.stringify({ generatedAt: new Date().toISOString(), success: false, mode: desktopMode, runtimeErrors }, null, 2),
      "utf8",
    );
    exitApplication(1);
  }
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1024,
    minHeight: 700,
    title: "Taichi-Flow",
    icon: fs.existsSync(iconPath) ? iconPath : undefined,
    autoHideMenuBar: true,
    show: !smokeMode,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: [
        `--taichi-flow-mode=${desktopMode}`,
        `--taichi-flow-api-url=${apiUrl}`,
        `--taichi-flow-client-version=${packageMetadata.version}`,
        `--taichi-flow-api-contract=${contract.apiContractVersion}`,
      ],
    },
  });
  mainWindow = window;

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedExternalUrl(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (isTrustedRendererUrl(url, desktopMode, rendererTarget)) return;
    event.preventDefault();
    if (isAllowedExternalUrl(url)) void shell.openExternal(url);
  });
  window.webContents.on("will-redirect", (event, url) => {
    if (isTrustedRendererUrl(url, desktopMode, rendererTarget)) return;
    event.preventDefault();
    if (isAllowedExternalUrl(url)) void shell.openExternal(url);
  });
  window.webContents.on("will-frame-navigate", (event, url, _isInPlace, isMainFrame) => {
    if (isMainFrame && isTrustedRendererUrl(url, desktopMode, rendererTarget)) return;
    event.preventDefault();
    if (isMainFrame && isAllowedExternalUrl(url)) void shell.openExternal(url);
  });
  window.webContents.on("did-fail-load", (_event, code, description, validatedUrl, isMainFrame) => {
    if (isMainFrame) recordRuntimeError("did-fail-load", `${code} ${description} ${validatedUrl}`);
  });
  window.webContents.on("render-process-gone", (_event, details) => {
    recordRuntimeError("render-process-gone", JSON.stringify(details));
  });
  window.on("closed", () => {
    if (mainWindow === window) mainWindow = null;
  });
  if (openDevTools && !smokeMode) window.webContents.openDevTools({ mode: "detach" });
  if (smokeMode) window.webContents.once("did-finish-load", () => void runSmoke(window));
  void window.loadURL(rendererTarget).catch((error) => {
    recordRuntimeError("load-url-failed", error instanceof Error ? error.message : String(error));
    if (smokeMode) exitApplication(1);
  });
  return window;
}

const hasSingleInstanceLock = app.requestSingleInstanceLock();

if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });

  app.whenReady().then(async () => {
    app.setAppUserModelId("TaichiFlow.DesktopDev");
    if (desktopMode === "preview") {
      if (!fs.existsSync(path.join(distDir, "index.html"))) {
        throw new Error("Missing dist/index.html; run npm run build before preview mode.");
      }
      await registerPreviewProtocol();
    }
    session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
    session.defaultSession.setPermissionCheckHandler(() => false);
    const picker = createDirectoryPickerHandler({
      showOpenDialog: (options) => {
        const owner = BrowserWindow.getFocusedWindow();
        return owner ? dialog.showOpenDialog(owner, options) : dialog.showOpenDialog(options);
      },
    });
    ipcMain.handle("taichi-flow:select-directory", (event, payload) => {
      assertTrustedSender(event);
      return picker(event, payload);
    });
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  }).catch((error) => {
    recordRuntimeError("startup-failed", error instanceof Error ? error.stack || error.message : String(error));
    exitApplication(1);
  });
}

app.on("will-quit", () => {
  writeDesktopExitReport();
  ipcMain.removeHandler("taichi-flow:select-directory");
  if (previewProtocolRegistered) protocol.unhandle(contract.desktopScheme);
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
