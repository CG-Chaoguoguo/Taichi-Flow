import { beforeEach, describe, expect, it } from "vitest";
import { useTaichiFlowStore } from "./taichiFlowStore";

describe("layerOrder", () => {
  beforeEach(() => {
    useTaichiFlowStore.setState({
      layerOrder: ["a", "b", "c"],
    });
  });

  it("reorders a layer before the drop target", () => {
    useTaichiFlowStore.getState().reorderLayer("a", "c");
    expect(useTaichiFlowStore.getState().layerOrder).toEqual(["b", "c", "a"]);
  });

  it("ignores unknown ids", () => {
    useTaichiFlowStore.getState().reorderLayer("missing", "a");
    expect(useTaichiFlowStore.getState().layerOrder).toEqual(["a", "b", "c"]);
  });
});
