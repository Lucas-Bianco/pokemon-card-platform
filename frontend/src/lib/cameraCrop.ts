// Coordinate-mapping for the camera capture path. Kept as a pure function so the
// math — which is the heart of the "aligned card is what's sent" fix — can be
// unit-tested in jsdom without a real camera.

export interface FrameRect {
  width: number;
  height: number;
}

export interface GuideRect {
  /** Guide position relative to the frame, in CSS pixels. */
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface CropRect {
  /** Source rectangle in the video's native pixel space, for drawImage(). */
  sx: number;
  sy: number;
  sw: number;
  sh: number;
}

/**
 * Map the on-screen guide rectangle (in CSS pixels, relative to the camera
 * frame) into the video's native pixel space, accounting for `object-fit: cover`.
 *
 * `object-fit: cover` scales the video so the smaller dimension fills the frame
 * and crops the overflow, then centers the result. Without this mapping, the
 * canvas would draw the full uncropped video.videoWidth x videoHeight, so the
 * card the user lined up inside the on-screen guide would NOT be what gets
 * sent to the server. This inverts the cover transform so the guide rect
 * becomes a source-pixel crop window.
 */
export function guideCropRect(
  frame: FrameRect,
  guide: GuideRect,
  videoWidth: number,
  videoHeight: number,
): CropRect {
  // Cover scale: the larger of the two axis scales wins, so the video fills the
  // frame in the constrained dimension and overflows in the other.
  const scale = Math.max(frame.width / videoWidth, frame.height / videoHeight);
  // The centered overflow is split equally on both sides; these offsets are
  // negative in the overflowing dimension (the displayed video extends past the
  // frame on both sides there).
  const offsetX = (frame.width - videoWidth * scale) / 2;
  const offsetY = (frame.height - videoHeight * scale) / 2;

  // Frame-pixel guide rect -> native-pixel source rect.
  const sx = (guide.left - offsetX) / scale;
  const sy = (guide.top - offsetY) / scale;
  const sw = guide.width / scale;
  const sh = guide.height / scale;

  // Clamp to the native frame so a guide that runs past the cover crop (e.g. the
  // user's viewport reports a frame size that produces a slightly-outside
  // window) doesn't yield negative or oversized source dims — drawImage fills
  // missing source pixels with transparent, which would show as black borders.
  const sxClamped = Math.max(0, sx);
  const syClamped = Math.max(0, sy);
  const swClamped = Math.min(sw, videoWidth - sxClamped);
  const shClamped = Math.min(sh, videoHeight - syClamped);

  return { sx: sxClamped, sy: syClamped, sw: swClamped, sh: shClamped };
}