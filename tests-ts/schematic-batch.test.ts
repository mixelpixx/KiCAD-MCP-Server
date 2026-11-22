import { describe, expect, it } from "vitest";
import { placedReferences } from "../src/tools/schematic-batch.js";

describe("batch placement reply", () => {
  it("names each placed reference once, in order", () => {
    // A power symbol sent without a reference comes back as #PWRnn; the caller
    // only learns the number from this line. A multi-unit part places one
    // entry per unit under one reference.
    expect(
      placedReferences([
        { reference: "U1" },
        { reference: "#PWR01" },
        { reference: "U1" },
        { reference: "#FLG01" },
      ]),
    ).toBe("U1, #PWR01, #FLG01");
  });

  it("skips entries without a reference", () => {
    expect(placedReferences([{}, { reference: "R1" }])).toBe("R1");
  });
});
