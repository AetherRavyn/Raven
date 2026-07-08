import { motion } from "framer-motion";

const variants = {
  hidden: { opacity: 0, y: 40 },
  show: (i: number = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 1, ease: [0.16, 1, 0.3, 1], delay: i * 0.08 },
  }),
};

type Props = {
  children: React.ReactNode;
  className?: string;
  delay?: number;
  as?: "div" | "span" | "p" | "h2" | "h3";
};

/** Scroll-triggered reveal wrapper using Framer Motion whileInView. */
export default function Reveal({ children, className = "", delay = 0, as = "div" }: Props) {
  const MotionTag = motion[as];
  return (
    <MotionTag
      className={className}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: "-12% 0px" }}
      variants={variants}
      custom={delay}
    >
      {children}
    </MotionTag>
  );
}
