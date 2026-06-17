"""Migracion FASE A v2: chapas no-techo de metro a unidad (regla de Fernando)."""
import sqlite3, shutil
from datetime import datetime

DB = r"C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\hierronort.db"

# Backup
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = f"{DB}.bak.{ts}"
shutil.copy2(DB, backup_path)
print(f"[backup] {backup_path}")

conn = sqlite3.connect(DB)
c = conn.cursor()

# 5 categorias con TODOS sus productos metro a migrar a unidad
cats_full = [
    "chapa-antideslizante",   # 3
    "chapa-decorativa",       # 13
    "chapa-estampada",        # 6
    "galvanizada-lisa",       # 16
    "prepintada-lisa",        # 6
]
total_full = 0
for cat in cats_full:
    n = c.execute("""
        UPDATE productos
        SET unidad_venta='unidad', configurable_en_metros=0
        WHERE slug_grupo='chapas' AND slug_categoria=? AND unidad_venta='metro'
    """, (cat,)).rowcount
    print(f"  {cat:25s}  {n:3d} productos migrados metro->unidad")
    total_full += n
conn.commit()
print(f"\n  Subtotal 5 categorias: {total_full} productos migrados")
print(f"  (El spec dice 83 total; los 39 restantes son de chapa-importada con filtro 'X' pendiente)")

# Resumen final
print("\n=== Estado final chapas (no techo) ===")
for slc in cats_full:
    metro = c.execute("SELECT COUNT(*) FROM productos WHERE slug_grupo='chapas' AND slug_categoria=? AND unidad_venta='metro'", (slc,)).fetchone()[0]
    unidad = c.execute("SELECT COUNT(*) FROM productos WHERE slug_grupo='chapas' AND slug_categoria=? AND unidad_venta='unidad'", (slc,)).fetchone()[0]
    print(f"  {slc:25s}  metro={metro:3d}  unidad={unidad:3d}")

print()
print("=== Estado final chapa-importada (39 metro, 18 unidad, SIN TOCAR) ===")
metro = c.execute("SELECT COUNT(*) FROM productos WHERE slug_grupo='chapas' AND slug_categoria='chapa-importada' AND unidad_venta='metro'").fetchone()[0]
unidad = c.execute("SELECT COUNT(*) FROM productos WHERE slug_grupo='chapas' AND slug_categoria='chapa-importada' AND unidad_venta='unidad'").fetchone()[0]
print(f"  metro={metro}  unidad={unidad}  (sin cambios, esperando filtro X)")

conn.close()
print(f"\n[done] backup: {backup_path}")
