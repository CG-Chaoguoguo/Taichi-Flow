const { contextBridge, ipcRenderer } = require("electron");

function readArgument(name, fallback = "") {
  const prefix = `--${name}=`;
  const value = process.argv.find((argument) => argument.startsWith(prefix));
  return value ? value.slice(prefix.length) : fallback;
}

const apiContractVersion = Number(readArgument("taichi-flow-api-contract", "0"));

contextBridge.exposeInMainWorld("taichiFlowDesktop", Object.freeze({
  runtime: "electron",
  mode: readArgument("taichi-flow-mode", "preview"),
  apiUrl: readArgument("taichi-flow-api-url"),
  version: readArgument("taichi-flow-client-version"),
  apiContractVersion: Number.isFinite(apiContractVersion) ? apiContractVersion : 0,
  selectDirectory: (options = {}) => ipcRenderer.invoke("taichi-flow:select-directory", options),
}));
