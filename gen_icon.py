#!/usr/bin/env python3
"""Generate a modern app icon for multi-llm-router."""
from PIL import Image, ImageDraw, ImageFont
import math, os

proj = "/Users/apple/Downloads/个人信息/我做的小玩具/三模型路由系统"
iconset = os.path.join(proj, "AppIcon.iconset")
os.makedirs(iconset, exist_ok=True)

# Brand colors: DeepSeek blue, Qwen teal, Kimi purple
COLORS = ["#1E90FF", "#00D4AA", "#A855F7"]
BG = "#0F172A"  # dark slate

def draw_icon(size):
    img = Image.new("RGBA", (size, size), BG)
    d = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    R = int(size * 0.38)
    r = int(size * 0.18)

    # Three orbiting nodes around center
    angles = [math.radians(a) for a in [90, 210, 330]]
    for i, ang in enumerate(angles):
        x = cx + int(R * math.cos(ang))
        y = cy - int(R * math.sin(ang))
        # Glow ring
        for g in range(4, 0, -1):
            gr = r + g * int(size * 0.02)
            d.ellipse([x-gr, y-gr, x+gr, y+gr], fill=COLORS[i] + "30")
        # Solid node
        d.ellipse([x-r, y-r, x+r, y+r], fill=COLORS[i])
        # Highlight
        hr = int(r * 0.35)
        d.ellipse([x-r//3-hr, y-r//3-hr, x-r//3+hr, y-r//3+hr], fill="#FFFFFF55")

    # Center hub
    hr = int(size * 0.12)
    d.ellipse([cx-hr, cy-hr, cx+hr, cy+hr], fill="#FFFFFF")
    # Small dot in center
    d.ellipse([cx-hr//3, cy-hr//3, cx+hr//3, cy+hr//3], fill=BG)

    # Connecting arcs (subtle)
    arc_w = max(1, size // 80)
    for i, ang in enumerate(angles):
        x1 = cx + int((R - r) * math.cos(ang))
        y1 = cy - int((R - r) * math.sin(ang))
        x2 = cx + int((R - r) * math.cos(angles[(i+1)%3]))
        y2 = cy - int((R - r) * math.sin(angles[(i+1)%3]))
        d.line([(x1, y1), (x2, y2)], fill="#FFFFFF30", width=arc_w)

    return img

sizes = [16, 32, 64, 128, 256, 512, 1024]
for s in sizes:
    im = draw_icon(s)
    # Standard + @2x naming
    if s <= 512:
        im.save(os.path.join(iconset, f"icon_{s}x{s}.png"))
    if s >= 32 and s <= 1024:
        im2 = draw_icon(s // 2)
        im2.save(os.path.join(iconset, f"icon_{s//2}x{s//2}@2x.png"))

print("Iconset generated.")
