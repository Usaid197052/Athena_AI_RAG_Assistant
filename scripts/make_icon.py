"""Generate Athena tray/exe icon assets."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw


def build_icon(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 48, 64, 128, 256]
    images = []
    for size in sizes:
        image = Image.new("RGBA", (size, size), (10, 15, 30, 255))
        draw = ImageDraw.Draw(image)
        margin = max(2, size // 8)
        draw.ellipse(
            (margin, margin, size - margin, size - margin),
            fill=(40, 160, 240, 255),
        )
        inner = size // 3
        draw.ellipse(
            (inner, inner, size - inner, size - inner),
            fill=(10, 15, 30, 255),
        )
        images.append(image)

    images[0].save(path, format="ICO", sizes=[(s, s) for s in sizes])
    return path


def main() -> int:
    target = ROOT / "resources" / "athena.ico"
    build_icon(target)
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
