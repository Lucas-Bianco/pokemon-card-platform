"use client";

import { useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";

/**
 * Problem — reveal-on-scroll prose with a subtle parallax accent shape.
 * Copy preserved verbatim from docs/index.html.
 */
export function Problem() {
  const ref = useRef<HTMLElement | null>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  // Parallax drift on the accent shape — disabled effect under reduced motion
  // is handled by the CSS media query (the shape is decorative, pointer-events none).
  const y = useTransform(scrollYProgress, [0, 1], [40, -40]);

  return (
    <section ref={ref} className="section" id="problem">
      <motion.div
        className="problem-parallax"
        style={{ y }}
        aria-hidden="true"
      />
      <div className="wrap" style={{ position: "relative", zIndex: 1 }}>
        <div className="section-head">
          <p className="eyebrow">The problem</p>
          <h2>Scanners guess. We fuse.</h2>
        </div>
        <motion.div
          className="problem-body"
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.14 } },
          }}
        >
          <motion.p
            className="body"
            variants={{
              hidden: { opacity: 0, y: 20 },
              visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] } },
            }}
          >
            Card scanning apps guess. They return one answer with no sense of whether it&apos;s
            right, and they routinely confuse holo, reverse-holo, and non-holo printings — cards
            that look nearly identical but differ enormously in price.
          </motion.p>
          <motion.p
            variants={{
              hidden: { opacity: 0, y: 20 },
              visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] } },
            }}
          >
            The fix isn&apos;t a better single model. It&apos;s{" "}
            <strong>two independent recognition engines that fail on different inputs</strong>,
            fused into a score that knows when it&apos;s uncertain.
          </motion.p>
        </motion.div>
      </div>
    </section>
  );
}