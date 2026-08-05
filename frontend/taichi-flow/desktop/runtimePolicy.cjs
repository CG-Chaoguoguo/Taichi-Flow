const contract = require("./runtime-contract.json");

const PREVIEW_TARGET = `${contract.desktopScheme}://${contract.desktopHost}/index.html`;
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

function parseUrl(value, label) {
  try {
    return new URL(String(value));
  } catch {
    throw new Error(`${label} must be a valid URL.`);
  }
}

function isLoopbackHttpUrl(value) {
  const parsed = parseUrl(value, "URL");
  return parsed.protocol === "http:" && LOOPBACK_HOSTS.has(parsed.hostname.toLowerCase());
}

function resolveDesktopMode(environment = process.env) {
  const explicitMode = String(environment.TAICHI_FLOW_DESKTOP_MODE || "").trim().toLowerCase();
  if (explicitMode) {
    if (explicitMode !== "dev" && explicitMode !== "preview") {
      throw new Error("TAICHI_FLOW_DESKTOP_MODE must be dev or preview.");
    }
    return explicitMode;
  }
  return environment.TAICHI_FLOW_DESKTOP_URL ? "dev" : "preview";
}

function resolveRendererTarget(mode, environment = process.env) {
  if (mode === "preview") return PREVIEW_TARGET;
  const configured = String(environment.TAICHI_FLOW_DESKTOP_URL || "").trim();
  if (!configured) throw new Error("TAICHI_FLOW_DESKTOP_URL is required in dev mode.");
  if (!isLoopbackHttpUrl(configured)) {
    throw new Error("TAICHI_FLOW_DESKTOP_URL must use a loopback HTTP origin.");
  }
  return parseUrl(configured, "TAICHI_FLOW_DESKTOP_URL").href;
}

function validateApiUrl(value) {
  const configured = String(value || "").trim();
  if (!configured) throw new Error("TAICHI_FLOW_API_URL is required.");
  const parsed = parseUrl(configured, "TAICHI_FLOW_API_URL");
  if (parsed.protocol !== "http:") {
    throw new Error("TAICHI_FLOW_API_URL must use HTTP.");
  }
  if (!LOOPBACK_HOSTS.has(parsed.hostname.toLowerCase())) {
    throw new Error("TAICHI_FLOW_API_URL must use a loopback host.");
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash || (parsed.pathname && parsed.pathname !== "/")) {
    throw new Error("TAICHI_FLOW_API_URL must be a loopback origin without credentials, path, query, or hash.");
  }
  return parsed.origin;
}

function isTrustedRendererUrl(candidate, mode, rendererTarget) {
  try {
    const parsed = new URL(candidate);
    if (mode === "preview") {
      return parsed.protocol === `${contract.desktopScheme}:` && parsed.host === contract.desktopHost;
    }
    return parsed.origin === new URL(rendererTarget).origin;
  } catch {
    return false;
  }
}

function isAllowedExternalUrl(candidate) {
  try {
    return new URL(candidate).protocol === "https:";
  } catch {
    return false;
  }
}

module.exports = {
  contract,
  PREVIEW_TARGET,
  resolveDesktopMode,
  resolveRendererTarget,
  validateApiUrl,
  isTrustedRendererUrl,
  isAllowedExternalUrl,
};
