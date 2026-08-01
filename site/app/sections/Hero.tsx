"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

/**
 * Hero — sticky/pinned with a scroll-scrubbed CSS 3D Pokémon card.
 * GSAP ScrollTrigger drives rotateY/rotateX from the section scroll progress.
 * No WebGL. Degrades to a static tilted card if JS is disabled or reduced-motion is set.
 */
export function Hero() {
  const sectionRef = useRef<HTMLElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const section = sectionRef.current;
    const card = cardRef.current;
    if (!section || !card) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return; // keep static tilt from CSS

    gsap.registerPlugin(ScrollTrigger);

    const ctx = gsap.context(() => {
      // Scrub the card rotation across the hero's scroll range.
      gsap.fromTo(
        card,
        { rotateY: -22, rotateX: 8, scale: 1 },
        {
          rotateY: 196,
          rotateX: -6,
          scale: 1.04,
          ease: "none",
          scrollTrigger: {
            trigger: section,
            start: "top top",
            end: "bottom top",
            scrub: 0.6,
          },
        }
      );
    }, sectionRef);

    return () => ctx.revert();
  }, []);

  return (
    <section ref={sectionRef} className="hero" id="top">
      <div className="hero-inner">
        <motion.div
          className="hero-copy"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
        >
          <span className="tag-pill">
            <span className="rec-dot" aria-hidden="true" />
            REC · recognition live
          </span>
          <h1>
            Point a camera.
            <br />
            <span className="hl">Know the card.</span>
          </h1>
          <p className="lede">
            A phased platform for Pokémon trading cards — hybrid computer vision and OCR that
            identifies any card from a photo, values it against live market data, and grows into
            grading, bulk cataloging, and deal detection.
          </p>
          <p className="hero-stats">
            <b>20,391</b> indexed · <b>100%</b> precision
          </p>
          <div className="hero-ctas">
            <a className="btn btn-primary" href="#roadmap">
              Scan a card →
            </a>
            <a className="btn btn-ghost" href="#roadmap">
              Roadmap
            </a>
          </div>
        </motion.div>

        <div className="card-stage">
          <div className="poke-card" ref={cardRef}>
            {/* Front */}
            <div className="face">
              <div className="glint" aria-hidden="true" />
              <div className="inner-frame">
                <div className="card-top">
                  <span className="card-name">CHARIZARD</span>
                  <span className="hp">HP 120</span>
                </div>
                <div className="art-frame">
                  <div className="pokeball" aria-hidden="true" />
                </div>
                <div className="flavor">
                  Spits fire that is hot enough to melt boulders. Known to cause forest fires.
                </div>
                <div className="card-foot">
                  <span>No. 006</span>
                  <span>4/102 · Holo</span>
                </div>
              </div>
            </div>
            {/* Back */}
            <div className="face back">
              <div className="card-back-glyph">Card&nbsp;Platform</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}