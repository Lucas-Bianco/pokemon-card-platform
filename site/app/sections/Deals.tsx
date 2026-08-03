"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

/**
 * Deals — the rip-vs-flip diagram, scroll-scrubbed.
 *
 * Phase 05 shipped the deal sniper: a marketplace keyword search surfaces raw
 * listings that might be underpriced two ways. The RIP path buys the raw card
 * below the sold-comp market and resells it raw. The FLIP path buys raw, pays
 * grading, and sells the slab at the PSA-10 comp. The two edges:
 *   rip edge  = raw sold-comp market − listing price
 *   flip edge = PSA-10 slab comp − listing price − grading fee
 *
 * The honest line — and the reason this section exists — is that these edges
 * are *indicative leads from keyword search, not guaranteed arbitrage*. A
 * listing can be mis-scraped, the comp can be stale, the grade can come back
 * below a 10. The sniper tells you where to look; it does not promise a profit.
 * "Never confidently wrong."
 *
 * Motion mirrors Alerts.tsx + Grading.tsx exactly: GSAP ScrollTrigger scrubs a
 * staggered reveal of the diagram nodes and fills the two edge bars as the
 * reader scrolls. Framer handles the section-head reveal. Reduced motion:
 * everything renders at its final state (nodes visible, bars at target width).
 * JS off: nodes carry no opacity:0 in CSS (GSAP animates FROM hidden) and the
 * bars carry their target width inline, so the diagram is fully readable
 * without scripting.
 */

type Node = {
  /** Which branch of the diagram this node sits on. */
  path: "source" | "rip" | "flip";
  label: string;
  note: string;
};

const NODES: Node[] = [
  { path: "source", label: "Raw listing", note: "Marketplace keyword match" },
  { path: "rip", label: "Raw sold-comp market", note: "Buy below market" },
  { path: "flip", label: "Grading", note: "Submit raw → PSA" },
  { path: "flip", label: "PSA-10 slab comp", note: "Sell the slab" },
];

// Illustrative edge bars — clearly an example, not a real listing's numbers.
// Bar fill is proportional to the FLIP edge (the wider one), so the visual
// reads as "flip carries more upside but more cost and risk."
const EDGES: { label: string; formula: string; pct: number; tag: string }[] = [
  { label: "Rip edge", formula: "market − listing", pct: 38, tag: "RIP" },
  { label: "Flip edge", formula: "PSA-10 comp − listing − grading fee", pct: 100, tag: "FLIP" },
];

export function Deals() {
  const sectionRef = useRef<HTMLElement | null>(null);
  const nodesRef = useRef<HTMLUListElement | null>(null);
  const barsRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const section = sectionRef.current;
    const nodes = nodesRef.current;
    const bars = barsRef.current;
    if (!section || !nodes || !bars) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const nodeRows = Array.from(nodes.querySelectorAll<HTMLElement>(".deal-node"));
    const barFills = Array.from(bars.querySelectorAll<HTMLElement>(".deal-bar-fill"));

    if (reduce) {
      // Static final state: every node visible and lit, every bar at target.
      nodeRows.forEach((row) => {
        row.style.opacity = "1";
        row.style.transform = "none";
        row.classList.add("is-lit");
      });
      barFills.forEach((bar) => {
        bar.style.width = bar.dataset.pct ?? "0%";
      });
      return;
    }

    gsap.registerPlugin(ScrollTrigger);

    const ctx = gsap.context(() => {
      // Staggered reveal of the diagram nodes as the reader scrolls in. The
      // source node arrives first, then the rip node, then the two flip nodes.
      // Each "lights up" (accent border) once it has fully arrived.
      nodeRows.forEach((row, i) => {
        gsap.fromTo(
          row,
          { opacity: 0, y: 18 },
          {
            opacity: 1,
            y: 0,
            ease: "none",
            scrollTrigger: {
              trigger: nodes,
              start: "top 80%",
              end: "bottom 65%",
              scrub: 0.5,
              onUpdate: (self) => {
                const seg = 1 / nodeRows.length;
                const local = (self.progress - i * seg) / seg;
                const p = Math.max(0, Math.min(1, local));
                row.style.opacity = String(p);
                row.style.transform = `translateY(${(1 - p) * 18}px)`;
                if (p >= 0.999) row.classList.add("is-lit");
                else row.classList.remove("is-lit");
              },
            },
          }
        );
      });

      // The two edge bars fill left-to-right, scrubbed to scroll. Each bar's
      // target width comes from its data-pct (proportional to the flip edge).
      barFills.forEach((bar) => {
        const target = bar.dataset.pct ?? "0%";
        gsap.fromTo(
          bar,
          { width: "0%" },
          {
            width: target,
            ease: "none",
            scrollTrigger: {
              trigger: bars,
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
    <section ref={sectionRef} className="section" id="deals">
      <div className="wrap">
        <div className="section-head">
          <p className="eyebrow">Deals</p>
          <h2>Two edges. One honest caveat.</h2>
          <p>
            The deal sniper scans marketplace keyword search for raw listings that might be
            underpriced — to rip (buy raw, resell raw) or to flip (buy raw, grade, sell the slab).
          </p>
        </div>

        <motion.ul
          ref={nodesRef}
          className="deal-diagram"
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.08 } },
          }}
        >
          {NODES.map((node) => (
            <motion.li
              key={`${node.path}-${node.label}`}
              className={`deal-node deal-node-${node.path}`}
              variants={{
                hidden: { opacity: 0, y: 18 },
                visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
              }}
            >
              <span className="deal-node-label">{node.label}</span>
              <span className="deal-node-note">{node.note}</span>
            </motion.li>
          ))}
        </motion.ul>

        <div ref={barsRef} className="deal-edges">
          <h3 className="deal-edges-title">The two edges</h3>
          <p className="deal-edges-sub">
            What the sniper returns for each match — the rip edge and the flip edge, before any
            fee the marketplace charges on sale. An <em>example</em> spread — not a real
            listing&rsquo;s numbers.
          </p>

          <ul className="deal-bars">
            {EDGES.map((edge) => (
              <li key={edge.label} className="deal-bar-row">
                <span className="deal-bar-head">
                  <span className={`deal-tag deal-tag-${edge.tag.toLowerCase()}`}>{edge.tag}</span>
                  <span className="deal-bar-label">{edge.label}</span>
                  <span className="deal-bar-formula">{edge.formula}</span>
                </span>
                <span className="deal-bar-track">
                  {/* data-pct is the GSAP target; the inline width is the JS-off
                      fallback so the bar is filled without scripting. */}
                  <span
                    className="deal-bar-fill"
                    data-pct={`${edge.pct}%`}
                    style={{ width: `${edge.pct}%` }}
                  />
                </span>
              </li>
            ))}
          </ul>

          <p className="deal-caption">
            Deal edges are indicative leads from marketplace keyword search, not guaranteed
            arbitrage — always verify the listing. A match can be mis-scraped, a comp can be stale,
            and a grade can come back below a 10. The sniper tells you where to look; it does not
            promise a profit.
          </p>
        </div>
      </div>
    </section>
  );
}