// Toast notifications. The context DEFAULT is a noop so `useToast()` never throws
// when rendered without a provider — every existing test renders <App/> or a
// component directly (no provider) and thus fires ZERO toasts, so toast copy
// can never collide with their text assertions. Production wraps <App/> in
// <ToastProvider> (main.tsx). Toasts render via portal to document.body so they
// sit above all content; they are pure-text (icon + message + close X) with NO
// action buttons, so they can never collide with getByRole("button") queries.
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";

export type ToastTone = "info" | "success" | "warn";

interface ToastApi {
  toast: (message: string, tone?: ToastTone) => void;
}

const NOOP: ToastApi = { toast: () => {} };
const ToastContext = createContext<ToastApi>(NOOP);

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const toast = useCallback((message: string, tone: ToastTone = "info") => {
    const id = nextId++;
    setToasts((prev) => [...prev, { id, message, tone }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {createPortal(
        <div className="toast-stack" role="status" aria-live="polite">
          <AnimatePresence>
            {toasts.map((t) => (
              <motion.div
                key={t.id}
                className={`toast toast-${t.tone}`}
                initial={{ opacity: 0, y: 12, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.98 }}
                transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
              >
                <span className="toast-msg" role="alert">{t.message}</span>
                <button className="toast-close" aria-label="Dismiss notification" onClick={() => dismiss(t.id)}>×</button>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}