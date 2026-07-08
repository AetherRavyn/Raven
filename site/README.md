# RAVEN — Website

The official RAVEN website monorepo. It contains two coordinated parts:

| Path | What | Stack | Purpose |
|------|------|-------|---------|
| `site/` (this folder) | **Documentation site** | Astro + Starlight | Full technical docs, guides, API/CLI/TUI references |
| `site/landing/` | **Marketing landing page** | Vite + React + Three.js | Cinematic, immersive homepage experience |

Both are deployed together — the landing page at the site root and the
documentation under `/docs/`.

---

## Documentation site (`site/`)

Astro + Starlight. Source content lives in `src/content/docs/` (Markdown).

```bash
npm install
npm run dev        # http://localhost:4321
npm run build      # production build -> dist/
npm run preview    # preview build
```

`site` is configured in `astro.config.mjs` (title, sidebar, GitHub social,
sitemap). The sidebar is organized into Overview, Core Components, Deployment &
Hardware, Features, Guides, and Reference.

---

## Landing page (`site/landing/`)

A cinematic, award-style homepage: a 3D raven hero, narrative scroll chapters
(Arrival → Memory → Understanding → Evolution → Intelligence → Execution →
Community → Future), smooth scrolling, magnetic cursor, and ambient particles.

```bash
cd landing
npm install
npm run dev        # http://localhost:4321
npm run build      # production build -> landing/dist/
npm run preview    # preview build
```

**Stack:** React 18 + TypeScript · Vite · Tailwind CSS · Framer Motion ·
GSAP + ScrollTrigger · Lenis · Three.js (React Three Fiber).

See `site/landing/README.md` for the full component architecture.

---

## Deployment

The site is a static build. Recommended: build both and serve from one origin.

```bash
# Docs
cd site && npm run build            # -> site/dist

# Landing
cd site/landing && npm run build    # -> site/landing/dist
```

Serve `site/dist` at the root and `site/landing/dist` at `/` (or mount the
landing output and copy `site/dist` into `site/landing/dist/docs`). Ensure the
landing footer **Docs** link (`/docs/`) resolves to the documentation build.

---

## Design language

- Deep matte black `#050505`, blood-red `#8b0000` / `#c8102e` glow, soft white `#f4f1ea`
- Editorial serif (Cormorant Garamond) for headlines, Inter for UI
- Massive whitespace, layered depth, volumetric fog, drifting feathers
- Mystery, elegance, intelligence, calm confidence — not cyberpunk
