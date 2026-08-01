"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { PIPELINE, PIPELINE_NOTE } from "./data";

/**
 * Pipeline — the 5 steps assemble/light up in sequence as the user scrolls.
 * GSAP ScrollTrigger scrubs an "active index" across the list; each step lights
 * up and connects in order. The note callout is preserved verbatim.
 */
export function Pipeline() {
  const sectionRef = useRef<HTMLElement | null>(null);
  const listRef = useRef<HTMLOListElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const section = sectionRef.current;
    const list = listRef.current;
    if (!section || !list) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const steps = Array.from(list.querySelectorAll<HTMLElement>(".pipe-step"));

    if (reduce) {
      // Static: show all steps fully lit.
      steps.forEach((s) => s.classList.add("is-active"));
      return;
    }

    gsap.registerPlugin(ScrollTrigger);

    const ctx = gsap.context(() => {
      steps.forEach((step, i) => {
        gsap.fromTo(
          step,
          { opacity: 0.4 },
          {
            opacity: 1,
            ease: "none",
            scrollTrigger: {
              trigger: list,
              start: "top 75%",
              end: "bottom 70%",
              scrub: 0.5,
              onUpdate: (self) => {
                // Distribute activation across the scroll range per step.
                const seg = 1 / steps.length;
                const local = (self.progress - i * seg) / seg;
                const lit = Math.max(0, Math.min(1, local));
                step.style.opacity = String(0.4 + 0.6 * lit);
                step.classList.toggle("is-active", lit > 0.55);
              },
            },
          }
        );
      });
    }, sectionRef);

    return () => ctx.revert();
  }, []);

  return (
    <section ref={sectionRef} className="section" id="pipeline">
      <div className="wrap">
        <div className="section-head">
          <p className="eyebrow">Recognition pipeline</p>
          <h2>Five steps, one calibrated answer.</h2>
          <p>Two engines that fail differently, fused into a score that knows when it&apos;s uncertain.</p>
        </div>

        <motion.ol
          ref={listRef}
          className="pipe-list"
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.08 } },
          }}
        >
          {PIPELINE.map((step) => (
            <motion.li
              key={step.title}
              className="pipe-step"
              variants={{
                hidden: { opacity: 0, y: 16 },
                visible: { opacity: 0.4, y: 0, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
              }}
            >
              <span className="idx">{String(PIPELINE.indexOf(step) + 1).padStart(2, "0")}</span>
              <div>
                <h3>{step.title}</h3>
                <small>{step.detail}</small>
              </div>
            </motion.li>
          ))}
        </motion.ol>

        <motion.div
          className="note-callout"
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        >
          {PIPELINE_NOTE}
        </motion.div>
      </div>
    </section>
  );
}