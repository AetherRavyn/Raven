import { motion } from "framer-motion";
import { useMagnetic } from "../hooks/useMagnetic";

type Props = {
  children: React.ReactNode;
  href?: string;
  className?: string;
  strength?: number;
  onClick?: () => void;
};

/**
 * Premium CTA button with magnetic hover + blood-red glow.
 */
export default function MagneticButton({
  children,
  href,
  className = "",
  strength = 0.5,
  onClick,
}: Props) {
  const ref = useMagnetic<HTMLAnchorElement | HTMLButtonElement>(strength);
  const cls = `group relative inline-flex items-center justify-center gap-3 px-9 py-4 text-sm tracking-[0.2em] uppercase text-bone border border-blood/40 rounded-full overflow-hidden transition-colors duration-500 hover:border-blood-bright ${className}`;

  const inner = (
    <>
      <span className="relative z-10 flex items-center gap-3">{children}</span>
      <span className="absolute inset-0 bg-blood/10 opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
      <span className="absolute -inset-x-10 top-1/2 h-px bg-blood-glow/60 blur-md opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
    </>
  );

  if (href) {
    return (
      <a ref={ref as React.Ref<HTMLAnchorElement>} href={href} data-magnetic className={cls} onClick={onClick}>
        {inner}
      </a>
    );
  }
  return (
    <button ref={ref as React.Ref<HTMLButtonElement>} data-magnetic className={cls} onClick={onClick}>
      {inner}
    </button>
  );
}
