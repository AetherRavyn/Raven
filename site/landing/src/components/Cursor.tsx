import { useEffect, useRef } from "react";
import { gsap } from "gsap";

/**
 * Custom magnetic cursor with a trailing ring and a blood-red core.
 * Buttons / links with data-magnetic attract the cursor on hover.
 */
export default function Cursor() {
  const dotRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const pos = useRef({ x: 0, y: 0 });
  const ring = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (window.matchMedia("(pointer: coarse)").matches) return;

    const dot = dotRef.current!;
    const ringEl = ringRef.current!;

    const move = (e: MouseEvent) => {
      pos.current.x = e.clientX;
      pos.current.y = e.clientY;
      gsap.set(dot, { x: e.clientX, y: e.clientY });

      const target = (e.target as HTMLElement)?.closest("[data-magnetic]");
      const label = (e.target as HTMLElement)?.closest("[data-cursor]");
      if (label) {
        ringEl.dataset.label = (label as HTMLElement).dataset.cursor || "";
      } else {
        delete ringEl.dataset.label;
      }
      if (target) {
        ringEl.classList.add("cursor--active");
      } else {
        ringEl.classList.remove("cursor--active");
      }
    };

    const render = () => {
      ring.current.x += (pos.current.x - ring.current.x) * 0.18;
      ring.current.y += (pos.current.y - ring.current.y) * 0.18;
      gsap.set(ringEl, { x: ring.current.x, y: ring.current.y });
      requestAnimationFrame(render);
    };
    render();

    window.addEventListener("mousemove", move);
    return () => window.removeEventListener("mousemove", move);
  }, []);

  return (
    <>
      <div
        ref={dotRef}
        className="cursor-dot"
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          width: 6,
          height: 6,
          marginLeft: -3,
          marginTop: -3,
          borderRadius: "50%",
          background: "#c8102e",
          boxShadow: "0 0 12px #c8102e",
          pointerEvents: "none",
          zIndex: 9999,
        }}
      />
      <div
        ref={ringRef}
        className="cursor-ring"
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          width: 38,
          height: 38,
          marginLeft: -19,
          marginTop: -19,
          borderRadius: "50%",
          border: "1px solid rgba(200,16,46,0.5)",
          pointerEvents: "none",
          zIndex: 9999,
          transition: "width .3s, height .3s, border-color .3s, background .3s",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "0.55rem",
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "#f4f1ea",
        }}
      />
    </>
  );
}
