import { motion } from "framer-motion";

const links = [
  { label: "Memory", href: "#memory" },
  { label: "Understanding", href: "#understanding" },
  { label: "Evolution", href: "#evolution" },
  { label: "Intelligence", href: "#intelligence" },
  { label: "Community", href: "#community" },
];

export default function Navbar() {
  return (
    <motion.nav
      initial={{ y: -40, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1], delay: 0.4 }}
      className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 md:px-10 py-5 mix-blend-difference"
    >
      <a href="#top" data-magnetic className="flex items-center gap-3 group">
        <RavenGlyph />
        <span className="serif text-xl tracking-[0.3em] text-bone">RAVEN</span>
      </a>

      <div className="hidden md:flex items-center gap-9 text-xs tracking-[0.2em] uppercase text-ash">
        {links.map((l) => (
          <a key={l.href} href={l.href} className="hover:text-bone transition-colors duration-300">
            {l.label}
          </a>
        ))}
      </div>

      <a
        href="#enter"
        data-magnetic
        className="text-xs tracking-[0.2em] uppercase text-bone border border-bone/30 rounded-full px-5 py-2 hover:border-blood-bright hover:text-blood-glow transition-all duration-400"
      >
        Enter
      </a>
    </motion.nav>
  );
}

function RavenGlyph() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" className="group-hover:text-blood-glow transition-colors">
      <path
        d="M2 14c4-1 6-4 9-9 0 5 2 8 6 10-3 0-5-1-7-3 3 2 6 2 9 1-4 3-9 3-12 1-2-1-3-3-5-5z"
        fill="currentColor"
      />
    </svg>
  );
}
