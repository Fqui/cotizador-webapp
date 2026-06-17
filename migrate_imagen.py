"""Paso 2: ALTER TABLE rubros + cargar mapeo de imagenes."""
import sqlite3

DB = r"C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\hierronort.db"

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Listar nombres reales primero
print("=== Rubros en la DB ===")
rows = cur.execute("SELECT nombre FROM rubros ORDER BY nombre").fetchall()
for r in rows:
    print(f"  {r[0]}")
print(f"Total: {len(rows)} rubros\n")

# Verificar si la columna imagen ya existe
cols = [r[1] for r in cur.execute("PRAGMA table_info(rubros)").fetchall()]
print(f"Columnas actuales: {cols}")
if "imagen" not in cols:
    print("ALTER TABLE rubros ADD COLUMN imagen TEXT...")
    cur.execute("ALTER TABLE rubros ADD COLUMN imagen TEXT")
    conn.commit()
    print("OK\n")
else:
    print("La columna 'imagen' ya existe, no la duplico.\n")

# Cargar el mapeo segun el spec - uso el rubro "raiz" de cada grupo
updates = [
    ("hierro.png",    "HIERRO DE CONSTRUCCION"),
    ("chapas.png",    "CHAPAS PREPINTADAS"),
    ("canos.png",     "CANOS ESTRUCTURALES"),       # sin Ñ porque esta asi en la DB
    ("perfiles.png",  "PERFILES PESADOS"),
    ("alambres.png",  "ALAMBRE NEGRO"),
    ("acero.png",     "ACERO INOXIDABLE"),
    ("varios.png",    "CLAVOS"),
    ("cumbreras.png", "CUMBRERAS PREPINTADAS"),
]
for img, nombre in updates:
    cur.execute("UPDATE rubros SET imagen = ? WHERE nombre = ?", (img, nombre))
    print(f"UPDATE {nombre} -> {img}")

conn.commit()

# Verificacion
print("\n=== Rubros con imagen (post-update) ===")
rows = cur.execute("SELECT nombre, imagen FROM rubros ORDER BY nombre").fetchall()
con_imagen = sum(1 for r in rows if r[1])
print(f"  {con_imagen}/{len(rows)} rubros con imagen")
for r in rows:
    flag = "OK " if r[1] else "-- "
    img = r[1] or "(null)"
    print(f"  {flag}{r[0][:40]:40s} {img}")

conn.close()
