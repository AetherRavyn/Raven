"""Generate RAVEN desktop app icons.

Produces:
  * icons/32x32.png        — Linux/window small icon
  * icons/128x128.png      — Linux medium icon
  * icons/128x128@2x.png   — 256×256 retina icon
  * icons/icon.png         — 512×512 master icon
  * icons/icon.ico         — Windows multi-resolution .ico
  * icons/icon.icns        — macOS multi-resolution .icns
  * icons/tray.png         — System tray icon (32×32, monochrome alpha)

Usage
-----
  uv run python scripts/build-app-icons.py
  # or
  python3 scripts/build-app-icons.py

The output lands in companion-shell/icons/.  Commit the
generated .png / .ico / .icns — they're already gitignored
only at the sidecar-binary level; the icon set is small and
checked in so a release build doesn't require Pillow on the
build host.

Prereqs
-------
  pip install pillow
  # macOS only: iconutil (ships with Xcode command-line tools)
  # Windows: just .ico via Pillow is fine
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Pillow not installed.  Run: pip install pillow")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ICON_DIR = ROOT / "companion-shell" / "icons"
SVG = ICON_DIR / "raven.svg"

# Sizes to generate.  The first list is the PNG raster; the
# second is what goes into the .ico / .icns bundles.
SIZES_PNG = [(32, "32x32.png"), (128, "128x128.png"), (256, "128x128@2x.png"), (512, "icon.png"), (32, "tray.png")]
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
ICNS_SIZES = [16, 32, 64, 128, 256, 512]


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    if not SVG.exists():
        sys.exit(f"missing source SVG: {SVG}")

    # 1. Render the SVG to a 512×512 base via cairo (Pillow can't
    #    read SVG directly).  Try cairosvg, fall back to a simple
    #    Pillow-drawn fallback if cairo isn't available.
    base = render_svg_to_png(SVG, 512)
    if base is None:
        print("cairosvg not available — falling back to procedural icon")
        base = render_procedural_icon(512)

    # 2. Save PNGs at all the required sizes.
    for size, name in SIZES_PNG:
        out = base.resize((size, size), Image.LANCZOS)
        path = ICON_DIR / name
        out.save(path, "PNG", optimize=True)
        print(f"  {path.relative_to(ROOT)}")

    # 3. Windows .ico — multi-resolution.
    ico_path = ICON_DIR / "icon.ico"
    base.save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s, _ in ICO_SIZES],
    )
    print(f"  {ico_path.relative_to(ROOT)}")

    # 4. macOS .icns — needs iconutil.
    build_icns(base, ICON_DIR / "icon.icns")

    print(f"\nWrote {len(SIZES_PNG) + 2} icons to {ICON_DIR}")


def render_svg_to_png(svg_path: Path, size: int) -> Image.Image | None:
    """Use cairosvg if available; otherwise return None."""
    try:
        import cairosvg  # type: ignore

        import io

        png_bytes = cairosvg.svg2png(url=str(svg_path), output_width=size, output_height=size)
        return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    except ImportError:
        return None
    except Exception as exc:  # cairosvg can fail on missing cairo
        print(f"  warning: cairosvg failed: {exc}")
        return None


def render_procedural_icon(size: int) -> Image.Image:
    """Draw a stylised RAVEN mark directly via Pillow.

    Used when cairo isn't installed (e.g. CI hosts without GTK).
    The result is good enough for development builds; release
    builds should run with cairosvg for crisp vector output.
    """
    img = Image.new("RGBA", (size, size), (11, 11, 16, 255))
    draw = ImageDraw.Draw(img)

    # Rounded-square background gradient (approximated with two rects).
    accent_top = (212, 184, 90, 255)
    accent_bottom = (168, 132, 58, 255)
    radius = size // 6
    # We can't blend in one call — draw two horizontal slabs.
    for y in range(size):
        t = y / size
        col = tuple(int(accent_top[i] * (1 - t) + accent_bottom[i] * t) for i in range(3)) + (255,)
        draw.line([(0, y), (size, y)], fill=col, width=1)
    # Round corners by drawing the bg colour over them.
    bg = (11, 11, 16, 255)
    for cx, cy in [(0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)]:
        for r in range(radius):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if dx * dx + dy * dy <= r * r:
                        px, py = cx + dx, cy + dy
                        if 0 <= px < size and 0 <= py < size:
                            draw.point((px, py), fill=bg)

    # Stylised "R" — three line segments.
    fg = (26, 26, 37, 255)  # dark, contrasts with gold bg
    pad = size // 6
    stroke = max(2, size // 16)
    x0, y0 = pad, pad
    x1, y1 = size - pad, size - pad
    # Vertical
    draw.line([(x0, y0), (x0, y1)], fill=fg, width=stroke)
    # Top horizontal + curve to middle
    draw.line([(x0, y0), (x1 - size // 6, y0)], fill=fg, width=stroke)
    draw.line([(x1 - size // 6, y0), (x1 - size // 12, y0 + size // 8)], fill=fg, width=stroke)
    draw.line([(x1 - size // 12, y0 + size // 8), (x1 - size // 6, y0 + size // 4)], fill=fg, width=stroke)
    draw.line([(x1 - size // 6, y0 + size // 4), (x0, y0 + size // 4)], fill=fg, width=stroke)
    # Diagonal leg
    draw.line([(x0 + size // 6, y0 + size // 4), (x1, y1)], fill=fg, width=stroke)

    return img


def build_icns(base: Image.Image, out_path: Path) -> None:
    """Build a multi-resolution .icns via macOS ``iconutil``.

    On non-macOS hosts we just skip — the .icns is only needed
    for the .app bundle and macOS devs regenerate it locally.
    """
    if sys.platform != "darwin":
        print(f"  skip {out_path.name} (macOS-only; run on macOS to build .icns)")
        return
    if shutil.which("iconutil") is None:
        print(f"  skip {out_path.name} (iconutil not on PATH)")
        return

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "iconset.iconset"
        iconset.mkdir()
        for size in ICNS_SIZES:
            actual = min(size, base.width)
            img = base.resize((actual, actual), Image.LANCZOS)
            ext = "png" if size >= 256 else "png"
            # iconutil expects specific filenames per size.
            if size == 16:
                img.save(iconset / f"icon_{size}x{size}.{ext}")
            elif size == 32:
                img.save(iconset / f"icon_{size}x{size}.{ext}")
                img.save(iconset / f"icon_{size}x{size}@2x.png".replace("32x32@2x", "64x64"))
            elif size == 64:
                continue  # covered by 32 @2x
            elif size == 128:
                img.save(iconset / f"icon_{size}x{size}.{ext}")
            elif size == 256:
                img.save(iconset / f"icon_{size}x{size}.{ext}")
                img.save(iconset / f"icon_{size}x{size}@2x.png".replace("256x256@2x", "512x512"))
            elif size == 512:
                img.save(iconset / f"icon_{size}x{size}.{ext}")
        # Run iconutil.
        try:
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset), "-o", str(out_path)],
                check=True,
            )
            print(f"  {out_path.name}")
        except subprocess.CalledProcessError as exc:
            print(f"  iconutil failed: {exc}")


if __name__ == "__main__":
    main()