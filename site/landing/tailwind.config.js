/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#050505",
        blood: {
          DEFAULT: "#8b0000",
          bright: "#c8102e",
          glow: "#ff1a2e",
        },
        bone: "#f4f1ea",
        ash: "#9a9690",
      },
      fontFamily: {
        serif: ['"Cormorant Garamond"', "Georgia", "serif"],
        sans: ['"Inter"', "system-ui", "sans-serif"],
      },
      letterSpacing: {
        widest: "0.35em",
      },
      animation: {
        breathe: "breathe 6s ease-in-out infinite",
        drift: "drift 20s linear infinite",
        float: "float 12s ease-in-out infinite",
        glow: "glow 4s ease-in-out infinite",
      },
      keyframes: {
        breathe: {
          "0%, 100%": { transform: "scale(1)", opacity: "0.95" },
          "50%": { transform: "scale(1.03)", opacity: "1" },
        },
        drift: {
          "0%": { transform: "translateY(0) translateX(0)" },
          "100%": { transform: "translateY(-120vh) translateX(40px)" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-14px)" },
        },
        glow: {
          "0%, 100%": { opacity: "0.4" },
          "50%": { opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};
