"""FASE 1 - parte 2: seed 5 clientes ficticios."""
import sqlite3
from werkzeug.security import generate_password_hash

DB = r"C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\hierronort.db"

conn = sqlite3.connect(DB)
cur = conn.cursor()

clientes = [
    # cod_cliente, usuario, nombre, password, razon_social, cuit, localidad, direccion,
    # telefono, email, tipo_cliente, limite_credito, notas, lat, lon
    ("0259766", "corralon",   "Corralon San Martin",      "Distribuidora San Martin SRL",  "30-12345678-9", "Pilar",          "Ruta 8 km 47",                "+54 11 4000-1001", "compras@corralonsm.com.ar",  "responsable_inscripto", 350000, "Cliente VIP desde 2018", -34.4587, -58.9142),
    ("0342881", "hiersur",    "Hierros del Sur",          "Hierros del Sur SA",              "30-23456789-0", "Quilmes",        "Av. Calchaqui 1500",          "+54 11 4000-1002", "ventas@hierrosdelsur.com.ar","responsable_inscripto", 500000, "Pago a 30 dias",          -34.7203, -58.2546),
    ("0411553", "matplat",    "Materiales La Plata",      "Materiales La Plata SH",          "30-34567890-1", "La Plata",       "Calle 44 entre 200 y 201",    "+54 11 4000-1003", "info@matlp.com.ar",         "monotributo",           180000, "",                       -34.9214, -57.9545),
    ("0510774", "acerbona",   "Aceros Bonaerenses",       "Aceros Bonaerenses SRL",         "27-40123456-2", "Avellaneda",     "Av. Mitre 850",               "+54 11 4000-1004", "contacto@acerbona.com.ar", "responsable_inscripto", 280000, "Pago contado",            -34.6611, -58.3678),
    ("0610298", "constructor","El Constructor",           "El Constructor de Juan Perez",    "20-12345678-3", "Moron",          "Belgrano 234",                 "+54 11 4000-1005", "jperez@elconstructor.com.ar","monotributo",         120000, "Prefiere entregas por la manana", -34.6500, -58.6197),
]

for c in clientes:
    cod, usuario, nombre, razon_social, cuit, localidad, direccion, telefono, email, tipo, limite, notas, lat, lon = c
    # Verificar si ya existe
    row = cur.execute("SELECT id FROM clientes WHERE usuario = ? OR cod_cliente = ?", (usuario, cod)).fetchone()
    if row:
        print(f"  SKIP {usuario} ({cod}) ya existe")
        continue
    cur.execute("""
        INSERT INTO clientes (
            cod_cliente, usuario, nombre, password_hash, password_temporal,
            activo, is_admin, razon_social, cuit, localidad, direccion,
            telefono, email, tipo_cliente, limite_credito, saldo_actual, notas,
            lat, lon, geo_radio_km
        ) VALUES (?, ?, ?, ?, 1, 1, 0, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 3.0)
    """, (
        cod, usuario, nombre, generate_password_hash("1234"),
        razon_social, cuit, localidad, direccion,
        telefono, email, tipo, limite, notas, lat, lon
    ))
    print(f"  OK {usuario} ({cod}) - {nombre}")

conn.commit()

print("\n=== Clientes cargados ===")
rows = cur.execute("""
    SELECT id, cod_cliente, usuario, nombre, tipo_cliente, limite_credito
    FROM clientes ORDER BY id
""").fetchall()
for r in rows:
    print(f"  id={r[0]:3d} cod={r[1]} user={r[2]:14s} {r[3]:25s} tipo={r[4]:25s} limite=${r[5]:,.0f}")

conn.close()
print("\nSeed FASE 1.2 OK. Password inicial: 1234 (password_temporal=1).")
