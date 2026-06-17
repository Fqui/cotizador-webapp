"""Migracion: agregar columnas a clientes + crear tablas facturas y pagos + seed."""
import sqlite3
import random
from datetime import date, timedelta

DB = r"C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\hierronort.db"

conn = sqlite3.connect(DB)
cur = conn.cursor()

# 1. ALTER TABLE clientes - agregar columnas nuevas
cols = [r[1] for r in cur.execute("PRAGMA table_info(clientes)").fetchall()]
print(f"Columnas actuales de clientes: {cols}")

agregar = [
    ("email", "TEXT"),
    ("telefono", "TEXT"),
    ("direccion", "TEXT"),
    ("limite_credito", "REAL DEFAULT 0"),
    ("saldo_actual", "REAL DEFAULT 0"),
]
for col, tipo in agregar:
    if col not in cols:
        cur.execute(f"ALTER TABLE clientes ADD COLUMN {col} {tipo}")
        print(f"  ADD COLUMN {col} {tipo}")
    else:
        print(f"  {col} ya existe, skip")

# 2. Crear tabla facturas
cur.execute("""
    CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        numero TEXT NOT NULL,
        fecha TEXT NOT NULL,
        total REAL NOT NULL,
        saldo_pendiente REAL NOT NULL,
        estado TEXT NOT NULL CHECK(estado IN ('pagada','pendiente','vencida')),
        FOREIGN KEY (cliente_id) REFERENCES clientes(id)
    )
""")
print("Tabla facturas OK")

cur.execute("CREATE INDEX IF NOT EXISTS idx_facturas_cliente ON facturas(cliente_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_facturas_estado ON facturas(estado)")

# 3. Crear tabla pagos
cur.execute("""
    CREATE TABLE IF NOT EXISTS pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        factura_id INTEGER,
        cliente_id INTEGER NOT NULL,
        fecha TEXT NOT NULL,
        monto REAL NOT NULL,
        metodo TEXT NOT NULL CHECK(metodo IN ('efectivo','transferencia','cheque')),
        referencia TEXT,
        FOREIGN KEY (factura_id) REFERENCES facturas(id),
        FOREIGN KEY (cliente_id) REFERENCES clientes(id)
    )
""")
print("Tabla pagos OK")

cur.execute("CREATE INDEX IF NOT EXISTS idx_pagos_cliente ON pagos(cliente_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_pagos_factura ON pagos(factura_id)")

# 4. Actualizar datos de contacto de admin y demo
cur.execute("""
    UPDATE clientes SET
        email = 'admin@hierronort.com.ar',
        telefono = '+54 11 4000-0001',
        direccion = 'Av. Siempre Viva 742, CABA',
        limite_credito = 500000,
        saldo_actual = 0
    WHERE usuario = 'admin'
""")
cur.execute("""
    UPDATE clientes SET
        email = 'demo@corralonsanm.com.ar',
        telefono = '+54 11 4000-0002',
        direccion = 'Ruta 8 km 47, Pilar, Buenos Aires',
        limite_credito = 250000,
        saldo_actual = 0
    WHERE usuario = 'demo'
""")
print("Datos de contacto cargados para admin y demo")

# 5. Seed de facturas y pagos
# Limpiar primero para que el seed sea idempotente
cur.execute("DELETE FROM pagos")
cur.execute("DELETE FROM facturas")
print("Tablas facturas/pagos limpias")

random.seed(42)  # para que el seed sea reproducible
hoy = date.today()
clientes = cur.execute("SELECT id, usuario FROM clientes WHERE usuario IN ('admin','demo')").fetchall()
print(f"Clientes a seedear: {clientes}")

metodos = ["efectivo", "transferencia", "cheque"]
for cid, usuario in clientes:
    n_facturas = random.randint(3, 5)
    for i in range(n_facturas):
        # Factura
        dias_atras = random.randint(5, 90)
        fecha_fac = (hoy - timedelta(days=dias_atras)).isoformat()
        numero = f"FC-{usuario.upper()}-{1000 + i:04d}"
        total = round(random.uniform(15000, 180000), 2)
        # 60% pagada, 25% pendiente, 15% vencida
        r = random.random()
        if r < 0.6:
            estado = "pagada"
            saldo = 0
        elif r < 0.85:
            estado = "pendiente"
            saldo = total
        else:
            estado = "vencida"
            saldo = total
        cur.execute("""
            INSERT INTO facturas (cliente_id, numero, fecha, total, saldo_pendiente, estado)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (cid, numero, fecha_fac, total, saldo, estado))
        factura_id = cur.lastrowid
        # Pagos: 1-3 por factura
        if estado == "pagada":
            n_pagos = random.randint(1, 3)
            pagos_totales = total
            for j in range(n_pagos):
                if j == n_pagos - 1:
                    monto_pago = round(pagos_totales, 2)
                else:
                    fraccion = pagos_totales / n_pagos
                    monto_pago = round(fraccion * random.uniform(0.7, 1.0), 2)
                    pagos_totales -= monto_pago
                fecha_pago = (date.fromisoformat(fecha_fac) + timedelta(days=random.randint(0, 30))).isoformat()
                metodo = random.choice(metodos)
                ref = f"REF-{random.randint(100000, 999999)}" if metodo != "efectivo" else None
                cur.execute("""
                    INSERT INTO pagos (factura_id, cliente_id, fecha, monto, metodo, referencia)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (factura_id, cid, fecha_pago, monto_pago, metodo, ref))
        elif estado in ("pendiente", "vencida") and random.random() < 0.3:
            # a veces factura pendiente/vencida tiene un pago parcial
            monto_pago = round(total * random.uniform(0.2, 0.5), 2)
            fecha_pago = (date.fromisoformat(fecha_fac) + timedelta(days=random.randint(0, 30))).isoformat()
            metodo = random.choice(metodos)
            ref = f"REF-{random.randint(100000, 999999)}" if metodo != "efectivo" else None
            cur.execute("""
                INSERT INTO pagos (factura_id, cliente_id, fecha, monto, metodo, referencia)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (factura_id, cid, fecha_pago, monto_pago, metodo, ref))
            cur.execute("""
                UPDATE facturas SET saldo_pendiente = saldo_pendiente - ?
                WHERE id = ?
            """, (monto_pago, factura_id))
    # Actualizar saldo_actual del cliente
    cur.execute("""
        UPDATE clientes SET saldo_actual = (
            SELECT COALESCE(SUM(saldo_pendiente), 0)
            FROM facturas WHERE cliente_id = ?
        )
        WHERE id = ?
    """, (cid, cid))

conn.commit()

# 6. Verificación
print("\n=== Verificación ===")
for cid, usuario in clientes:
    c = cur.execute("SELECT nombre, email, telefono, direccion, limite_credito, saldo_actual FROM clientes WHERE id = ?", (cid,)).fetchone()
    n_fac = cur.execute("SELECT COUNT(*) FROM facturas WHERE cliente_id = ?", (cid,)).fetchone()[0]
    n_pag = cur.execute("SELECT COUNT(*) FROM pagos WHERE cliente_id = ?", (cid,)).fetchone()[0]
    fac_estado = cur.execute("SELECT estado, COUNT(*) FROM facturas WHERE cliente_id = ? GROUP BY estado", (cid,)).fetchall()
    print(f"\n  {usuario} ({c[0]}):")
    print(f"    Email: {c[1]}")
    print(f"    Tel:   {c[2]}")
    print(f"    Dir:   {c[3]}")
    print(f"    Limite credito: ${c[4]:,.2f}")
    print(f"    Saldo actual:   ${c[5]:,.2f}")
    print(f"    Facturas: {n_fac} ({dict(fac_estado)})")
    print(f"    Pagos:    {n_pag}")

conn.close()
print("\nMigracion completa.")
