const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { createDirectoryPickerHandler } = require("./directoryPicker.cjs");

const rootDir = path.resolve(__dirname, "..");
const distDir = path.join(rootDir, "dist");
const preloadPath = path.join(__dirname, "preload.cjs");
const smokeMode = process.env.TAICHI_FLOW_DESKTOP_SMOKE === "1";
const smokeReportPath = process.env.TAICHI_FLOW_DESKTOP_SMOKE_REPORT || path.join(rootDir, "artifacts", "desktop-smoke-report.json");
const smokeScreenshotPath = process.env.TAICHI_FLOW_DESKTOP_SMOKE_SCREENSHOT || path.join(rootDir, "artifacts", "desktop-smoke.png");

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1024,
    minHeight: 700,
    title: "Taichi-Flow",
    autoHideMenuBar: true,
    webPreferences: { preload: preloadPath, contextIsolation: true, nodeIntegration: false, sandbox: false },
  });
  window.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
  const target = process.env.TAICHI_FLOW_DESKTOP_URL || `file://${path.join(distDir, "index.html")}`;
  void window.loadURL(target);
  if (smokeMode) {
    window.webContents.once("did-finish-load", async () => {
      try {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        const report = await window.webContents.executeJavaScript(`({ title: document.title, url: location.href, textLength: document.body?.innerText?.trim().length || 0, desktopRuntime: Boolean(window.taichiFlowDesktop), directoryPickerBridge: typeof window.taichiFlowDesktop?.selectDirectory === "function", routeMode: location.hash ? "hash" : "browser" })`);
        fs.mkdirSync(path.dirname(smokeReportPath), { recursive: true });
        fs.mkdirSync(path.dirname(smokeScreenshotPath), { recursive: true });
        const screenshotParts = path.parse(smokeScreenshotPath);
        const viewports = [];
        for (const size of [{ width: 1024, height: 768 }, { width: 1280, height: 800 }, { width: 1440, height: 900 }]) {
          window.setSize(size.width, size.height);
          await new Promise((resolve) => setTimeout(resolve, 250));
          const layout = await window.webContents.executeJavaScript(`(() => { const footer = document.querySelector('[data-testid="sidebar-footer"]'); const settings = footer?.querySelector('button[aria-label="设置"]'); const toggle = footer?.querySelector('button[aria-label="折叠导航"], button[aria-label="展开导航"]'); const rect = (element) => element ? ({ x: element.getBoundingClientRect().x, y: element.getBoundingClientRect().y, width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height }) : null; return { innerWidth, innerHeight, horizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, settings: rect(settings), toggle: rect(toggle) }; })()`);
          const sizeScreenshot = path.join(screenshotParts.dir, `${screenshotParts.name}_${size.width}x${size.height}${screenshotParts.ext || ".png"}`);
          fs.writeFileSync(sizeScreenshot, (await window.webContents.capturePage()).toPNG());
          viewports.push({ requested: size, screenshot: sizeScreenshot, ...layout });
        }
        fs.writeFileSync(smokeReportPath, JSON.stringify({ generatedAt: new Date().toISOString(), viewports, ...report }, null, 2), "utf8");
        app.quit();
      } catch (error) {
        fs.mkdirSync(path.dirname(smokeReportPath), { recursive: true });
        fs.writeFileSync(smokeReportPath, JSON.stringify({ generatedAt: new Date().toISOString(), error: error instanceof Error ? error.message : String(error) }, null, 2), "utf8");
        app.exit(1);
      }
    });
  }
}

app.whenReady().then(() => {
  if (!fs.existsSync(path.join(distDir, "index.html")) && !process.env.TAICHI_FLOW_DESKTOP_URL) throw new Error("Missing dist/index.html; run npm run build first.");
  ipcMain.handle(
    "taichi-flow:select-directory",
    createDirectoryPickerHandler({
      showOpenDialog: (options) => {
        const owner = BrowserWindow.getFocusedWindow();
        return owner ? dialog.showOpenDialog(owner, options) : dialog.showOpenDialog(options);
      },
    }),
  );
  createWindow();
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on("will-quit", () => { ipcMain.removeHandler("taichi-flow:select-directory"); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
