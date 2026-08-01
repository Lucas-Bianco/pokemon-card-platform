"use client";

import { motion } from "framer-motion";
import {
  STACK_FRONTEND,
  STACK_BACKEND,
  STACK_FRONTEND_BLURB,
  STACK_BACKEND_BLURB,
  STACK_LOCAL_NOTE,
} from "./data";

/**
 * Stack — two chip columns (Frontend/Backend) with stagger reveal,
 * plus the local-compute note. Copy preserved verbatim.
 */
export function Stack() {
  const col = (title: string, blurb: string, chips: string[]) => (
    <motion.div
      className="stack-col"
      variants={{
        hidden: { opacity: 0, y: 18 },
        visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
      }}
    >
      <h3>{title}</h3>
      <p>{blurb}</p>
      <motion.div
        className="chips"
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: "-40px" }}
        variants={{
          hidden: {},
          visible: { transition: { staggerChildren: 0.06 } },
        }}
      >
        {chips.map((c) => (
          <motion.span
            key={c}
            className="chip"
            variants={{
              hidden: { opacity: 0, y: 10 },
              visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } },
            }}
          >
            {c}
          </motion.span>
        ))}
      </motion.div>
    </motion.div>
  );

  return (
    <section className="section" id="stack">
      <div className="wrap">
        <div className="section-head">
          <p className="eyebrow">Stack</p>
          <h2>Local-first by design.</h2>
          <p>Python on the backend where the CV/ML ecosystem lives; a PWA on the front so one codebase ships to phone and desktop.</p>
        </div>

        <motion.div
          className="stack-cols"
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.12 } },
          }}
        >
          {col("Frontend", STACK_FRONTEND_BLURB, STACK_FRONTEND)}
          {col("Backend", STACK_BACKEND_BLURB, STACK_BACKEND)}
        </motion.div>

        <motion.div
          className="stack-note"
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        >
          <strong>Runs entirely on your own machine.</strong> {STACK_LOCAL_NOTE}
        </motion.div>
      </div>
    </section>
  );
}