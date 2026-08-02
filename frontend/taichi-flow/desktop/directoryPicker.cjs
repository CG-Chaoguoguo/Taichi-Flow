function isUncPath(value) {
  return String(value).replaceAll("/", "\\").startsWith("\\\\");
}

function createDirectoryPickerHandler(dialogApi) {
  return async (_event, payload = {}) => {
    const defaultPath = payload && typeof payload === "object" && typeof payload.defaultPath === "string"
      ? payload.defaultPath.trim()
      : "";
    if (defaultPath && isUncPath(defaultPath)) {
      throw new Error("目录选择器仅支持本机路径，不支持 UNC 或网络共享。");
    }
    const options = {
      title: "选择 Taichi-Flow 项目根目录",
      properties: ["openDirectory", "createDirectory", "promptToCreate"],
    };
    if (defaultPath) {
      options.defaultPath = defaultPath;
    }

    const result = await dialogApi.showOpenDialog(options);
    if (result.canceled || !result.filePaths?.[0]) {
      return { canceled: true, path: null };
    }
    const selectedPath = String(result.filePaths[0]);
    if (isUncPath(selectedPath)) {
      throw new Error("目录选择器仅支持本机路径，不支持 UNC 或网络共享。");
    }
    return { canceled: false, path: selectedPath };
  };
}

module.exports = { createDirectoryPickerHandler };
