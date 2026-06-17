"""Optimiza las 8 imagenes a 256x256 PNG."""
import os
from PIL import Image

DIR = r"C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\static\rubros"

before_total = 0
after_total = 0
for name in os.listdir(DIR):
    if not name.endswith(".png"):
        continue
    path = os.path.join(DIR, name)
    before = os.path.getsize(path)
    before_total += before

    img = Image.open(path).convert("RGBA")
    img = img.resize((256, 256), Image.LANCZOS)
    img.save(path, "PNG", optimize=True)

    after = os.path.getsize(path)
    after_total += after
    print(f"  {name:20s} {before:>10,} -> {after:>10,} bytes  ({after*100//before}% del original)")

print(f"\nTotal: {before_total:,} -> {after_total:,} bytes ({(before_total-after_total)*100//before_total}% menos)")
