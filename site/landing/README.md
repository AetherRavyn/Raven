# RAVEN — Landing Page

A cinematic, immersive landing page for RAVEN, a next-generation personal AI
operating system. Built as a standalone Vite + React app inside the `site/`
monorepo (the existing `site/` root is the Starlight documentation site).

## Stack

- **React 18 + TypeScript** — component architecture
- **Vite** — build tooling / dev server
- **Tailwind CSS** — styling system (custom blood-red / matte-black theme)
- **Framer Motion** — section reveals, loader, magnetic buttons
- **GSAP + ScrollTrigger** — scroll-linked animation
- **Lenis** — inertial smooth scrolling
- **Three.js (React Three Fiber)** — 3D raven silhouette, volumetric moon glow, drifting particles

## Run

```bash
npm install
npm run dev      # http://localhost:4321
npm run build    # production build -> dist/
npm run preview  # preview the build
```

## Structure

```
src/
  App.tsx                 # assembles loader, cursor, sections, footer
  index.css               # theme tokens, fog, grain, glow
  components/
    SmoothScroll.tsx      # Lenis + GSAP ticker
    Cursor.tsx            # custom magnetic cursor
    Navbar.tsx            # minimal mix-blend nav
    Hero.tsx              # oversized wordmark + headline + CTA
    RavenScene.tsx        # R3F raven, particles, moon glow (lazy)
    Sections.tsx          # 8 narrative chapters
    Feathers.tsx          # ambient drifting feathers
    Footer.tsx            # footer + hidden easter egg
    MagneticButton.tsx    # CTA with magnetic hover
    Reveal.tsx            # scroll reveal wrapper
  hooks/
    useMagnetic.ts        # magnetic pull
    useParallax.ts        # mouse parallax
```

## Design notes

- Deep matte black `#050505`, blood-red `#8b0000` / `#c8102e` glow, soft white `#f4f1ea`.
- Editorial serif (Cormorant Garamond) for headlines, Inter for UI.
- Narrative scroll: Arrival → Memory → Understanding → Evolution →
  Intelligence → Execution → Community → Future.
- Honors `prefers-reduced-motion`; disables custom cursor on touch devices.
- Three.js scene is code-split and lazy-loaded so first paint stays light.
