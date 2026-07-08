import { motion } from "framer-motion";
import { Suspense, lazy } from "react";
import MagneticButton from "./MagneticButton";

const RavenScene = lazy(() => import("./RavenScene"));

const ease = [0.16, 1, 0.3, 1] as const;

export default function Hero() {
  return (
    <section
      id="top"
      className="relative min-h-screen w-full flex items-center justify-center overflow-hidden"
    >
      {/* 3D raven + particles */}
      <Suspense fallback={null}>
        <RavenScene />
      </Suspense>

      {/* Oversized ghost wordmark */}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <h1
          className="serif font-light text-[26vw] leading-none text-white/[0.035] select-none whitespace-nowrap"
          style={{ letterSpacing: "0.05em" }}
        >
          RAVEN
        </h1>
      </div>

      {/* Foreground copy */}
      <div className="relative z-10 text-center px-6 max-w-4xl">
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1, ease, delay: 0.3 }}
          className="eyebrow mb-8"
        >
          A personal intelligence, not a chatbot
        </motion.p>

        <motion.h2
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1.3, ease, delay: 0.5 }}
          className="serif text-5xl md:text-7xl lg:text-8xl font-light leading-[1.05] text-bone"
        >
          Not another AI.
          <br />
          <span className="text-blood-glow text-glow italic">A mind that grows</span> with you.
        </motion.h2>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1.1, ease, delay: 0.9 }}
          className="mt-8 text-ash text-base md:text-lg font-light max-w-xl mx-auto leading-relaxed"
        >
          Raven remembers what matters, reasons through what's complex, and becomes
          wiser with every passing year. One quiet intelligence, woven through your
          whole life.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1, ease, delay: 1.2 }}
          className="mt-12 flex items-center justify-center gap-5"
        >
          <MagneticButton href="#enter">Enter Raven</MagneticButton>
        </motion.div>
      </div>

      {/* Scroll cue */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.8, duration: 1 }}
        className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2"
      >
        <span className="text-[0.6rem] tracking-[0.3em] uppercase text-ash">Scroll</span>
        <span className="w-px h-10 bg-gradient-to-b from-blood-bright to-transparent" />
      </motion.div>
    </section>
  );
}
