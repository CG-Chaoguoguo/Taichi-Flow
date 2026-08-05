import { describe, expect, it } from "vitest";
import {
  compareFilenamesNatural,
  filenameOrdinal,
  sortAssetsByFilename,
  sortFilesByFilename,
  sortRainfallFiles,
} from "./filenameSort";

describe("filenameSort", () => {
  it("extracts the trailing numeric ordinal from filenames", () => {
    expect(filenameOrdinal("ri1.asc")).toBe(1);
    expect(filenameOrdinal("ri16.asc")).toBe(16);
    expect(filenameOrdinal("rain_02_final.asc")).toBe(2);
    expect(filenameOrdinal("plain.asc")).toBeNull();
  });

  it("sorts like Windows Explorer natural order for ri1/ri2/ri10", () => {
    const files = [new File([""], "ri10.asc"), new File([""], "ri2.asc"), new File([""], "ri1.asc")];
    expect(sortFilesByFilename(files).map((file) => file.name)).toEqual(["ri1.asc", "ri2.asc", "ri10.asc"]);
    expect(sortRainfallFiles(files).map((file) => file.name)).toEqual(["ri1.asc", "ri2.asc", "ri10.asc"]);
  });

  it("sorts assets by name and keeps non-numeric names stable", () => {
    const assets = [{ name: "zone.asc" }, { name: "1.asc" }, { name: "alpha.asc" }, { name: "2.asc" }];
    expect(sortAssetsByFilename(assets).map((item) => item.name)).toEqual(["1.asc", "2.asc", "alpha.asc", "zone.asc"]);
    expect(compareFilenamesNatural("ri2.asc", "ri10.asc")).toBeLessThan(0);
  });
});
