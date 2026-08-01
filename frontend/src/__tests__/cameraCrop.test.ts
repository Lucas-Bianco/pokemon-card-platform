import { describe, expect, it } from "vitest";

import { guideCropRect } from "../lib/cameraCrop";

describe("guideCropRect", () => {
  it("maps a centered guide into native pixels when the video is wider than the 3/4 frame", () => {
    // Frame is 3/4 portrait (300x400); a 1920x1080 landscape feed is cover-scaled
    // to fill the height and cropped on the sides.
    const crop = guideCropRect(
      { width: 300, height: 400 },
      // Guide: centered, 78% of the frame height, card aspect 2.5/3.5.
      { left: 38.5714, top: 44, width: 222.857, height: 312 },
      1920,
      1080,
    );

    // The cover scale is driven by the height (400/1080); the guide's 312px
    // height maps to ~842 native px, and its 222.857px width to ~602 native px.
    expect(crop.sx).toBeCloseTo(659.1, 0);
    expect(crop.sy).toBeCloseTo(118.8, 0);
    expect(crop.sw).toBeCloseTo(602.0, 0);
    expect(crop.sh).toBeCloseTo(842.4, 0);
    // The crop stays inside the native frame.
    expect(crop.sx + crop.sw).toBeLessThanOrEqual(1920);
    expect(crop.sy + crop.sh).toBeLessThanOrEqual(1080);
    expect(crop.sw).toBeGreaterThan(0);
    expect(crop.sh).toBeGreaterThan(0);
  });

  it("handles a portrait video in a landscape frame (cover crops top/bottom)", () => {
    // Frame 400x300 (4/3 landscape); video 1080x1920 (9/16 portrait). Cover scale
    // is driven by the width (400/1080); the video overflows top and bottom.
    const crop = guideCropRect(
      { width: 400, height: 300 },
      { left: 100, top: 50, width: 200, height: 200 },
      1080,
      1920,
    );

    const scale = 400 / 1080;
    const offsetY = (300 - 1920 * scale) / 2; // negative
    expect(crop.sx).toBeCloseTo(100 / scale, 5);
    expect(crop.sy).toBeCloseTo((50 - offsetY) / scale, 5);
    expect(crop.sw).toBeCloseTo(200 / scale, 5);
    expect(crop.sh).toBeCloseTo(200 / scale, 5);
    expect(crop.sx + crop.sw).toBeLessThanOrEqual(1080);
    expect(crop.sy + crop.sh).toBeLessThanOrEqual(1920);
  });

  it("is a no-op crop (full guide == full frame) when aspects match exactly", () => {
    // When the video and frame share an aspect, cover = contain = exact fit, so a
    // guide the size of the whole frame maps to the whole native frame.
    const crop = guideCropRect(
      { width: 300, height: 400 },
      { left: 0, top: 0, width: 300, height: 400 },
      600,
      800,
    );

    expect(crop.sx).toBeCloseTo(0, 5);
    expect(crop.sy).toBeCloseTo(0, 5);
    expect(crop.sw).toBeCloseTo(600, 5);
    expect(crop.sh).toBeCloseTo(800, 5);
  });

  it("clamps a guide that extends past the cover crop to the native frame", () => {
    // Absurd guide wider than the frame: the clamps must keep the source rect
    // inside [0, videoWidth] x [0, videoHeight] and never negative.
    const crop = guideCropRect(
      { width: 300, height: 400 },
      { left: -50, top: -50, width: 500, height: 600 },
      1920,
      1080,
    );

    expect(crop.sx).toBeGreaterThanOrEqual(0);
    expect(crop.sy).toBeGreaterThanOrEqual(0);
    expect(crop.sx + crop.sw).toBeLessThanOrEqual(1920);
    expect(crop.sy + crop.sh).toBeLessThanOrEqual(1080);
    expect(crop.sw).toBeGreaterThan(0);
    expect(crop.sh).toBeGreaterThan(0);
  });
});