"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

/**
 * Alerts — the watchlist + delivery-channels reveal.
 *
 * Phase 3c shipped the watchlist and the five alert types: restock, new
 * listing, price target, auction ending, and vending-machine drop times. The
 * three delivery channels (in-app, push, email) are shown with their real
 * availability — in-app is always on; push and email need configuration.
 *
 * The caption is honest about the one thing people get wrong: alerts fire only
 * while a check runs. The poll runs on an interval while the app/server is up —
 * it is not 24/7 monitoring. Restocks, new listings, and auction alerts need a
 * listings key (eBay); vending-machine drop times need no key.
 *
 * Motion mirrors Grading.tsx exactly: GSAP ScrollTrigger scrubs a staggered
 * reveal of the alert chips as the reader scrolls in; Framer handles the
 * section-head + channels entrance. Reduced motion: everything renders at its
 * final state. JS off: chips carry no opacity:0 in CSS (GSAP animates FROM
 * hidden), so the section is fully readable without scripting.
 */

type Alert = {
  icon: string;
  name: string;
  note: string;
  /** Drop times need no listings key; the other four do. */
  noKey?: boolean;
};

const ALERTS: Alert[] = [
  { icon: "📦", name: "Restock", note: "Back in stock" },
  { icon: "✨", name: "New listing", note: "Fresh match on the watchlist" },
  { icon: "🎯", name: "Price target", note: "Hits your threshold" },
  { icon: "⏳", name: "Auction ending", note: "Time running out" },
  { icon: "⏰", name: "Drop times", note: "Vending-machine drops", noKey: true },
];

const CHANNELS: { name: string; note: string; alwaysOn?: boolean }[] = [
  { name: "In-app", note: "Always on", alwaysOn: true },
  { name: "Push", note: "When configured" },
  { name: "Email", note: "When configured" },
];

export function Alerts() {
  const sectionRef = useRef<HTMLElement | null>(null);
  const chipsRef = useRef<HTMLUListElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const section = sectionRef.current;
    const chips = chipsRef.current;
    if (!section || !chips) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const rows = Array.from(chips.querySelectorAll<HTMLElement>(".alert-chip"));

    if (reduce) {
      // Static final state: every chip lit and in place.
      rows.forEach((row) => {
        row.style.opacity = "1";
        row.style.transform = "none";
        row.classList.add("is-lit");
      });
      return;
    }

    gsap.registerPlugin(ScrollTrigger);

    const ctx = gsap.context(() => {
      // Staggered reveal of the five alert chips as the reader scrolls in.
      // Each chip "lights up" (opacity + rise + accent border) in sequence.
      rows.forEach((row, i) => {
        gsap.fromTo(
          row,
          { opacity: 0, y: 18 },
          {
            opacity: 1,
            y: 0,
            ease: "none",
            scrollTrigger: {
              trigger: chips,
              start: "top 80%",
              end: "bottom 65%",
              scrub: 0.5,
              onUpdate: (self) => {
                const seg = 1 / rows.length;
                const local = (self.progress - i * seg) / seg;
                const p = Math.max(0, Math.min(1, local));
                row.style.opacity = String(p);
                row.style.transform = `translateY(${(1 - p) * 18}px)`;
                // Light up the accent border once the chip has fully arrived.
                if (p >= 0.999) row.classList.add("is-lit");
                else row.classList.remove("is-lit");
              },
            },
          }
        );
      });
    }, sectionRef);

    return () => ctx.revert();
  }, []);

  return (
    <section ref={sectionRef} className="section" id="alerts">
      <div className="wrap">
        <div className="section-head">
          <p className="eyebrow">Alerts</p>
          <h2>Five alerts. Three channels. One honest caveat.</h2>
          <p>
            Watch a card and get notified the moment something changes — restocks, fresh listings,
            price targets, auctions ending, and vending-machine drop times.
          </p>
        </div>

        <motion.ul
          ref={chipsRef}
          className="alert-chips"
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.08 } },
          }}
        >
          {ALERTS.map((alert) => (
            <motion.li
              key={alert.name}
              className="alert-chip"
              variants={{
                hidden: { opacity: 0, y: 18 },
                visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
              }}
            >
              <span className="alert-icon" aria-hidden="true">{alert.icon}</span>
              <span className="alert-name">{alert.name}</span>
              <span className="alert-note">{alert.note}</span>
              {alert.noKey && <span className="alert-key-tag">No key needed</span>}
            </motion.li>
          ))}
        </motion.ul>

        <motion.div
          className="alert-channels"
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-60px" }}
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.08 } },
          }}
        >
          <h3 className="alert-channels-title">Delivery channels</h3>
          <ul className="channel-row">
            {CHANNELS.map((channel) => (
              <motion.li
                key={channel.name}
                className={`channel${channel.alwaysOn ? " is-on" : " is-opt"}`}
                variants={{
                  hidden: { opacity: 0, y: 14 },
                  visible: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] } },
                }}
              >
                <span className="channel-name">{channel.name}</span>
                <span className="channel-note">{channel.note}</span>
              </motion.li>
            ))}
          </ul>
        </motion.div>

        <p className="alert-caption">
          Alerts fire only while a check runs. Set a listings key (eBay) to detect restocks, new
          listings, and auctions; vending-machine drop times need no key. The poll runs on an interval
          while the app is up — not 24/7 monitoring — so the moment a check catches a change is the
          moment you hear about it, never sooner.
        </p>
      </div>
    </section>
  );
}