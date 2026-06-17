"""FASE 1 - parte 1: ALTER TABLE clientes (fix)."""
import sqlite3
import datetime

DB = r"C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\hierronort.db"
NOW = datetime.datetime.now().isoformat(timespec="seconds")

conn = sqlite3.connect(DB)
cur = conn.cursor()

cols = [r[1] for r in cur.execute("PRAGMA table_info(clientes)").fetchall()]
print(f"Columnas actuales: {cols}")

agregar = [
    ("cod_cliente",     "TEXT"),
    ("razon_social",    "TEXT"),
    ("cuit",            "TEXT"),
    ("localidad",       "TEXT"),
    ("tipo_cliente",    "TEXT"),
    ("notas",           "TEXT"),
    ("lat",             "REAL"),
    ("lon",             "REAL"),
    ("geo_radio_km",    "REAL DEFAULT 3.0"),
    ("password_temporal", "INTEGER DEFAULT 0"),
    ("updated_at",      "TEXT"),
]
for col, decl in agregar:
    if col not in cols:
        cur.execute(f"ALTER TABLE clientes ADD COLUMN {col} {decl}")
        print(f"  ADD COLUMN {col} {decl}")
    else:
        print(f"  {col} ya existe")

# created_at con default constante (datetime actual en formato ISO)
if "created_at" not in cols:
    cur.execute(f"ALTER TABLE clientes ADD COLUMN created_at TEXT DEFAULT '{NOW}'")
    print(f"  ADD COLUMN created_at TEXT DEFAULT '{NOW}'")
else:
    print(f"  created_at ya existe")

# Indice unico parcial (solo aplica a clientes con cod_cliente)
cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_cod ON clientes(cod_cliente) WHERE cod_cliente IS NOT NULL")
cur.execute("CREATE INDEX IF NOT EXISTS idx_clientes_localidad ON clientes(localidad)")
print("Indices OK")

# Defaults razonables para admin y demo (los 2 clientes actuales)
cur.execute("UPDATE clientes SET tipo_cliente = 'consumidor_final' WHERE tipo_cliente IS NULL")
cur.execute("UPDATE clientes SET updated_at = ? WHERE updated_at IS NULL", (NOW,))
cur.execute("UPDATE clientes SET created_at = ? WHERE created_at IS NULL", (NOW,))
print("Defaults aplicados a admin y demo")

print("\n=== Schema final ===")
rows = cur.execute("PRAGMA table_info(clientes)").fetchall()
for r in rows:
    print(f"  {r[1]:25s} {r[2]}")

conn.commit()
conn.close()
print("\nMigracion FASE 1.1 OK.")
