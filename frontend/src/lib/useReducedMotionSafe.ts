import { useReducedMotion } from "framer-motion";
// framer's useReducedMotion returns boolean | null. Normalize to boolean so
// downstream `reduced ? ... : ...` is always deterministic (null → false).
export function useReducedMotionSafe(): boolean {
  return useReducedMotion() ?? false;
}