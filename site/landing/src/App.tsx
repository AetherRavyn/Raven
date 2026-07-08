import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import SmoothScroll from "./components/SmoothScroll";
import Cursor from "./components/Cursor";
import Feathers from "./components/Feathers";
import Navbar from "./components/Navbar";
import Hero from "./components/Hero";
import Footer from "./components/Footer";
import {
  Arrival,
  Memory,
  Understanding,
  Evolution,
  Intelligence,
  Execution,
  Community,
  Future,
} from "./components/Sections";

/** Cinematic intro: a blood-red ring draws, then the wordmark settles. */
function Loader() {
  const [done, setDone] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setDone(true), 2200);
    return () => clearTimeout(t);
  }, []);
  return (
    <AnimatePresence>
      {!done && (
        <motion.div
          initial={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.8 }}
          className="fixed inset-0 z-[100] bg-ink flex items-center justify-center"
        >
          <div className="relative flex flex-col items-center">
            <motion.svg
              width="80"
              height="80"
              viewBox="0 0 80 80"
              initial={{ rotate: -90 }}
              animate={{ rotate: 0 }}
            >
              <motion.circle
                cx="40"
                cy="40"
                r="36"
                stroke="#c8102e"
                strokeWidth="1"
                fill="none"
                strokeDasharray={2 * Math.PI * 36}
                initial={{ strokeDashoffset: 2 * Math.PI * 36 }}
                animate={{ strokeDashoffset: 0 }}
                transition={{ duration: 1.6, ease: [0.16, 1, 0.3, 1] }}
              />
            </motion.svg>
            <motion.span
              className="serif text-3xl tracking-[0.4em] text-bone mt-6"
              initial={{ opacity: 0, letterSpacing: "0.8em" }}
              animate={{ opacity: 1, letterSpacing: "0.4em" }}
              transition={{ duration: 1.4, delay: 0.4 }}
            >
              RAVEN
            </motion.span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default function App() {
  return (
    <SmoothScroll>
      <Loader />
      <Cursor />
      <Feathers />
      <div className="fog-overlay" />
      <div className="grain" />
      <Navbar />
      <main className="relative z-[3]">
        <Hero />
        <Arrival />
        <Memory />
        <Understanding />
        <Evolution />
        <Intelligence />
        <Execution />
        <Community />
        <Future />
        <Footer />
      </main>
    </SmoothScroll>
  );
}
