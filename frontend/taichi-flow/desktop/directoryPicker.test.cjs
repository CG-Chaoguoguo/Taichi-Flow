const assert = require("node:assert/strict");
const test = require("node:test");

const { createDirectoryPickerHandler } = require("./directoryPicker.cjs");

test("directory picker returns the selected folder", async () => {
  const calls = [];
  const handler = createDirectoryPickerHandler({
    showOpenDialog: async (options) => {
      calls.push(options);
      return { canceled: false, filePaths: ["C:\\Research\\Taichi-Flow"] };
    },
  });

  const result = await handler({}, { defaultPath: "C:\\Research" });

  assert.deepEqual(result, { canceled: false, path: "C:\\Research\\Taichi-Flow" });
  assert.equal(calls[0].defaultPath, "C:\\Research");
  assert.deepEqual(calls[0].properties, ["openDirectory", "createDirectory", "promptToCreate"]);
});

test("directory picker cancellation preserves an empty result", async () => {
  const handler = createDirectoryPickerHandler({
    showOpenDialog: async () => ({ canceled: true, filePaths: [] }),
  });

  assert.deepEqual(await handler({}, {}), { canceled: true, path: null });
});

test("directory picker rejects a UNC default path before opening the dialog", async () => {
  let opened = false;
  const handler = createDirectoryPickerHandler({
    showOpenDialog: async () => {
      opened = true;
      return { canceled: true, filePaths: [] };
    },
  });

  await assert.rejects(() => handler({}, { defaultPath: "\\\\server\\share" }), /不支持 UNC/);
  assert.equal(opened, false);
});
