const assert = require("node:assert/strict");
const test = require("node:test");

const {
  PREVIEW_TARGET,
  resolveDesktopMode,
  resolveRendererTarget,
  validateApiUrl,
  isTrustedRendererUrl,
  isAllowedExternalUrl,
} = require("./runtimePolicy.cjs");

test("desktop mode defaults to dev only when an explicit dev URL exists", () => {
  assert.equal(resolveDesktopMode({ TAICHI_FLOW_DESKTOP_MODE: "dev" }), "dev");
  assert.equal(resolveDesktopMode({ TAICHI_FLOW_DESKTOP_MODE: "preview" }), "preview");
  assert.equal(resolveDesktopMode({ TAICHI_FLOW_DESKTOP_URL: "http://127.0.0.1:3000" }), "dev");
  assert.equal(resolveDesktopMode({}), "preview");
  assert.throws(() => resolveDesktopMode({ TAICHI_FLOW_DESKTOP_MODE: "production" }), /dev or preview/);
});

test("dev renderer target must be an explicit loopback HTTP URL", () => {
  assert.equal(
    resolveRendererTarget("dev", { TAICHI_FLOW_DESKTOP_URL: "http://127.0.0.1:3001" }),
    "http://127.0.0.1:3001/",
  );
  assert.throws(
    () => resolveRendererTarget("dev", { TAICHI_FLOW_DESKTOP_URL: "https://example.com" }),
    /loopback/,
  );
  assert.throws(() => resolveRendererTarget("dev", {}), /TAICHI_FLOW_DESKTOP_URL/);
});

test("preview renderer uses the packaged custom protocol", () => {
  assert.equal(resolveRendererTarget("preview", {}), PREVIEW_TARGET);
});

test("API URL accepts only loopback HTTP origins", () => {
  assert.equal(validateApiUrl("http://127.0.0.1:8001"), "http://127.0.0.1:8001");
  assert.equal(validateApiUrl("http://localhost:8000/"), "http://localhost:8000");
  assert.throws(() => validateApiUrl("http://api.example.com"), /loopback/);
  assert.throws(() => validateApiUrl("https://127.0.0.1:8000"), /HTTP/);
  assert.throws(() => validateApiUrl("file:///tmp/api"), /HTTP/);
  assert.throws(() => validateApiUrl("http://127.0.0.1:8000/api"), /origin/);
  assert.throws(() => validateApiUrl("http://user@127.0.0.1:8000"), /origin/);
});

test("renderer navigation remains inside the selected runtime origin", () => {
  const devTarget = "http://127.0.0.1:3001/";
  assert.equal(isTrustedRendererUrl("http://127.0.0.1:3001/projects", "dev", devTarget), true);
  assert.equal(isTrustedRendererUrl("http://127.0.0.1:3002/projects", "dev", devTarget), false);
  assert.equal(isTrustedRendererUrl("app://taichi-flow/index.html#/projects", "preview", PREVIEW_TARGET), true);
  assert.equal(isTrustedRendererUrl("app://other/index.html", "preview", PREVIEW_TARGET), false);
});

test("only HTTPS links may leave the desktop shell", () => {
  assert.equal(isAllowedExternalUrl("https://www.electronjs.org/docs/latest/"), true);
  assert.equal(isAllowedExternalUrl("http://example.com"), false);
  assert.equal(isAllowedExternalUrl("file:///C:/secret.txt"), false);
  assert.equal(isAllowedExternalUrl("javascript:alert(1)"), false);
});
