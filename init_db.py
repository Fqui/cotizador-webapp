"""
Inicializa la base SQLite y carga los productos desde data.json.

Uso:
    python init_db.py
"""

import json
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hierronort.db")
DATA_JSON = os.path.join(BASE_DIR, "data.json")

GRUPO_ORDEN = {
    "HIERRO DE CONSTRUCCION": 1,
    "CHAPAS PREPINTADAS": 2, "CHAPAS CINCALUM": 2, "CHAPAS GALVANIZADAS": 2,
    "GALVANIZADAS LISAS": 2, "CHAPAS TRASLUCIDAS": 2, "CHAPAS POLICARBONATO": 2,
    "CHAPAS ESTAMPADAS": 2, "CHAPAS IMPORTADAS": 2, "CHAPAS ANTIDESLIZANTES": 2,
    "CHAPAS LAMINADAS EN CALIENTE": 2, "CHAPA DECORATIVA": 2,
    "CHAPA PERFORADA": 2, "METAL DESPLEGADO": 2, "CINCA T101": 2,
    "CINCA ACANALADA": 2, "GALVA ACANALADA": 2, "TRASLUCIDA ACANALADA": 2,
    "TRASLUCIDA T101": 2,
    "CAÑOS ESTRUCTURALES": 3, "CAÑOS MECANICOS": 3, "TUBOS SCHEDULE 40-80": 3,
    "CAÑOS GALVANIZADOS": 3, "NEGRO BISELADO": 3, "CONDUIT GALVANIZADO": 3,
    "CAÑOS EPOXI": 3,
    "PERFILES PESADOS": 4, "PERFILES C": 4, "PERFILES COMERCIALES": 4,
    "AL.NEGRO/CORDON/TRENZA": 5, "ALAMBRE NEGRO": 5, "ALAMBRE GALVANIZADO": 5,
    "ALAMBRE TEJIDO": 5, "MEDIANA Y ALTA RESISTENCIA": 5, "BOYERO / VID": 5,
    "ELECTROSOLDADAS": 5,
    "ACERO INOXIDABLE": 6,
    "CLAVOS": 7, "ACCESORIOS P/AGRO": 7, "ELECTRODOS": 7, "AISLACION TERMICA": 7,
    "RODAMIENTOS": 7, "PUA Y CONCERTINA": 7, "PLACAS DE YESO": 7, "CEMENTICIO": 7,
    "LAMINADO EN FRIO": 7,
    "CUMBRERAS PREPINTADAS": 99, "CUMBRERAS CINCALUM": 99, "CUMBRERAS GALVANIZADAS": 99,
}

GRUPO_NOMBRE = {
    1: "HIERRO", 2: "CHAPAS", 3: "CAÑOS", 4: "PERFILES",
    5: "ALAMBRES", 6: "ACERO INOX", 7: "VARIOS", 99: "CUMBRERAS",
}


def get_tipo(cod):
    return "ADN" if str(cod).upper().startswith("ADN") else "NORMAL"


def init_schema(conn):
    cur = conn.cursor()
    cur.executescript("""
    DROP TABLE IF EXISTS productos;
    DROP TABLE IF EXISTS rubros;
    DROP TABLE IF EXISTS clientes;

    CREATE TABLE rubros (
        nombre       TEXT PRIMARY KEY,
        grupo        TEXT,
        grupo_orden  INTEGER
    );

    CREATE TABLE productos (
        cod            TEXT PRIMARY KEY,
        descripcion    TEXT NOT NULL,
        precio_lista   REAL NOT NULL,
        rubro          TEXT NOT NULL,
        grupo          TEXT,
        tipo_descuento TEXT,
        FOREIGN KEY (rubro) REFERENCES rubros(nombre)
    );

    CREATE INDEX idx_productos_rubro ON productos(rubro);
    CREATE INDEX idx_productos_cod ON productos(cod);
    CREATE INDEX idx_productos_desc ON productos(descripcion);

    CREATE TABLE clientes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario       TEXT UNIQUE NOT NULL,
        nombre        TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        activo        INTEGER DEFAULT 1,
        is_admin      INTEGER DEFAULT 0
    );
    """)
    conn.commit()


def seed_productos(json_path=DATA_JSON, db_path=DB_PATH):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Re-creamos rubros y productos sin tocar clientes
    cur.execute("DELETE FROM productos")
    cur.execute("DELETE FROM rubros")

    inserted = 0
    for r in data["rubros"]:
        cur.execute(
            "INSERT OR IGNORE INTO rubros (nombre, grupo, grupo_orden) VALUES (?, ?, ?)",
            (r["nombre"], r["grupo"], r["grupo_orden"]),
        )
        for p in r["productos"]:
            cur.execute(
                """INSERT OR REPLACE INTO productos
                   (cod, descripcion, precio_lista, rubro, grupo, tipo_descuento)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (p["cod"], p["desc"], p["precio_lista"],
                 r["nombre"], r["grupo"], p["tipo"]),
            )
            inserted += 1
    conn.commit()
    conn.close()
    return inserted


def seed_clientes_default(db_path=DB_PATH):
    """Crea dos clientes por defecto: admin y uno de prueba."""
    from werkzeug.security import generate_password_hash
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    defaults = [
        ("admin",   "Administrador", "admin123",   1),
        ("demo",    "Cliente Demo",  "demo1234",   0),
    ]
    for usuario, nombre, password, is_admin in defaults:
        cur.execute(
            "INSERT OR IGNORE INTO clientes (usuario, nombre, password_hash, activo, is_admin) "
            "VALUES (?, ?, ?, 1, ?)",
            (usuario, nombre, generate_password_hash(password), is_admin),
        )
    conn.commit()
    conn.close()


def main():
    if not os.path.exists(DATA_JSON):
        print(f"No se encontró {DATA_JSON}")
        sys.exit(1)
    print(f"Inicializando base en {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    init_schema(conn)
    conn.close()
    n = seed_productos(DATA_JSON, DB_PATH)
    seed_clientes_default(DB_PATH)
    print(f"  → {n} productos cargados")
    print("  → Clientes por defecto:")
    print("       admin / admin123  (administrador)")
    print("       demo  / demo1234  (cliente de prueba)")


if __name__ == "__main__":
    main()
