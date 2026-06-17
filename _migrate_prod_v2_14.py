"""Script de migracion V2.14 para correr en prod.
Sube via API, ejecuta via consola de PA o mediante un endpoint /admin/_migrate."""
import os
import sys
import sqlite3
import re

DB_PATH = "/home/hierronort/hierronort-webapp/hierronort.db"

def col_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)

conn = sqlite3.connect(DB_PATH)
print(f"Conectado a {DB_PATH}")

# 1) Schema migrations
if not col_exists(conn, "facturas", "archivo_path"):
    print("Agregando columna facturas.archivo_path...")
    conn.execute("ALTER TABLE facturas ADD COLUMN archivo_path TEXT")
else:
    print("facturas.archivo_path ya existe")

if not col_exists(conn, "pagos", "comprobante_path"):
    print("Agregando columna pagos.comprobante_path...")
    conn.execute("ALTER TABLE pagos ADD COLUMN comprobante_path TEXT")
else:
    print("pagos.comprobante_path ya existe")

conn.commit()

# 2) Verificar que pedidos tiene columna estado
if not col_exists(conn, "pedidos", "estado"):
    print("ERROR: pedidos.estado no existe. Verificar schema base.")
    # Lo agregamos igual
    conn.execute("ALTER TABLE pedidos ADD COLUMN estado TEXT DEFAULT 'pendiente'")
    conn.commit()
    print("  Agregada pedidos.estado con default 'pendiente'")
else:
    print("pedidos.estado OK")

# 3) Migrar PDFs de pedidos a filesystem legacy
print("Migrando PDFs de pedidos a filesystem...")
LEGACY_DIR = "/home/hierronort/hierronort-webapp/uploads/facturas/legacy/2026-pre"
os.makedirs(LEGACY_DIR, exist_ok=True)

migrated = 0
skipped = 0
for row in conn.execute("SELECT nro, pdf_bytes FROM pedidos WHERE pdf_bytes IS NOT NULL").fetchall():
    nro = row["nro"]
    pdf = row["pdf_bytes"]
    if not pdf:
        continue
    safe_nro = re.sub(r"[^A-Za-z0-9_\-]", "_", nro)
    target = os.path.join(LEGACY_DIR, f"{safe_nro}.pdf")
    if os.path.exists(target):
        skipped += 1
        continue
    with open(target, "wb") as f:
        f.write(pdf)
    print(f"  -> {nro}.pdf ({len(pdf)} bytes)")
    migrated += 1

conn.close()
print(f"\nMigrados: {migrated}, skipped: {skipped}")
