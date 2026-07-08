import { useMemo } from "react";

/**
 * Ambient drifting feathers + dust. Pure CSS/SVG, GPU-friendly transforms.
 * Each feather floats up with random duration and horizontal sway.
 */
const FEATHERS = Array.from({ length: 14 });

export default function Feathers() {
  const items = useMemo(
    () =>
      FEATHERS.map((_, i) => ({
        left: Math.random() * 100,
        delay: Math.random() * 20,
        duration: 16 + Math.random() * 18,
        scale: 0.5 + Math.random() * 0.9,
        opacity: 0.06 + Math.random() * 0.12,
        sway: 20 + Math.random() * 40,
      })),
    []
  );

  return (
    <div className="pointer-events-none fixed inset-0 z-[1] overflow-hidden">
      {items.map((f, i) => (
        <span
          key={i}
          className="absolute bottom-[-10%]"
          style={{
            left: `${f.left}%`,
            animation: `feather-rise ${f.duration}s linear ${f.delay}s infinite`,
            opacity: f.opacity,
            ["--sway" as string]: `${f.sway}px`,
          }}
        >
          <svg
            width={18 * f.scale}
            height={42 * f.scale}
            viewBox="0 0 18 42"
            fill="none"
            style={{ filter: "drop-shadow(0 0 6px rgba(200,16,46,0.25))" }}
          >
            <path
              d="M9 0C5 6 3 14 3 24c0 6 2 11 6 18 4-7 6-12 6-18 0-10-2-18-6-24z"
              fill="rgba(244,241,234,0.5)"
            />
            <path d="M9 2v36" stroke="rgba(200,16,46,0.6)" strokeWidth="0.6" />
          </svg>
        </span>
      ))}
      <style>{`
        @keyframes feather-rise {
          0% { transform: translateY(0) translateX(0) rotate(0deg); }
          50% { transform: translateY(-60vh) translateX(var(--sway)) rotate(180deg); }
          100% { transform: translateY(-120vh) translateX(calc(var(--sway) * -1)) rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
