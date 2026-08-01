"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ROADMAP, SHIPPED_COUNT, TOTAL_COUNT } from "./data";

/**
 * CountUp — animates a numeric stat from `from` to `to` when scrolled into view.
 * Parses the leading number; preserves any prefix/suffix (e.g. "%").
 */
function CountUp({ from, to, label }: { from: string; to: string; label: string }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const [display, setDisplay] = useState(to);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const el = ref.current;
    if (!el) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const fromNum = parseFloat(from);
    const toNum = parseFloat(to);
    if (reduce || Number.isNaN(fromNum) || Number.isNaN(toNum)) {
      setDisplay(to);
      return;
    }

    let raf = 0;
    let started = false;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !started) {
          started = true;
          const start = performance.now();
          const dur = 1100;
          const tick = (now: number) => {
            const p = Math.min(1, (now - start) / dur);
            const eased = 1 - Math.pow(1 - p, 3);
            const val = fromNum + (toNum - fromNum) * eased;
            const rounded = Math.round(val);
            // Preserve any prefix/suffix from the `to` string (e.g. "%").
            const m = to.match(/^([^\d.-]*)([\d.-]+)([^\d.-]*)$/);
            const prefix = m ? m[1] : "";
            const suffix = m ? m[3] : "";
            setDisplay(`${prefix}${rounded}${suffix}`);
            if (p < 1) raf = requestAnimationFrame(tick);
          };
          raf = requestAnimationFrame(tick);
        }
      },
      { threshold: 0.5 }
    );
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [from, to]);

  return (
    <div className="phase-stat">
      <span ref={ref}>
        {from} → <b>{display}</b>
      </span>{" "}
      {label}
    </div>
  );
}

/**
 * Roadmap — interactive: phases reveal on scroll; DONE phases get a yellow check
 * and a count-up stat where relevant; PLANNED phases are dimmed with a "Planned" pill.
 * Hover/tap a row to expand detail (React state, no router). Progress indicator on top.
 */
export function Roadmap() {
  const [open, setOpen] = useState<string | null>(null);
  const barRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const el = barRef.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const target = `${(SHIPPED_COUNT / TOTAL_COUNT) * 100}%`;
    if (reduce) {
      el.style.width = target;
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          el.style.width = target;
          io.disconnect();
        }
      },
      { threshold: 0.4 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section className="section" id="roadmap">
      <div className="wrap">
        <div className="section-head">
          <p className="eyebrow">Roadmap</p>
          <h2>Twelve phases. Six shipped.</h2>
          <p>Each phase ships something usable on its own and builds on the same recognition core.</p>
        </div>

        <div className="progress-row">
          <span className="progress-label">
            <b>{SHIPPED_COUNT}</b> of {TOTAL_COUNT} phases shipped
          </span>
          <div className="progress-bar" aria-hidden="true">
            <span ref={barRef} className="progress-fill" />
          </div>
        </div>

        <motion.div
          className="road-list"
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.06 } },
          }}
        >
          {ROADMAP.map((phase) => {
            const isOpen = open === phase.n;
            return (
              <motion.div
                key={phase.n}
                className={`phase ${phase.status === "planned" ? "is-planned" : ""}`}
                variants={{
                  hidden: { opacity: 0, y: 14 },
                  visible: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] } },
                }}
                onClick={() => setOpen(isOpen ? null : phase.n)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setOpen(isOpen ? null : phase.n);
                  }
                }}
                role="button"
                tabIndex={0}
                aria-expanded={isOpen}
              >
                <span className="pn">{phase.n}</span>
                <span className="pt">
                  {phase.title}
                  <span className="sub">{phase.subtitle}</span>
                  {phase.status === "done" && phase.stat && (
                    <CountUp from={phase.stat.from} to={phase.stat.to} label={phase.stat.label} />
                  )}
                  {isOpen && (
                    <span className="phase-detail">
                      {phase.status === "done"
                        ? "Shipped and live. Builds on the same recognition core — no module re-solves a problem an earlier one already solved."
                        : "Planned. Ships something usable on its own and extends the recognition core into a new capability."}
                    </span>
                  )}
                </span>
                <span className={`status-pill ${phase.status}`}>
                  {phase.status === "done" ? (
                    <>
                      <span className="check-mark" aria-hidden="true">✓</span> Complete
                    </>
                  ) : (
                    "Planned"
                  )}
                </span>
              </motion.div>
            );
          })}
        </motion.div>

        <p className="road-foot">
          Each phase ships something usable on its own and builds on the same recognition core — no
          module re-solves a problem an earlier one already solved.
        </p>
      </div>
    </section>
  );
}