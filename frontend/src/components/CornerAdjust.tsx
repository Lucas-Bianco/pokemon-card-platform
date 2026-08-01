import { useCallback, useEffect, useRef, useState } from "react";

type Point = [number, number];

interface Props {
  image: Blob;
  onSubmit: (corners: Point[]) => void;
  onCancel: () => void;
}

export default function CornerAdjust({ image, onSubmit, onCancel }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  // Fractions of the displayed image, so they survive any rescaling or rotation.
  const [points, setPoints] = useState<Point[]>([
    [0.2, 0.15],
    [0.8, 0.15],
    [0.8, 0.85],
    [0.2, 0.85],
  ]);
  const dragging = useRef<number | null>(null);

  useEffect(() => {
    const objectUrl = URL.createObjectURL(image);
    setUrl(objectUrl);
    // Revoking on unmount matters here: a scanning session creates one of these per
    // retry, and each holds a full-resolution phone photo.
    return () => URL.revokeObjectURL(objectUrl);
  }, [image]);

  const move = useCallback((event: React.PointerEvent) => {
    const index = dragging.current;
    const box = boxRef.current;
    if (index === null || !box) return;
    const rect = box.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    setPoints((prev) => prev.map((p, i) => (i === index ? [x, y] : p)));
  }, []);

  const endDrag = useCallback(() => {
    dragging.current = null;
  }, []);

  const submit = useCallback(() => {
    if (!natural) return;
    // Back to source-image pixels — the server rectifies against the original.
    onSubmit(points.map(([x, y]) => [x * natural.w, y * natural.h] as Point));
  }, [natural, points, onSubmit]);

  return (
    <div className="corner-adjust">
      <p className="hint">Drag the four dots onto the card's corners.</p>
      <div className="corner-box">
        {/* The stage is the image-bounding box; the surrounding .corner-box
            padding insets the stage from the device bezel so the 44px handles,
            centered on the stage edge at fraction 0/1, never collide with the
            safe-area. Pointer events live on the stage so coordinate mapping
            stays relative to the image, not the padded wrapper. */}
        <div
          ref={boxRef}
          className="corner-stage"
          onPointerMove={move}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          {url && (
            <img
              src={url}
              alt=""
              onLoad={(e) =>
                setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })
              }
            />
          )}
          <svg className="corner-overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
            <polygon
              points={points.map(([x, y]) => `${x * 100},${y * 100}`).join(" ")}
              fill="rgba(255,203,5,0.15)"
              stroke="var(--accent)"
              strokeWidth="0.6"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
          {points.map(([x, y], i) => (
            <button
              key={i}
              className="handle"
              style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
              onPointerDown={(e) => {
                dragging.current = i;
                // Capture the pointer so move events keep flowing to this element
                // even if the finger drifts off it, and the drag only ends on a
                // real up/cancel — not on pointerleave, which used to drop a drag
                // the moment the handle slid under the cursor.
                e.currentTarget.setPointerCapture(e.pointerId);
              }}
              aria-label={`Corner ${i + 1}`}
            />
          ))}
        </div>
      </div>
      <div className="actions">
        <button className="primary" onClick={submit} disabled={!natural}>
          Use these corners
        </button>
        <button onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}