import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";

import { guideCropRect } from "../lib/cameraCrop";

interface Props {
  onCapture: (image: Blob) => void;
  busy: boolean;
}

// A real card is 2.5 x 3.5in. The guide matches that ratio so a card lined up inside
// it arrives at the server already close to the shape rectification expects.
const CARD_ASPECT = 2.5 / 3.5;

export default function CameraCapture({ onCapture, busy }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const flashTimer = useRef<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Camera-ready gate: the shutter stays disabled and a "warming up" state is
  // shown until the video element has loaded metadata (videoWidth > 0). Without
  // this, tapping the shutter before the feed produced its first frame silently
  // no-ops because capture() bailed on the zero-dimension guard.
  const [ready, setReady] = useState(false);
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        // The overwhelmingly common cause is a non-secure context: getUserMedia is
        // simply absent over plain HTTP. Say so, rather than "camera unavailable".
        setError(
          window.isSecureContext
            ? "This browser has no camera API."
            : "Camera needs HTTPS. Open the https:// address, not http://.",
        );
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment", width: { ideal: 1920 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not open the camera.");
      }
    }

    void start();
    return () => {
      cancelled = true;
      if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const capture = useCallback(() => {
    const video = videoRef.current;
    const frame = frameRef.current;
    const guide = guideRef.current;
    if (!video || !video.videoWidth || !video.videoHeight) return;

    // The canvas dims default to the full native frame; if the guide and frame
    // can be measured, we instead capture ONLY the guide-box region — the card
    // the user aligned — by coordinate-mapping the on-screen guide rect into
    // the video's native pixel space (inverting the object-fit: cover transform).
    let sx = 0;
    let sy = 0;
    let sw = video.videoWidth;
    let sh = video.videoHeight;

    if (frame && guide) {
      const frameRect = frame.getBoundingClientRect();
      const guideRect = guide.getBoundingClientRect();
      if (frameRect.width > 0 && guideRect.width > 0) {
        const crop = guideCropRect(
          { width: frameRect.width, height: frameRect.height },
          {
            left: guideRect.left - frameRect.left,
            top: guideRect.top - frameRect.top,
            width: guideRect.width,
            height: guideRect.height,
          },
          video.videoWidth,
          video.videoHeight,
        );
        if (crop.sw > 0 && crop.sh > 0) {
          sx = crop.sx;
          sy = crop.sy;
          sw = crop.sw;
          sh = crop.sh;
        }
      }
    }

    const canvas = document.createElement("canvas");
    canvas.width = Math.round(sw);
    canvas.height = Math.round(sh);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);

    // Capture flash — a brief white fade over the frame so the user gets the
    // shutter feedback they expect from a native camera app.
    setFlash(true);
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlash(false), 180);

    canvas.toBlob(
      (blob) => {
        if (blob) onCapture(blob);
      },
      "image/jpeg",
      0.92,
    );
  }, [onCapture]);

  const pickFile = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (file) onCapture(file);
    },
    [onCapture],
  );

  if (error) {
    return (
      <div className="camera-error">
        <p>{error}</p>
        <p className="hint">You can still upload a photo instead:</p>
        <input type="file" accept="image/*" onChange={pickFile} disabled={busy} />
      </div>
    );
  }

  const warming = !ready;

  return (
    <div className="camera">
      <div className="camera-frame" ref={frameRef}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          onLoadedMetadata={() => setReady(true)}
        />
        <div
          className="guide"
          ref={guideRef}
          style={{ aspectRatio: String(CARD_ASPECT) }}
        />
        <div className="guide-corners" aria-hidden="true" />
        <p className="guide-hint">Fill the box · dark background works best</p>
        {warming && (
          <div className="camera-warming" aria-live="polite">
            <span className="warming-dot" />
            <span>Warming up camera…</span>
          </div>
        )}
        <div className={`camera-flash${flash ? " is-on" : ""}`} aria-hidden="true" />
      </div>
      <button
        className="shutter"
        onClick={capture}
        disabled={busy || warming}
        aria-busy={busy}
      >
        {warming ? "Warming up…" : busy ? "Scanning…" : "Scan card"}
      </button>
    </div>
  );
}