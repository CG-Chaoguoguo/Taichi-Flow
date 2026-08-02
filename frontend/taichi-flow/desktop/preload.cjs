const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("taichiFlowDesktop", {
  runtime: "electron",
  mode: process.env.TAICHI_FLOW_DESKTOP_URL ? "dev" : "production",
  apiUrl: process.env.TAICHI_FLOW_API_URL || "",
  selectDirectory: (options = {}) => ipcRenderer.invoke("taichi-flow:select-directory", options),
});
