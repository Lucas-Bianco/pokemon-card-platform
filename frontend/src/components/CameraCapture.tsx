import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent } from "react";

interface Props {
  onCapture: (image: Blob) => void;
  busy: boolean;
}

// A real card is 2.5 x 3.5in. The guide matches that ratio so a card lined up inside
// it arrives at the server already close to the shape rectification expects.
const CARD_ASPECT = 2.5 / 3.5;

export default function CameraCapture({ onCapture, busy }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const capture = useCallback(() => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
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

  return (
    <div className="camera">
      <div className="camera-frame">
        <video ref={videoRef} autoPlay playsInline muted />
        <div className="guide" style={{ aspectRatio: String(CARD_ASPECT) }} />
        <p className="guide-hint">Fill the box · dark background works best</p>
      </div>
      <button className="shutter" onClick={capture} disabled={busy}>
        {busy ? "Scanning…" : "Scan card"}
      </button>
    </div>
  );
}
