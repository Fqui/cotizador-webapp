"""Migracion FASE A v2 parte 2: chapa-importada con filtro CHPERF/METAL."""
import sqlite3

DB = r"C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\hierronort.db"

conn = sqlite3.connect(DB)
c = conn.cursor()

# Filtro del spec: excluir los que cod empieza con CHPERF o METAL (los 18 que NO migran)
# LIKE con _ es wildcard en SQLite; ESCAPE no es necesario porque no usamos _
n = c.execute("""
    UPDATE productos
    SET unidad_venta='unidad', configurable_en_metros=0
    WHERE slug_grupo='chapas' AND slug_categoria='chapa-importada'
      AND unidad_venta='metro'
      AND cod NOT LIKE 'CHPERF%'
      AND cod NOT LIKE 'METAL%'
""").rowcount
print(f"  chapa-importada: {n} productos migrados metro->unidad")
conn.commit()

# Smoke test
print("\n=== Smoke test ===")
total_metro = c.execute("""
    SELECT COUNT(*) FROM productos
    WHERE slug_grupo='chapas' AND slug_categoria='chapa-importada' AND unidad_venta='metro'
""").fetchone()[0]
total_unidad = c.execute("""
    SELECT COUNT(*) FROM productos
    WHERE slug_grupo='chapas' AND slug_categoria='chapa-importada' AND unidad_venta='unidad'
""").fetchone()[0]
total_general = total_metro + total_unidad
print(f"  chapa-importada: metro={total_metro}  unidad={total_unidad}  total={total_general}")
print(f"  Esperado: metro=0  unidad=57  total=57")

# Verifico que los 18 PERF/METAL siguen intactos
perferro = c.execute("SELECT COUNT(*) FROM productos WHERE slug_grupo='chapas' AND slug_categoria='chapa-importada' AND cod LIKE 'CHPERF%' AND unidad_venta='metro'").fetchone()[0]
metalerro = c.execute("SELECT COUNT(*) FROM productos WHERE slug_grupo='chapas' AND slug_categoria='chapa-importada' AND cod LIKE 'METAL%' AND unidad_venta='metro'").fetchone()[0]
print(f"\n  Errores (no deberia haber): CHPERF* en metro={perferro}  METAL* en metro={metalerro}")

conn.close()
print("\n[done] backup anterior: hierronort.db.bak.20260607_214031")
