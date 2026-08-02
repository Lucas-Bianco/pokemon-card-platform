"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

/**
 * Grading — the four-dimension reveal + the upside spread visual.
 *
 * Centering is the only dimension shipped (03a): it lights up. Corners, edges
 * and surface are NOT implemented — they stay dimmed with a "needs labelled
 * data" tag and never light up, because pretending they work would be the exact
 * confidently-wrong failure the project refuses. The reveal is honest about
 * what exists and what does not.
 *
 * The spread bars (raw / PSA 9 / PSA 10) fill as the reader scrolls — an
 * illustrative example of the grading-upside spread the scanner now returns.
 * The caption states plainly: this is a spread, not a grade prediction.
 * Predicting a grade needs labelled data the project is only starting to
 * collect (the 03b self-annotation flow).
 *
 * Motion: GSAP ScrollTrigger scrubs the bar fills + the staggered dim reveal
 * (mirrors Pipeline.tsx). Framer handles the section-head reveal. Reduced
 * motion: everything renders at its final state. JS off: bars carry their
 * target width inline and the dims are visible at natural CSS, so the section
 * is fully readable without scripting.
 */

type Dim = {
  name: string;
  done: boolean;
  note: string;
};

const DIMS: Dim[] = [
  { name: "Centering", done: true, note: "Geometric PSA cap — live" },
  { name: "Corners", done: false, note: "Needs labelled data" },
  { name: "Edges", done: false, note: "Needs labelled data" },
  { name: "Surface", done: false, note: "Needs labelled data" },
];

// An illustrative spread — clearly labelled "example" below. Not a real card's
// data; it shows the shape of the grading-upside the scanner returns. Bar fill
// is proportional to PSA 10 (the widest), so the visual reads as a spread.
const SPREAD: { label: string; value: string; pct: number }[] = [
  { label: "Raw", value: "$120", pct: 10 },
  { label: "PSA 9", value: "$350", pct: 29 },
  { label: "PSA 10", value: "$1,200", pct: 100 },
];

export function Grading() {
  const sectionRef = useRef<HTMLElement | null>(null);
  const dimsRef = useRef<HTMLOListElement | null>(null);
  const spreadRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const section = sectionRef.current;
    const dims = dimsRef.current;
    const spread = spreadRef.current;
    if (!section || !dims || !spread) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const dimRows = Array.from(dims.querySelectorAll<HTMLElement>(".grade-dim"));
    const bars = Array.from(spread.querySelectorAll<HTMLElement>(".spread-bar-fill"));

    if (reduce) {
      // Static final state: every dim row visible (lit/dimmed by semantic
      // class), every bar at its target width.
      dimRows.forEach((row) => {
        row.style.opacity = "1";
        row.style.transform = "none";
      });
      bars.forEach((bar) => {
        bar.style.width = bar.dataset.pct ?? "0%";
      });
      return;
    }

    gsap.registerPlugin(ScrollTrigger);

    const ctx = gsap.context(() => {
      // Staggered reveal of the four dimensions as the reader scrolls in.
      // Centering arrives lit; the three unshipped ones arrive already dimmed
      // with their "needs labelled data" tag — the reveal is a fade/rise, not
      // a promise that they will light up.
      dimRows.forEach((row, i) => {
        gsap.fromTo(
          row,
          { opacity: 0, y: 18 },
          {
            opacity: 1,
            y: 0,
            ease: "none",
            scrollTrigger: {
              trigger: dims,
              start: "top 80%",
              end: "bottom 65%",
              scrub: 0.5,
              onUpdate: (self) => {
                const seg = 1 / dimRows.length;
                const local = (self.progress - i * seg) / seg;
                const p = Math.max(0, Math.min(1, local));
                row.style.opacity = String(p);
                row.style.transform = `translateY(${(1 - p) * 18}px)`;
              },
            },
          }
        );
      });

      // The spread bars fill left-to-right, scrubbed to scroll. Each bar's
      // target width comes from its data-pct (proportional to PSA 10).
      bars.forEach((bar) => {
        const target = bar.dataset.pct ?? "0%";
        gsap.fromTo(
          bar,
          { width: "0%" },
          {
            width: target,
            ease: "none",
            scrollTrigger: {
              trigger: spread,
              start: "top 78%",
              end: "bottom 60%",
              scrub: 0.6,
            },
          }
        );
      });
    }, sectionRef);

    return () => ctx.revert();
  }, []);

  return (
    <section ref={sectionRef} className="section" id="grading">
      <div className="wrap">
        <div className="section-head">
          <p className="eyebrow">Grading</p>
          <h2>One dimension live. Three waiting on data.</h2>
          <p>
            Centering is solved geometrically. Corners, edges and surface need labelled graded-card
            images — the project refuses to guess a grade without them.
          </p>
        </div>

        <motion.ol
          ref={dimsRef}
          className="grade-dims"
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.08 } },
          }}
        >
          {DIMS.map((dim) => (
            <motion.li
              key={dim.name}
              className={`grade-dim${dim.done ? " is-done" : " is-pending"}`}
              variants={{
                hidden: { opacity: 0, y: 18 },
                visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
              }}
            >
              <span className="dim-name">{dim.name}</span>
              <span className={`dim-tag ${dim.done ? "tag-done" : "tag-pending"}`}>
                {dim.done ? <span className="check-mark" aria-hidden="true">✓</span> : null}
                {dim.note}
              </span>
            </motion.li>
          ))}
        </motion.ol>

        <div ref={spreadRef} className="spread">
          <h3 className="spread-title">The grading-upside spread</h3>
          <p className="spread-sub">
            What the scanner returns today: the gap between a raw card and its graded comps, before
            any fee. An <em>example</em> spread — not a real card&rsquo;s data.
          </p>

          <ul className="spread-bars">
            {SPREAD.map((bar) => (
              <li key={bar.label} className="spread-row">
                <span className="spread-bar-label">{bar.label}</span>
                <span className="spread-bar-track">
                  {/* data-pct is the GSAP target; the inline width is the JS-off
                      fallback so the bar is filled without scripting. */}
                  <span
                    className="spread-bar-fill"
                    data-pct={`${bar.pct}%`}
                    style={{ width: `${bar.pct}%` }}
                  />
                </span>
                <span className="spread-bar-value">{bar.value}</span>
              </li>
            ))}
          </ul>

          <p className="spread-caption">
            We show the upside spread, not a grade prediction. Predicting a grade needs labelled data
            we&rsquo;re only starting to collect — the self-annotation flow lets you record the grade
            you got back, seeding the only honest dataset the predictor can train on.
          </p>
        </div>
      </div>
    </section>
  );
}