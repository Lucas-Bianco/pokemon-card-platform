import type { ReactNode } from "react";
import {
  motion,
  useReducedMotion,
  type Variants,
  type Transition,
} from "framer-motion";

const EASE: Transition = { duration: 0.28, ease: [0.22, 1, 0.36, 1] };

export const pageVariants: Variants = {
  initial: { opacity: 0, y: 8 },
  enter: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

export const staggerContainer: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.04, delayChildren: 0.02 },
  },
};

export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: EASE },
};

export function PageTransition({
  id,
  children,
}: {
  id: string;
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      key={id}
      variants={pageVariants}
      initial={reduced ? { opacity: 0 } : "initial"}
      animate={reduced ? { opacity: 1 } : "enter"}
      exit={reduced ? { opacity: 0 } : "exit"}
      transition={EASE}
      style={{ width: "100%" }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerList({
  children,
}: {
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      variants={staggerContainer}
      initial={reduced ? "show" : "hidden"}
      animate="show"
      style={{ display: "contents" }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const reduced = useReducedMotion();
  if (reduced) return <div className={className}>{children}</div>;
  return (
    <motion.div
      variants={staggerItem}
      className={className}
      style={{ width: "100%" }}
    >
      {children}
    </motion.div>
  );
}

export function MotionCard({
  as = "div",
  className,
  children,
  ...rest
}: {
  as?: "div" | "button" | "a";
  className?: string;
  children: ReactNode;
  [key: string]: unknown;
}) {
  const reduced = useReducedMotion();
  if (reduced) {
    const Tag = as;
    return (
      <Tag className={className} {...rest}>
        {children}
      </Tag>
    );
  }
  const Tag = motion[as];
  return (
    <Tag
      className={className}
      whileHover={{ y: -4 }}
      whileTap={{ scale: 0.985 }}
      transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
      {...rest}
    >
      {children}
    </Tag>
  );
}