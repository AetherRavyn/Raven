import { motion } from "framer-motion";
import Reveal from "./Reveal";
import MagneticButton from "./MagneticButton";
import { useParallax } from "../hooks/useParallax";

const ease = [0.16, 1, 0.3, 1] as const;

function ChapterMark({ n, label }: { n: string; label: string }) {
  return (
    <div className="flex items-center gap-4 mb-10">
      <span className="serif text-blood-glow text-2xl text-glow">{n}</span>
      <span className="h-px w-16 bg-blood/40" />
      <span className="eyebrow">{label}</span>
    </div>
  );
}

/* ── Arrival ─────────────────────────────────────────────── */
export function Arrival() {
  return (
    <section id="arrival" className="relative min-h-screen flex items-center section-pad">
      <div className="max-w-5xl">
        <ChapterMark n="I" label="Arrival" />
        <Reveal as="h2" className="serif text-5xl md:text-7xl font-light leading-[1.08] text-bone">
          You never start from zero again.
        </Reveal>
        <Reveal delay={1} className="mt-8 text-ash text-lg font-light max-w-2xl leading-relaxed">
          Most assistants forget you by morning. Raven arrives with context already
          intact — your history, your preferences, the shape of your days. The first
          message is never the first conversation.
        </Reveal>
        <Reveal delay={2} className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-px bg-white/5">
          {[
            ["Continuity", "A single thread of memory across every channel and year."],
            ["Presence", "Always there — silently attentive, never intrusive."],
            ["Calm", "No noise, no upsell. Just intelligence, on your terms."],
          ].map(([t, d]) => (
            <div key={t} className="bg-ink p-8 hover:bg-white/[0.02] transition-colors duration-500">
              <h3 className="serif text-2xl text-bone mb-3">{t}</h3>
              <p className="text-ash text-sm font-light leading-relaxed">{d}</p>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

/* ── Memory ──────────────────────────────────────────────── */
export function Memory() {
  const parallax = useParallax(30);
  return (
    <section id="memory" className="relative min-h-screen flex items-center section-pad overflow-hidden">
      <div
        ref={parallax}
        className="absolute right-[-5%] top-1/2 -translate-y-1/2 w-[42vw] h-[42vw] rounded-full border border-blood/10 opacity-40"
      />
      <div className="max-w-4xl relative z-10">
        <ChapterMark n="II" label="Memory" />
        <Reveal as="h2" className="serif text-5xl md:text-7xl font-light leading-[1.08] text-bone">
          A memory that behaves
          <br />
          <span className="italic text-blood-glow text-glow">like a mind.</span>
        </Reveal>
        <Reveal delay={1} className="mt-8 text-ash text-lg font-light max-w-2xl leading-relaxed">
          Not a transcript dump. Raven distills, connects, and forgets gracefully.
          Facts become understanding. Understanding becomes intuition. The longer it
          knows you, the less you have to explain.
        </Reveal>
        <Reveal delay={2} className="mt-14 flex flex-wrap gap-3">
          {["Episodic", "Semantic", "Procedural", "Emotional", "Proactive"].map((m, i) => (
            <motion.span
              key={m}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.08, duration: 0.8, ease }}
              className="px-5 py-2 rounded-full border border-white/10 text-sm text-ash hover:border-blood-bright hover:text-bone transition-all duration-400"
            >
              {m}
            </motion.span>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

/* ── Understanding ───────────────────────────────────────── */
export function Understanding() {
  return (
    <section id="understanding" className="relative min-h-screen flex items-center section-pad">
      <div className="grid md:grid-cols-2 gap-16 items-center max-w-6xl">
        <div>
          <ChapterMark n="III" label="Understanding" />
          <Reveal as="h2" className="serif text-5xl md:text-6xl font-light leading-[1.1] text-bone">
            It listens between the words.
          </Reveal>
          <Reveal delay={1} className="mt-8 text-ash text-lg font-light leading-relaxed">
            Context, tone, timing, the unsaid. Raven reads the situation before it
            answers — then reasons, instead of reacting. This is comprehension, not
            completion.
          </Reveal>
        </div>
        <Reveal delay={2} className="relative">
          <div className="aspect-square rounded-2xl border border-white/10 bg-gradient-to-br from-white/[0.04] to-transparent p-8 flex flex-col justify-between">
            <div className="space-y-3">
              {["Intent", "Sentiment", "Urgency", "Relationship"].map((k, i) => (
                <div key={k} className="flex items-center gap-3">
                  <span className="text-xs text-ash w-28">{k}</span>
                  <span className="flex-1 h-px bg-white/10 relative overflow-hidden">
                    <motion.span
                      className="absolute inset-y-0 left-0 bg-blood-glow"
                      initial={{ width: 0 }}
                      whileInView={{ width: `${[82, 64, 47, 73][i]}%` }}
                      viewport={{ once: true }}
                      transition={{ duration: 1.4, delay: i * 0.15, ease }}
                    />
                  </span>
                </div>
              ))}
            </div>
            <p className="serif text-xl text-bone/80 italic">
              "The question was never about the weather."
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* ── Evolution ───────────────────────────────────────────── */
export function Evolution() {
  const steps = [
    ["Observe", "Every interaction is a signal."],
    ["Reflect", "Patterns surface across time."],
    ["Adapt", "Behavior shifts without being told."],
    ["Crystallize", "Wisdom becomes reusable skill."],
  ];
  return (
    <section id="evolution" className="relative min-h-screen flex items-center section-pad">
      <div className="max-w-5xl mx-auto text-center">
        <ChapterMark n="IV" label="Evolution" />
        <Reveal as="h2" className="serif text-5xl md:text-7xl font-light leading-[1.08] text-bone">
          It becomes <span className="italic text-blood-glow text-glow">you-er</span> every year.
        </Reveal>
        <Reveal delay={1} className="mt-8 text-ash text-lg font-light max-w-2xl mx-auto">
          Raven self-improves through use. Skills crystallize from repetition. Mistakes
          become corrections. The system you meet in year three is not the one you
          met in year one — and it remembers the difference.
        </Reveal>
        <div className="mt-16 grid grid-cols-2 md:grid-cols-4 gap-px bg-white/5">
          {steps.map(([t, d], i) => (
            <motion.div
              key={t}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.12, duration: 0.9, ease }}
              className="bg-ink p-8 text-left relative"
            >
              <span className="serif text-blood-glow text-glow text-3xl block mb-4">
                {String(i + 1).padStart(2, "0")}
              </span>
              <h3 className="serif text-xl text-bone mb-2">{t}</h3>
              <p className="text-ash text-sm font-light">{d}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Intelligence ────────────────────────────────────────── */
export function Intelligence() {
  return (
    <section id="intelligence" className="relative min-h-screen flex items-center section-pad overflow-hidden">
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[60vw] h-[60vw] rounded-full bg-blood/5 blur-[120px]" />
      <div className="max-w-4xl relative z-10">
        <ChapterMark n="V" label="Intelligence" />
        <Reveal as="h2" className="serif text-5xl md:text-7xl font-light leading-[1.08] text-bone">
          Reasoning, not autocomplete.
        </Reveal>
        <Reveal delay={1} className="mt-8 text-ash text-lg font-light max-w-2xl leading-relaxed">
          Multi-step planning, causal forecasting, and a world model that anticipates
          what comes next. Raven thinks before it speaks — and shows its work when it
          matters.
        </Reveal>
        <Reveal delay={2} className="mt-14 grid md:grid-cols-2 gap-8">
          {[
            ["World Model", "A living graph of people, plans, and consequences."],
            ["Forecasting", "It sees the likely future and warns before it arrives."],
            ["Tool Use", "100+ tools, chosen with judgment, not habit."],
            ["Self-Correction", "Confidence calibrated against reality, not vibes."],
          ].map(([t, d]) => (
            <div key={t} className="border-l border-blood/30 pl-6 py-2">
              <h3 className="serif text-2xl text-bone mb-2">{t}</h3>
              <p className="text-ash text-sm font-light">{d}</p>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

/* ── Execution ───────────────────────────────────────────── */
export function Execution() {
  return (
    <section id="execution" className="relative min-h-screen flex items-center section-pad">
      <div className="max-w-6xl mx-auto">
        <ChapterMark n="VI" label="Execution" />
        <Reveal as="h2" className="serif text-5xl md:text-7xl font-light leading-[1.08] text-bone text-center">
          From thought to done.
        </Reveal>
        <Reveal delay={1} className="mt-8 text-ash text-lg font-light max-w-2xl mx-auto text-center">
          Raven acts — across your calendar, files, messages, and devices — under
          clear governance. High-risk moves ask; routine moves flow.
        </Reveal>
        <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            ["Orchestration", "Spawns the right agent for the right job, in parallel."],
            ["Governance", "Deny-by-default policy. You stay in command."],
            ["Companion", "Native apps mirror the mind to phone, desktop, and web."],
          ].map(([t, d], i) => (
            <motion.div
              key={t}
              initial={{ opacity: 0, scale: 0.96 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1, duration: 1, ease }}
              className="rounded-xl border border-white/10 p-8 hover:border-blood-bright/50 transition-colors duration-500"
            >
              <h3 className="serif text-2xl text-bone mb-3">{t}</h3>
              <p className="text-ash text-sm font-light leading-relaxed">{d}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Community ───────────────────────────────────────────── */
export function Community() {
  return (
    <section id="community" className="relative min-h-screen flex items-center section-pad">
      <div className="max-w-4xl">
        <ChapterMark n="VII" label="Community" />
        <Reveal as="h2" className="serif text-5xl md:text-7xl font-light leading-[1.08] text-bone">
          A flock, not a product.
        </Reveal>
        <Reveal delay={1} className="mt-8 text-ash text-lg font-light max-w-2xl leading-relaxed">
          Open modules, shared skills, and a research community advancing personal
          intelligence in the open. Your Raven can learn from the flock — and give back.
        </Reveal>
        <Reveal delay={2} className="mt-12 flex flex-wrap gap-10">
          {[
            ["13", "Connected platforms"],
            ["5", "Companion device types"],
            ["100+", "Tools in its arsenal"],
          ].map(([n, l]) => (
            <div key={l}>
              <div className="serif text-5xl text-blood-glow text-glow">{n}</div>
              <div className="eyebrow mt-2">{l}</div>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

/* ── Future ──────────────────────────────────────────────── */
export function Future() {
  return (
    <section id="future" className="relative min-h-screen flex flex-col items-center justify-center section-pad text-center">
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="w-[70vw] h-[70vw] rounded-full bg-blood/5 blur-[140px]" />
      </div>
      <div className="relative z-10 max-w-3xl">
        <ChapterMark n="VIII" label="Future" />
        <Reveal as="h2" className="serif text-5xl md:text-8xl font-light leading-[1.05] text-bone">
          The raven remembers
          <br />
          <span className="italic text-blood-glow text-glow">what you forget.</span>
        </Reveal>
        <Reveal delay={1} className="mt-8 text-ash text-lg font-light max-w-xl mx-auto">
          This is the beginning of a relationship measured in decades, not sessions.
          Step into the mind.
        </Reveal>
        <Reveal delay={2} className="mt-12 flex items-center justify-center gap-5">
          <MagneticButton href="#enter">Enter Raven</MagneticButton>
        </Reveal>
      </div>
    </section>
  );
}
