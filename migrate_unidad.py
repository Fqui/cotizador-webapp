"""Migracion: agregar unidad_venta a productos + heuristica."""
import sqlite3
DB = r"C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\hierronort.db"

conn = sqlite3.connect(DB)
cur = conn.cursor()

# 1. Agregar columna
cols = [r[1] for r in cur.execute("PRAGMA table_info(productos)").fetchall()]
print(f"Columnas actuales: {cols}")
if "unidad_venta" not in cols:
    cur.execute("ALTER TABLE productos ADD COLUMN unidad_venta TEXT DEFAULT 'unidad'")
    print("ADD unidad_venta OK")
else:
    print("unidad_venta ya existe")

# 2. Heuristica
# Metro: RUBRO contiene CHAPA, CINCA, GALVA, PREPI, POLICARBONATO, TRASLUCIDA
cur.execute("""
    UPDATE productos SET unidad_venta = 'metro'
    WHERE unidad_venta = 'unidad'
      AND (UPPER(rubro) LIKE '%CHAPA%'
           OR UPPER(rubro) LIKE '%CINCA%'
           OR UPPER(rubro) LIKE '%GALVA%'
           OR UPPER(rubro) LIKE '%PREPI%'
           OR UPPER(rubro) LIKE '%POLICARBONATO%'
           OR UPPER(rubro) LIKE '%TRASLUCIDA%')
""")
print(f"metro: {cur.rowcount} rows")

# Kg: RUBRO contiene CLAVOS, ELECTRODOS
cur.execute("""
    UPDATE productos SET unidad_venta = 'kg'
    WHERE unidad_venta = 'unidad'
      AND (UPPER(rubro) LIKE '%CLAVOS%' OR UPPER(rubro) LIKE '%ELECTRODOS%')
""")
print(f"kg: {cur.rowcount} rows")

conn.commit()

# 3. Verificacion
print("\n=== Distribucion ===")
rows = cur.execute("SELECT unidad_venta, COUNT(*) FROM productos GROUP BY unidad_venta").fetchall()
for u, n in rows:
    print(f"  {u:8s} {n}")

print("\n=== Rubros con metro ===")
rows = cur.execute("""
    SELECT DISTINCT rubro FROM productos
    WHERE unidad_venta = 'metro'
    ORDER BY rubro
""").fetchall()
for (r,) in rows:
    print(f"  {r}")

print("\n=== Rubros con kg ===")
rows = cur.execute("""
    SELECT DISTINCT rubro FROM productos
    WHERE unidad_venta = 'kg'
    ORDER BY rubro
""").fetchall()
for (r,) in rows:
    print(f"  {r}")

print("\n=== Muestra de productos por unidad ===")
for u in ('unidad', 'metro', 'kg'):
    rows = cur.execute("""
        SELECT cod, descripcion, precio_lista, rubro FROM productos
        WHERE unidad_venta = ?
        ORDER BY descripcion LIMIT 3
    """, (u,)).fetchall()
    print(f"\n  {u}:")
    for r in rows:
        print(f"    {r[0]:15s} {r[1][:40]:40s} ${r[2]:>10,.2f}  ({r[3]})")

conn.close()
