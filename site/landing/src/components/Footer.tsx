import { useState } from "react";
import MagneticButton from "./MagneticButton";

/**
 * Footer with a hidden easter egg: clicking the raven glyph three times
 * in a row reveals a secret message.
 */
export default function Footer() {
  const [clicks, setClicks] = useState(0);
  const [secret, setSecret] = useState(false);

  const onGlyph = () => {
    const next = clicks + 1;
    setClicks(next);
    if (next >= 3) {
      setSecret(true);
      setClicks(0);
    }
    setTimeout(() => setClicks(0), 1500);
  };

  return (
    <footer className="relative z-10 border-t border-white/10 section-pad py-16">
      <div className="max-w-6xl mx-auto flex flex-col md:flex-row justify-between items-start gap-12">
        <div>
          <button
            onClick={onGlyph}
            data-magnetic
            className="flex items-center gap-3 group mb-6"
            aria-label="Raven glyph"
          >
            <svg width="26" height="26" viewBox="0 0 24 24" className="text-blood-glow group-hover:scale-110 transition-transform">
              <path
                d="M2 14c4-1 6-4 9-9 0 5 2 8 6 10-3 0-5-1-7-3 3 2 6 2 9 1-4 3-9 3-12 1-2-1-3-3-5-5z"
                fill="currentColor"
              />
            </svg>
            <span className="serif text-2xl tracking-[0.3em] text-bone">RAVEN</span>
          </button>
          <p className="text-ash text-sm font-light max-w-xs leading-relaxed">
            A personal AI operating system. Memory, reasoning, and lifelong
            intelligence — woven through your life.
          </p>
        </div>

        <div className="flex gap-16 text-sm">
          <div className="space-y-3">
            <p className="eyebrow mb-2">Explore</p>
            {["Memory", "Understanding", "Evolution", "Intelligence"].map((l) => (
              <a key={l} href={`#${l.toLowerCase()}`} className="block text-ash hover:text-bone transition-colors">
                {l}
              </a>
            ))}
          </div>
          <div className="space-y-3">
            <p className="eyebrow mb-2">Project</p>
            {[
              ["GitHub", "https://github.com/AetherRavyn/Raven"],
              ["Docs", "/docs/"],
              ["Research", "https://github.com/AetherRavyn/Raven/tree/main/docs"],
              ["Community", "https://github.com/AetherRavyn/Raven/discussions"],
            ].map(([l, h]) => (
              <a key={l} href={h} className="block text-ash hover:text-bone transition-colors">
                {l}
              </a>
            ))}
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto mt-12 pt-8 border-t border-white/5 flex flex-col md:flex-row justify-between items-center gap-4 text-xs text-ash/60">
        <span>© {new Date().getFullYear()} Raven. Built in the dark, for the light.</span>
        <MagneticButton href="#top" className="!px-6 !py-2 !text-[0.65rem]">
          Back to top
        </MagneticButton>
      </div>

      {secret && (
        <p className="text-center mt-8 serif italic text-blood-glow text-glow text-lg animate-glow">
          "Two ravens flew from thought: one named Memory, one named Fate." — the mind is listening.
        </p>
      )}
    </footer>
  );
}
