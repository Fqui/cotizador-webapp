"""
HIERRONORT — Webapp de Precios
Flask app con login, catálogo de rubros, lista de productos, búsqueda y detalle.

Reglas de descuento:
  - ADN (códigos que empiezan con ADN) → 35% off
  - Resto                          → 34% off
"""

import json
import re
import os
import secrets
import io
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, jsonify, abort, send_file, Response, g, make_response,
)
from werkzeug.security import generate_password_hash, check_password_hash

import sqlite3

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hierronort.db")
DATA_JSON = os.path.join(BASE_DIR, "data.json")
SECRET_KEY_FILE = os.path.join(BASE_DIR, ".secret_key")

# V2.14 — Uploads: PDFs de factura + comprobantes de pago
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
FACTURAS_DIR = os.path.join(UPLOADS_DIR, "facturas")
COMPROBANTES_DIR = os.path.join(UPLOADS_DIR, "comprobantes")
ARCHIVE_DIR = os.path.join(FACTURAS_DIR, "archive")
BACKUP_DIR = os.path.join(BASE_DIR, "..", "backups")  # /home/hierronort/backups
# Limites
MAX_PDF_SIZE = 2 * 1024 * 1024      # 2MB para PDFs de factura
MAX_COMP_SIZE = 2 * 1024 * 1024     # 2MB para comprobantes
# Magic bytes (primer 4 bytes) para validar
PDF_MAGIC = b"%PDF"
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC  = b"\x89PNG"

# Discount rules
DESC_ADN = 0.35
DESC_NORMAL = 0.34

# Group ordering (matches exportar_webapp.py)
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


# -----------------------------------------------------------------------------
# App + secret key persistence
# -----------------------------------------------------------------------------

app = Flask(__name__)

if os.path.exists(SECRET_KEY_FILE):
    with open(SECRET_KEY_FILE, "r") as f:
        app.secret_key = f.read().strip()
else:
    new_key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, "w") as f:
        f.write(new_key)
    app.secret_key = new_key

# V2.14: limite de subida (max 2MB por archivo, pero Flask acepta un poco mas por overhead)
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024  # 4MB total por request


# Bloque E - context processor: count de pedidos pendientes para el badge
# del navbar. Se ejecuta en cada request admin.
@app.context_processor
def inject_admin_pedidos_count():
    count = 0
    if session.get("is_admin"):
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT COUNT(*) FROM pedidos WHERE estado = 'pendiente'"
            ).fetchone()
            count = row[0] if row else 0
        except Exception:
            count = 0
    return dict(admin_pedidos_count=count)


@app.context_processor
def inject_admin_pagos_pendientes_count():
    """Inyecta n_pagos_pendientes en TODOS los templates (para badge en navbar)."""
    count = 0
    if session.get("is_admin"):
        try:
            conn = get_db()
            row = conn.execute("""
                SELECT COUNT(*) FROM pagos
                WHERE comprobante_path IS NOT NULL
                  AND (estado IS NULL OR estado != 'aprobado')
            """).fetchone()
            count = row[0] if row else 0
        except Exception:
            count = 0
    return dict(n_pagos_pendientes=count)


# Filtro Jinja: parsea un string JSON a un objeto Python.
@app.template_filter("fromjson")
def fromjson_filter(s):
    import json
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []


# -----------------------------------------------------------------------------
# DB helpers
# -----------------------------------------------------------------------------

def get_db():
    """Abre una conexion nueva. El caller es responsable de cerrarla con
    `db_close()` o usar el patron de context manager.

    Tambien corre migraciones idempotentes al inicio (V2.14: agregar
    columnas archivo_path a facturas y comprobante_path a pagos)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _run_migrations(conn)
    return conn


def _column_exists(conn, table, column):
    """True si la columna existe en la tabla."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _run_migrations(conn):
    """Migraciones idempotentes. Se ejecutan cada vez que se abre la DB."""
    # V2.14: agregar archivo_path a facturas
    if not _column_exists(conn, "facturas", "archivo_path"):
        conn.execute("ALTER TABLE facturas ADD COLUMN archivo_path TEXT")
    # V2.14: agregar comprobante_path a pagos
    if not _column_exists(conn, "pagos", "comprobante_path"):
        conn.execute("ALTER TABLE pagos ADD COLUMN comprobante_path TEXT")
    conn.commit()


def db_close(conn):
    if conn is not None:
        conn.close()


# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# V2.14 — Helpers de upload de archivos (facturas PDF + comprobantes)
# -----------------------------------------------------------------------------

def _validar_archivo(file_storage, magic_bytes_set, max_size):
    """Valida extension y magic bytes. Retorna (bytes, ext, error)."""
    if not file_storage or not file_storage.filename:
        return None, None, "No se recibio ningun archivo"
    filename = file_storage.filename.lower()
    if "." not in filename:
        return None, None, "El archivo no tiene extension"
    ext = filename.rsplit(".", 1)[-1]  # "pdf" sin punto
    expected_exts = {"pdf": "pdf", "jpg": "jpg", "jpeg": "jpg", "png": "png"}
    if ext not in expected_exts:
        return None, None, f"Extension .{ext} no permitida (solo PDF, JPG, PNG)"
    content = file_storage.read()
    if len(content) > max_size:
        return None, None, f"Archivo muy grande ({len(content)} bytes, max {max_size})"
    # Magic bytes
    for magic in magic_bytes_set:
        if content[:len(magic)] == magic:
            return content, expected_exts[ext], None
    return None, None, "El archivo no es un PDF/JPG/PNG valido"


def _guardar_factura_pdf(nro_factura, content):
    """Guarda PDF de factura en /uploads/facturas/YYYY/MM/<nro>.pdf.
    Retorna path relativo (desde BASE_DIR) o None si falla."""
    from datetime import datetime
    ahora = datetime.now()
    subdir = os.path.join(FACTURAS_DIR, str(ahora.year), f"{ahora.month:02d}")
    os.makedirs(subdir, exist_ok=True)
    # Sanitizar nombre
    safe_nro = re.sub(r"[^A-Za-z0-9_\-]", "_", nro_factura)
    full_path = os.path.join(subdir, f"{safe_nro}.pdf")
    with open(full_path, "wb") as f:
        f.write(content)
    rel = os.path.relpath(full_path, BASE_DIR)
    return rel


def _guardar_comprobante(pago_id, content, ext):
    """Guarda comprobante en /uploads/comprobantes/<pago_id>.<ext>."""
    subdir = COMPROBANTES_DIR
    os.makedirs(subdir, exist_ok=True)
    full_path = os.path.join(subdir, f"{pago_id}.{ext}")
    with open(full_path, "wb") as f:
        f.write(content)
    rel = os.path.relpath(full_path, BASE_DIR)
    return rel


def _servir_archivo_factura(nro_factura):
    """Retorna send_file del PDF de la factura o el PDF legacy si no hay archivo_path."""
    conn = get_db()
    row = conn.execute(
        "SELECT archivo_path FROM facturas WHERE numero = ?", (nro_factura,)
    ).fetchone()
    conn.close()
    if not row or not row["archivo_path"]:
        # Fallback al PDF legacy del pedido
        conn = get_db()
        ped = conn.execute(
            "SELECT pdf_bytes, pdf_filename FROM pedidos WHERE nro = ?", (nro_factura,)
        ).fetchone()
        conn.close()
        if not ped or not ped["pdf_bytes"]:
            abort(404)
        return send_file(
            io.BytesIO(ped["pdf_bytes"]),
            mimetype="application/pdf",
            as_attachment=False,
            download_name=ped["pdf_filename"] or f"{nro_factura}.pdf",
        )
    full = os.path.join(BASE_DIR, row["archivo_path"])
    if not os.path.exists(full):
        abort(404)
    return send_file(
        full,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=os.path.basename(full),
    )


def _servir_comprobante(pago_id, cliente_id_check=None):
    """Sirve comprobante de pago. Si cliente_id_check, valida que el pago sea del cliente."""
    conn = get_db()
    if cliente_id_check is not None:
        row = conn.execute(
            "SELECT id, cliente_id, comprobante_path FROM pagos WHERE id = ?",
            (pago_id,),
        ).fetchone()
        conn.close()
        if not row or row["cliente_id"] != cliente_id_check:
            abort(403)
        if not row["comprobante_path"]:
            abort(404)
    else:
        conn.close()
        # admin: cualquier pago
        conn = get_db()
        row = conn.execute(
            "SELECT comprobante_path FROM pagos WHERE id = ?", (pago_id,)
        ).fetchone()
        conn.close()
        if not row or not row["comprobante_path"]:
            abort(404)
    full = os.path.join(BASE_DIR, row["comprobante_path"])
    if not os.path.exists(full):
        abort(404)
    return send_file(full, as_attachment=False)


# Business logic
# -----------------------------------------------------------------------------

def calc_precio_final(precio_lista, tipo, largo_default=0):
    """Aplica el descuento segun el tipo (ADN o NORMAL).
    NO multiplica por largo_default: el precio devuelto es SIEMPRE por metro.

    Convencion: precio_lista siempre por metro. El precio devuelto es por metro
    con descuento. La multiplicacion por largo (ej: 12) la hace la UI cuando
    necesita mostrar el subtotal de la barra."""
    if tipo == "ADN":
        return round(precio_lista * (1 - DESC_ADN), 2)
    return round(precio_lista * (1 - DESC_NORMAL), 2)


def _aplica_descuento_cliente(cod, rubro, descuento_pct):
    """Mapeo de producto a tipo de descuento segun reglas Fer (descuentos por cliente).
    cod, rubro: del producto.
    descuento_pct: porcentaje (0-100) o None.
    Retorna el porcentaje a aplicar o None si no aplica.
    Reglas:
      - ADN: cod empieza con 'ADN' Y rubro == 'HIERRO DE CONSTRUCCION'
      - CEMENTO: cod == 'CEMENTOCPC40'
      - resto: cualquier otro
    """
    if descuento_pct is None:
        return None
    cod_s = (cod or "").upper().strip()
    rubro_s = (rubro or "").upper().strip()
    if cod_s.startswith("ADN") and rubro_s == "HIERRO DE CONSTRUCCION":
        return descuento_pct  # adn ya viene como parametro
    if cod_s == "CEMENTOCPC40":
        return descuento_pct  # cemento ya viene como parametro
    return descuento_pct  # resto


def _descuento_para_producto(cod, rubro, descuentos):
    """Devuelve el multiplicador (0-100) aplicable a este producto segun los descuentos del cliente.
    descuentos: dict con claves 'adn', 'cemento', 'resto' (None o float 0-100).
    Retorna float 0-100 o None (sin descuento)."""
    if not descuentos:
        return None
    cod_s = (cod or "").upper().strip()
    rubro_s = (rubro or "").upper().strip()
    if cod_s.startswith("ADN") and rubro_s == "HIERRO DE CONSTRUCCION":
        return descuentos.get("adn")
    if cod_s == "CEMENTOCPC40":
        return descuentos.get("cemento")
    return descuentos.get("resto")


def precio_con_descuento_cliente(precio_lista, cod, rubro, descuentos):
    """Aplica descuento del cliente al precio_lista. Retorna float redondeado a 2.
    descuentos: dict o None.

    Formula: precio_final = precio_lista * (1 - descuento/100).
    Si descuento es NULL o 0, precio_final = precio_lista (sin modificacion).
    Ejemplo: descuento=36 -> precio_final = precio_lista * 0.64.
    """
    pct = _descuento_para_producto(cod, rubro, descuentos)
    if pct is None or pct <= 0:
        return round(float(precio_lista), 2)
    return round(float(precio_lista) * (1.0 - float(pct) / 100.0), 2)


# Token-based size sort:
# - "ADN 4 MM"     → (0, 4, "")
# - "CH 1/8 1,24 X 6" → (1, 8, "1,24 X 6")
# - "CAÑO 20 X 30" → (2, 20, "20 X 30")
NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def size_key(desc):
    """Devuelve (group, num, tail) para ordenar por tamaño dentro del rubro."""
    d = desc.upper()
    if d.startswith("ADN"):
        nums = NUM_RE.findall(d)
        n = float(nums[-1].replace(",", ".")) if nums else 0.0
        return (0, n, d)
    if "X" in d:
        nums = NUM_RE.findall(d)
        n = float(nums[0].replace(",", ".")) if nums else 0.0
        return (1, n, d)
    nums = NUM_RE.findall(d)
    n = float(nums[0].replace(",", ".")) if nums else 0.0
    return (2, n, d)


def fmt_money(n):
    """Formatea con separador de miles '.' y dos decimales (estilo AR)."""
    return f"${n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# -----------------------------------------------------------------------------
# Auth decorators
# -----------------------------------------------------------------------------

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "cliente_id" not in session:
            return redirect(url_for("login", next=request.path))
        # Bloque A — device-binding: validar que el device del cliente
        # coincide con el que el cliente manda (cookie o form).
        # Admin no se ve afectado.
        if not session.get("is_admin"):
            cid = session["cliente_id"]
            cookie_token = request.cookies.get("hn_device_token", "")
            form_token = request.form.get("device_token", "")
            sent_token = cookie_token or form_token
            conn = get_db()
            row = conn.execute(
                "SELECT device_token FROM clientes WHERE id = ?", (cid,)
            ).fetchone()
            conn.close()
            if row is None:
                session.clear()
                return redirect(url_for("login"))
            db_token = row["device_token"] or ""
            if db_token and sent_token and sent_token != db_token:
                session.clear()
                flash("Tu sesión expiró. Este usuario está activo en otro dispositivo.", "error")
                return redirect(url_for("logout"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "cliente_id" not in session:
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


# -----------------------------------------------------------------------------
# Metadata FASE A — grupos y categorias v2
# -----------------------------------------------------------------------------

GRUPOS_META = {
    "hierro-de-construccion": {
        "nombre": "HIERROS DE CONSTRUCCION", "orden": 1, "color": "var(--grp-hierro)",
        "clase": "hierro",
        "categorias": {
            "adn": "ADN",
            "hierro-liso": "HIERRO LISO",
            "mallas": "MALLAS",
        },
    },
    "perfiles": {
        "nombre": "PERFILES", "orden": 2, "color": "var(--grp-perfiles)",
        "clase": "perfiles",
        "categorias": {
            "perfiles-c": "PERFILES C",
            "perfiles-pesados": "PERFILES PESADOS",
            "perfiles-comerciales": "PERFILES COMERCIALES",
        },
    },
    "chapas-para-techo": {
        "nombre": "CHAPAS PARA TECHO", "orden": 3, "color": "var(--grp-chapas)",
        "clase": "chapas",
        "categorias": {
            "cincalum": "CINCALUM",
            "galvanizada": "GALVANIZADA",
            "prepintada": "PREPINTADA",
            "traslucidas": "TRASLUCIDAS",
            "policarbonato": "POLICARBONATO",
        },
    },
    "canos": {
        "nombre": "CAÑOS", "orden": 4, "color": "var(--grp-canos)",
        "clase": "canos",
        "categorias": {
            "canos-estructurales": "CAÑOS ESTRUCTURALES",
            "canos-mecanicos": "CAÑOS MECANICOS",
            "tubos-schedule-40-80": "TUBOS SCHEDULE 40-80",
            "canos-galvanizados": "CAÑOS GALVANIZADOS",
            "negro-biselado": "NEGRO BISELADO",
            "conduit-galvanizado": "CONDUIT GALVANIZADO",
            "canos-epoxi": "CAÑOS EPOXI",
        },
    },
    "chapas": {
        "nombre": "CHAPAS", "orden": 5, "color": "var(--grp-chapas)",
        "clase": "chapas",
        "categorias": {
            "galvanizada-lisa": "GALVANIZADA LISA",
            "prepintada-lisa": "PREPINTADA LISA",
            "chapa-estampada": "CHAPA ESTAMPADA",
            "chapa-decorativa": "CHAPA DECORATIVA",
            "chapa-antideslizante": "CHAPA ANTIDESLIZANTE",
            "chapa-importada": "CHAPA IMPORTADA",
            "chapas-perforadas": "CHAPAS PERFORADAS",
            "metal-desplegado": "METAL DESPLEGADO",
            "acero-inoxidable": "ACERO INOXIDABLE",
        },
    },
    "alambres": {
        "nombre": "ALAMBRES", "orden": 6, "color": "var(--grp-alambres)",
        "clase": "alambres",
        "categorias": {
            "alambre-negro": "ALAMBRE NEGRO",
            "alambre-galvanizado": "ALAMBRE GALVANIZADO",
            "alambre-tejido": "ALAMBRE TEJIDO",
            "boyero-vid": "BOYERO / VID",
            "mediana-y-alta-resistencia": "MEDIANA Y ALTA RESISTENCIA",
            "mallas-job-shop": "MALLAS JOB-SHOP",
        },
    },
    "cumbreras": {
        "nombre": "CUMBRERAS", "orden": 7, "color": "var(--grp-cumbreras)",
        "clase": "cumbreras",
        "categorias": {
            "cumbreras-cinca-acan": "CUMBRERAS CINCA ACAN",
            "cumbreras-cinca-t101": "CUMBRERAS CINCA T101",
            "cumbreras-otros-materiales": "OTROS MATERIALES",
        },
    },
    "varios": {
        "nombre": "VARIOS", "orden": 8, "color": "var(--grp-varios)",
        "clase": "varios",
        "categorias": {},  # dinámico, se carga desde la DB
    },
}

# Slugs reservados que NO son grupos (evita que el catch-all 2-segmentos los pise)
SLUGS_RESERVADOS = {
    "admin", "mi-cuenta", "facturas", "factura", "pagos", "login", "logout",
    "carrito", "api", "rubros", "static", "rubro", "producto", "buscar",
}


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

# Helper: devuelve el filename de la imagen de una categoria.
# Solo busca la imagen propia de la categoria ({slug_cat}.jpg).
# Si no existe, devuelve None y el template muestra el SVG placeholder.
# (Antes habia fallback a _grupo_{slug_grupo}.jpg; Fernando lo saco porque
# hacia que varias categorias sin foto compartan la misma imagen de grupo.)
CAT_IMG_DIR = os.path.join(BASE_DIR, "static", "img", "categorias")


def _cat_img_filename(slug_grupo, slug_cat):
    """Devuelve el filename .jpg de la imagen o None si no hay."""
    cand_cat = os.path.join(CAT_IMG_DIR, f"{slug_cat}.jpg")
    if os.path.exists(cand_cat):
        return f"{slug_cat}.jpg"
    return None


@app.route("/", endpoint="rubros")
@login_required
def index():
    """Index v2: muestra los 8 grupos con sus categorias + counts.
    Si el cliente no completo los 7 datos obligatorios, activa
    show_welcome_modal para que el template muestre el modal full-screen."""
    # Bloque E - check de datos incompletos (clientes no-admin)
    if not session.get("is_admin"):
        cid = session["cliente_id"]
        conn = get_db()
        cli_row = conn.execute(
            "SELECT nombre, razon_social, cuit, direccion, localidad, telefono, email FROM clientes WHERE id = ?",
            (cid,)
        ).fetchone()
        conn.close()
        campos_oblig = ("nombre", "razon_social", "cuit", "direccion", "localidad", "telefono", "email")
        if cli_row and any(not (cli_row[c] if c in cli_row.keys() else None) for c in campos_oblig):
            session["show_welcome_modal"] = True
        else:
            # Los 7 datos ya estan cargados: limpiar el flag para que el
            # modal desaparezca definitivamente.
            session.pop("show_welcome_modal", None)
    return _render_index()


def _render_index():
    """Helper que renderiza la pagina de inicio (rubros). Usado por index()."""
    conn = get_db()
    # Trae todos los (slug_grupo, slug_categoria) con count
    rows = conn.execute("""
        SELECT slug_grupo, slug_categoria, COUNT(*) AS count
        FROM productos
        WHERE slug_grupo IS NOT NULL AND slug_categoria IS NOT NULL
        GROUP BY slug_grupo, slug_categoria
    """).fetchall()
    conn.close()
    conn = get_db()
    # Trae todos los (slug_grupo, slug_categoria) con count
    rows = conn.execute("""
        SELECT slug_grupo, slug_categoria, COUNT(*) AS count
        FROM productos
        WHERE slug_grupo IS NOT NULL AND slug_categoria IS NOT NULL
        GROUP BY slug_grupo, slug_categoria
    """).fetchall()
    conn.close()

    # Arma dict {slug_grupo: {slug_categoria: count}}
    counts = {}
    for r in rows:
        counts.setdefault(r["slug_grupo"], {})[r["slug_categoria"]] = r["count"]

    # Construye la estructura para el template
    grupos_v2 = []
    for slug_grupo, meta in sorted(GRUPOS_META.items(), key=lambda x: x[1]["orden"]):
        cats_known = meta["categorias"]
        if slug_grupo == "varios":
            # Varios: las categorias son los slugs de la DB que aparecen bajo "varios"
            cats_presentes = counts.get("varios", {})
            # Mantiene solo las que NO estan en otros grupos
            cat_list = [(slug, slug.upper().replace("-", " "), n) for slug, n in cats_presentes.items()]
            cat_list.sort(key=lambda x: x[0])
        else:
            # Solo muestra las categorias que tienen productos
            cat_list = []
            for slug_cat, nombre in cats_known.items():
                n = counts.get(slug_grupo, {}).get(slug_cat, 0)
                if n > 0:
                    cat_list.append((slug_cat, nombre, n))
        if not cat_list:
            continue
        # Anota la URL de imagen por categoria (slug_cat > _grupo_slug_grupo > None)
        cats_con_img = []
        for slug_cat, nombre, n in cat_list:
            img = _cat_img_filename(slug_grupo, slug_cat)
            cats_con_img.append((slug_cat, nombre, n, img))
        grupos_v2.append({
            "slug": slug_grupo,
            "nombre": meta["nombre"],
            "color": meta["color"],
            "clase": meta["clase"],
            "orden": meta["orden"],
            "categorias": cats_con_img,
        })

    return render_template(
        "rubros.html",
        grupos=grupos_v2,
        cliente=session.get("cliente_nombre"),
        is_admin=session.get("is_admin"),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    new_device_token = None
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        password = request.form.get("password", "")
        # Device token que el cliente manda (puede estar vacio = primer login
        # o cookies borradas).
        sent_device = (
            request.form.get("device_token", "")
            or request.cookies.get("hn_device_token", "")
        ).strip()
        if not usuario or not password:
            error = "Ingresá usuario y contraseña."
        else:
            conn = get_db()
            row = conn.execute(
                "SELECT * FROM clientes WHERE usuario = ? AND activo = 1",
                (usuario,),
            ).fetchone()
            if row and check_password_hash(row["password_hash"], password):
                db_token = (row["device_token"] or "").strip()
                is_admin = bool(row["is_admin"])
                # Bloque A — device-binding.
                # Admin: no se valida device.
                # No-admin: si DB tiene token y el cliente mando uno distinto -> bloquea.
                if not is_admin and db_token and sent_device and sent_device != db_token:
                    conn.close()
                    error = (
                        "Este usuario está activo en otro dispositivo. "
                        "Contactanos para liberar el acceso."
                    )
                else:
                    # OK: abrir sesion.
                    session.clear()
                    session["cliente_id"] = row["id"]
                    session["cliente_nombre"] = row["nombre"]
                    session["cliente_cod"] = row["cod_cliente"] or ""
                    session["cliente_email"] = row["email"] or ""
                    session["cliente_telefono"] = row["telefono"] or ""
                    session["cliente_direccion"] = row["direccion"] or ""
                    session["is_admin"] = is_admin

                    # Si no-admin y no tiene device, generar uno nuevo.
                    # (Tambien si el cliente no mando token, se regenera.)
                    if not is_admin and not db_token:
                        new_device_token = secrets.token_hex(32)
                        device_label = (request.user_agent.string or "")[:200]
                        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        conn.execute(
                            """UPDATE clientes
                               SET device_token = ?,
                                   device_first_login = COALESCE(device_first_login, ?),
                                   device_last_login = ?,
                                   device_label = COALESCE(NULLIF(device_label, ''), ?)
                               WHERE id = ?""",
                            (new_device_token, now_iso, now_iso, device_label, row["id"]),
                        )
                    elif not is_admin and db_token:
                        # Cliente existente, solo actualizar last_login.
                        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        conn.execute(
                            "UPDATE clientes SET device_last_login = ? WHERE id = ?",
                            (now_iso, row["id"]),
                        )

                    conn.commit()
                    conn.close()

                    # Bloque E: si el cliente (no-admin) no lleno los 7
                    # datos obligatorios, redirigir a /mi-cuenta/completar
                    # en lugar de la home. Es obligatorio completar antes
                    # de poder hacer pedidos.
                    cli_check = get_db()
                    cli_row = cli_check.execute(
                        "SELECT nombre, razon_social, cuit, direccion, localidad, telefono, email FROM clientes WHERE id = ?",
                        (row["id"],)
                    ).fetchone()
                    cli_check.close()
                    campos_oblig_login = ("nombre", "razon_social", "cuit", "direccion", "localidad", "telefono", "email", "tipo_cliente")
                    faltan_datos = (
                        not is_admin
                        and cli_row
                        and any(not (cli_row[c] if c in cli_row.keys() else None) for c in campos_oblig_login)
                    )
                    nxt = request.args.get("next")
                    if not nxt:
                        if faltan_datos:
                            # El template del home (rubros.html) detecta
                            # este flag y muestra el modal full-screen
                            # bloqueante con los 7 campos.
                            session["show_welcome_modal"] = True
                            nxt = url_for("rubros")
                        else:
                            # Cliente ya completo: limpiar flag por las dudas
                            session.pop("show_welcome_modal", None)
                            nxt = url_for("rubros")
                    resp = redirect(nxt)
                    if new_device_token:
                        # Cookie persistente 5 anios.
                        resp.set_cookie(
                            "hn_device_token",
                            new_device_token,
                            max_age=5 * 365 * 24 * 60 * 60,
                            httponly=False,  # el JS necesita leerla
                            samesite="Lax",
                        )
                    return resp
            else:
                conn.close()
                error = "Usuario o contraseña incorrectos."
    response = render_template("login.html", error=error, new_device_token=new_device_token)
    if new_device_token:
        # Render template: el token nuevo va al hidden field del form para que
        # el JS lo guarde en localStorage en el primer submit OK.
        # Pero como el token YA se setea como cookie arriba, el JS puede leerlo
        # de ahi. Aun asi, lo exponemos en el contexto para que el template
        # lo pueda usar si hace falta.
        pass
    return response


@app.route("/logout")
def logout():
    # Bloque A — logout: NO borra device_token de la DB. Solo limpia la sesion.
    # Asi si el cliente vuelve a entrar desde la misma PC, reconoce el device.
    session.clear()
    return redirect(url_for("login"))


# -----------------------------------------------------------------------------
# Productos por categoria v2 — /<grupo>/<categoria>
# -----------------------------------------------------------------------------

@app.route("/<slug_grupo>/<slug_categoria>")
@login_required
def productos_por_categoria(slug_grupo, slug_categoria):
    if slug_grupo in SLUGS_RESERVADOS:
        abort(404)
    if slug_grupo not in GRUPOS_META:
        abort(404)
    grupo_meta = GRUPOS_META[slug_grupo]
    if slug_grupo != "varios" and slug_categoria not in grupo_meta["categorias"]:
        abort(404)

    conn = get_db()
    prods = conn.execute("""
        SELECT * FROM productos
        WHERE slug_grupo = ? AND slug_categoria = ?
        ORDER BY descripcion
    """, (slug_grupo, slug_categoria)).fetchall()
    cli = conn.execute(
        "SELECT descuento_adn, descuento_cemento, descuento_resto FROM clientes WHERE id = ?",
        (session["cliente_id"],),
    ).fetchone()
    conn.close()
    descuentos = None
    if cli:
        descuentos = {
            "adn": cli["descuento_adn"],
            "cemento": cli["descuento_cemento"],
            "resto": cli["descuento_resto"],
        }

    items = []
    for p in prods:
        precio_final = precio_con_descuento_cliente(p["precio_lista"], p["cod"], p["rubro"], descuentos)
        items.append({
            "cod": p["cod"],
            "desc": p["descripcion"],
            "precio_lista": p["precio_lista"],
            "precio_final": precio_final,
            "tipo": p["tipo_descuento"],
            "unidad_venta": p["unidad_venta"] or "unidad",
            "configurable_en_metros": p["configurable_en_metros"] or 0,
            "largo_default": p["largo_default"] or 0,
        })
    items.sort(key=lambda x: size_key(x["desc"]))

    # Filter buckets para sub-filtrar client-side (por categoria)
    # Cada bucket = (slug, label, lista de cod_prefixes que matchean, o None para TODOS)
    filter_buckets = None
    if (slug_grupo, slug_categoria) == ("canos", "canos-estructurales"):
        # Distribucion real en DB: ESC=57, ESR=58, EST=93, ESP=2 (suma 210).
        # Los 2 ESP (OVALADO/PASAMANO) aparecen en TODOS sin sub-boton propio (opcion B).
        filter_buckets = [
            {"slug": "todos",        "label": "TODOS",          "prefixes": None, "count": 210},
            {"slug": "cuadrados",    "label": "CUADRADOS",      "prefixes": ["ESC"], "count": 57},
            {"slug": "redondos",     "label": "REDONDOS",       "prefixes": ["ESR"], "count": 58},
            {"slug": "rectangulares","label": "RECTANGULARES",  "prefixes": ["EST"], "count": 93},
        ]
    elif (slug_grupo, slug_categoria) == ("perfiles", "perfiles-c"):
        # Distribucion real: 52 productos (34 PC* = negro, 18 PCG* = galvanizado).
        # Orden importante: GALVANIZADO va antes que NEGRO porque 'PCG...'.startswith('PC') == True.
        filter_buckets = [
            {"slug": "todos",         "label": "TODOS",        "prefixes": None,     "count": 52},
            {"slug": "galvanizado",   "label": "GALVANIZADO",  "prefixes": ["PCG"],  "count": 18},
            {"slug": "negro",         "label": "NEGRO",        "prefixes": ["PC"],   "count": 34},
        ]
    elif (slug_grupo, slug_categoria) == ("perfiles", "perfiles-comerciales"):
        # Distribucion real: 180 productos. Orden importante:
        # - PLP antes que PL (PLP empieza con PL)
        # - HUC antes que HU (HUC empieza con HU)
        # - HT (Hierro Tee) y PU (Perfil U) caen en el bucket de IPN/UPN/U CHICO (son perfiles metalicos)
        filter_buckets = [
            {"slug": "todos",                    "label": "TODOS",                "prefixes": None,            "count": 180},
            {"slug": "angulos",                  "label": "ANGULOS",              "prefixes": ["AN"],           "count": 44},
            {"slug": "planchuelas-perforadas",   "label": "PLANCH. PERFORADAS",   "prefixes": ["PLP"],          "count": 9},
            {"slug": "planchuelas",              "label": "PLANCHUELAS",          "prefixes": ["PL"],           "count": 89},
            {"slug": "ipn-upn-uchico",           "label": "IPN / UPN / U CHICO",  "prefixes": ["HUC", "HU", "HI", "HT", "PU"], "count": 29},
            {"slug": "hierros-herreros",         "label": "HIERROS HERREROS",     "prefixes": ["HC", "REDONDO"], "count": 23},
        ]
    if filter_buckets:
        # Asignar bucket a cada item segun cod_prefix
        for it in items:
            it["bucket"] = "todos"
            for b in filter_buckets:
                if b["prefixes"] is None:
                    continue
                if any(it["cod"].startswith(p) for p in b["prefixes"]):
                    it["bucket"] = b["slug"]
                    break

    # Nombre visible
    if slug_grupo == "varios":
        cat_nombre = slug_categoria.upper().replace("-", " ")
    else:
        cat_nombre = grupo_meta["categorias"].get(slug_categoria, slug_categoria)

    return render_template(
        "productos.html",
        rubro=f"{grupo_meta['nombre']} / {cat_nombre}",
        grupo_nombre=grupo_meta["nombre"],
        grupo_slug=slug_grupo,
        categoria_nombre=cat_nombre,
        categoria_slug=slug_categoria,
        grupo_color=grupo_meta["color"],
        items=items,
        filter_buckets=filter_buckets,
        fmt=fmt_money,
    )


# Compatibilidad: /rubro/<path> redirige a / si existe match, si no 404
@app.route("/rubro/<path:rubro>")
@login_required
def productos_rubro(rubro):
    # Busca por rubro exacto en la nueva columna
    conn = get_db()
    row = conn.execute("""
        SELECT slug_grupo, slug_categoria FROM productos WHERE rubro = ? LIMIT 1
    """, (rubro,)).fetchone()
    conn.close()
    if row and row["slug_grupo"] and row["slug_categoria"]:
        return redirect(url_for("productos_por_categoria",
                                slug_grupo=row["slug_grupo"],
                                slug_categoria=row["slug_categoria"]))
    abort(404)


# -----------------------------------------------------------------------------
# Detalle
# -----------------------------------------------------------------------------

@app.route("/producto/<cod>")
@login_required
def detalle(cod):
    conn = get_db()
    p = conn.execute("SELECT * FROM productos WHERE cod = ?", (cod,)).fetchone()
    if not p:
        conn.close(); abort(404)
    cli = conn.execute(
        "SELECT descuento_adn, descuento_cemento, descuento_resto FROM clientes WHERE id = ?",
        (session["cliente_id"],),
    ).fetchone()
    conn.close()
    descuentos = None
    if cli:
        descuentos = {
            "adn": cli["descuento_adn"],
            "cemento": cli["descuento_cemento"],
            "resto": cli["descuento_resto"],
        }
    precio_final = precio_con_descuento_cliente(p["precio_lista"], p["cod"], p["rubro"], descuentos)
    descuento_pct = _descuento_para_producto(p["cod"], p["rubro"], descuentos)
    return render_template(
        "detalle.html",
        p={
            "cod": p["cod"],
            "desc": p["descripcion"],
            "rubro": p["rubro"],
            "grupo": p["grupo"],
            "precio_lista": p["precio_lista"],
            "precio_final": precio_final,
            "tipo": p["tipo_descuento"],
            "unidad_venta": p["unidad_venta"] or "unidad",
            "descuento_pct": descuento_pct,
            "slug_grupo": p["slug_grupo"] or "",
            "slug_categoria": p["slug_categoria"] or "",
            "largo_default": p["largo_default"] or 0,
        },
        fmt=fmt_money,
    )


# -----------------------------------------------------------------------------
# Búsqueda
# -----------------------------------------------------------------------------

@app.route("/buscar")
@login_required
def buscar():
    q = (request.args.get("q") or "").strip()
    results = []
    if q:
        conn = get_db()
        like = f"%{q}%"
        rows = conn.execute(
            """SELECT * FROM productos
               WHERE cod LIKE ? OR descripcion LIKE ?
               ORDER BY rubro, descripcion
               LIMIT 100""",
            (like, like),
        ).fetchall()
        cli = conn.execute(
            "SELECT descuento_adn, descuento_cemento, descuento_resto FROM clientes WHERE id = ?",
            (session["cliente_id"],),
        ).fetchone()
        conn.close()
        descuentos = None
        if cli:
            descuentos = {
                "adn": cli["descuento_adn"],
                "cemento": cli["descuento_cemento"],
                "resto": cli["descuento_resto"],
            }
        for p in rows:
            precio_final = precio_con_descuento_cliente(p["precio_lista"], p["cod"], p["rubro"], descuentos)
            results.append({
                "cod": p["cod"],
                "desc": p["descripcion"],
                "rubro": p["rubro"],
                "precio_final": precio_final,
                "unidad_venta": p["unidad_venta"] or "unidad",
            })
    return render_template("buscar.html", q=q, results=results, fmt=fmt_money)


# API JSON para live search
@app.route("/api/buscar")
@login_required
def api_buscar():
    q = (request.args.get("q") or "").strip()
    if not q or len(q) < 2:
        return jsonify([])
    conn = get_db()
    like = f"%{q}%"
    rows = conn.execute(
        """SELECT cod, descripcion, rubro, precio_lista, tipo_descuento, unidad_venta
           FROM productos
           WHERE cod LIKE ? OR descripcion LIKE ?
           ORDER BY rubro, descripcion
           LIMIT 30""",
        (like, like),
    ).fetchall()
    cli = conn.execute(
        "SELECT descuento_adn, descuento_cemento, descuento_resto FROM clientes WHERE id = ?",
        (session["cliente_id"],),
    ).fetchone()
    conn.close()
    descuentos = None
    if cli:
        descuentos = {
            "adn": cli["descuento_adn"],
            "cemento": cli["descuento_cemento"],
            "resto": cli["descuento_resto"],
        }
    out = []
    for p in rows:
        out.append({
            "cod": p["cod"],
            "desc": p["descripcion"],
            "rubro": p["rubro"],
            "precio_final": precio_con_descuento_cliente(p["precio_lista"], p["cod"], p["rubro"], descuentos),
            "unidad_venta": p["unidad_venta"] or "unidad",
        })
    return jsonify(out)


# FIX 3 — API para obtener info de un producto por cod (usado en admin_pedido_editar
# para agregar/quitar items). Nombre de funcion y endpoint unicos a proposito
# para evitar colision con cualquier otro route.
@app.route("/api/admin/pedido/producto/<cod>", endpoint="api_admin_pedido_producto")
@login_required
def api_admin_pedido_producto(cod):
    """Devuelve JSON con los datos basicos de un producto."""
    conn = get_db()
    row = conn.execute(
        "SELECT cod, descripcion, rubro, precio_lista, unidad_venta, largo_default FROM productos WHERE cod = ?",
        (cod,),
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": "Producto no encontrado"}), 404
    return jsonify({
        "ok": True,
        "cod": row["cod"],
        "descripcion": row["descripcion"],
        "rubro": row["rubro"],
        "precio_lista": row["precio_lista"],
        "unidad_venta": row["unidad_venta"] or "unidad",
        "largo_default": row["largo_default"] or 0,
    })


# -----------------------------------------------------------------------------
# Carrito — vista
# -----------------------------------------------------------------------------

@app.route("/carrito")
@login_required
def carrito():
    return render_template("carrito.html", fmt=fmt_money)


# -----------------------------------------------------------------------------
# Config de contacto (la consume el front para armar links de WhatsApp/email)
# -----------------------------------------------------------------------------

CONTACTO = {
    "nombre": "HIERRONORT",
    "whatsapp": "+5493804104613",   # numero real configurado
    "email": "ventas@hierronort.com.ar",
}


@app.route("/api/contacto")
def api_contacto():
    return jsonify(CONTACTO)


# -----------------------------------------------------------------------------
# Cotizar: manda mail al admin cuando el WA esta en placeholder,
# o devuelve link de WhatsApp cuando ya esta configurado.
# Credenciales SMTP se leen de variables de entorno (PA las tiene en
# /home/<user>/.env o se setean en el panel web).
# -----------------------------------------------------------------------------

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def _es_placeholder_wa(wa):
    """True si el numero de WhatsApp es un placeholder o vacio."""
    if not wa:
        return True
    placeholders = ("+5491155555555", "+5491100000000", "+5491111111111")
    return wa.strip() in placeholders


def _smtp_config():
    """Lee config SMTP de env vars (con fallback a defaults PA)."""
    user = os.environ.get("SMTP_USER", "hierronort")
    password = os.environ.get("SMTP_PASSWORD", "")
    host = os.environ.get("SMTP_HOST", "smtp.pythonanywhere.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    from_addr = os.environ.get("SMTP_FROM", f"no-reply@{user}.pythonanywhere.com")
    to_addr = os.environ.get("SMTP_TO", "ventas@hierronort.com.ar")
    return {
        "host": host, "port": port, "user": user, "password": password,
        "from": from_addr, "to": to_addr,
    }


def _armar_texto_pedido(items, total, cliente):
    """Genera el texto del pedido en texto plano (para el cuerpo del mail)."""
    lineas = []
    lineas.append(f"Pedido de: {cliente.get('nombre', '?')} ({cliente.get('cod_cliente', '?')})")
    if cliente.get("email"):
        lineas.append(f"Email: {cliente['email']}")
    if cliente.get("telefono"):
        lineas.append(f"Telefono: {cliente['telefono']}")
    if cliente.get("direccion"):
        lineas.append(f"Direccion: {cliente['direccion']}")
    lineas.append("")
    lineas.append("ITEMS:")
    lineas.append("-" * 60)
    for it in items:
        cant = it.get("cantidad", 0)
        desc = it.get("desc", "?")
        cod = it.get("cod", "?")
        uv = it.get("unidad_venta", "unidad")
        precio = it.get("precio_por", 0)
        if uv == "metro":
            largo = it.get("largo", 0)
            sub = cant * largo * precio
            lineas.append(f"  {cod}  {desc}")
            lineas.append(f"        {cant} u x {largo} m x ${precio:,.2f}/m = ${sub:,.2f}")
        elif uv == "kg":
            kilos = it.get("kilos", cant)
            sub = kilos * precio
            lineas.append(f"  {cod}  {desc}")
            lineas.append(f"        {kilos} kg x ${precio:,.2f}/kg = ${sub:,.2f}")
        else:
            sub = cant * precio
            lineas.append(f"  {cod}  {desc}")
            lineas.append(f"        {cant} u x ${precio:,.2f}/u = ${sub:,.2f}")
    lineas.append("-" * 60)
    lineas.append(f"TOTAL: ${total:,.2f}")
    return "\n".join(lineas)


@app.route("/api/cotizar", methods=["POST"])
def api_cotizar():
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    total = float(data.get("total", 0) or 0)
    cliente = data.get("cliente", {})

    if not items:
        return jsonify({"ok": False, "error": "Carrito vacio."}), 400

    # Si WA es placeholder -> mandar mail
    if _es_placeholder_wa(CONTACTO.get("whatsapp", "")):
        try:
            cfg = _smtp_config()
            if not cfg["password"]:
                return jsonify({
                    "ok": False,
                    "error": "SMTP no configurado. Setea SMTP_PASSWORD en el .env del server."
                }), 500
            cuerpo = _armar_texto_pedido(items, total, cliente)
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Pedido HIERRONORT — {cliente.get('nombre', 'sin nombre')}"
            msg["From"] = cfg["from"]
            msg["To"] = cfg["to"]
            msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
            with smtplib.SMTP(cfg["host"], cfg["port"]) as s:
                s.starttls()
                s.login(cfg["user"], cfg["password"])
                s.sendmail(cfg["from"], [cfg["to"]], msg.as_string())
            return jsonify({
                "ok": True,
                "modo": "email",
                "mensaje": "Te enviamos tu pedido por email. Te respondemos a la brevedad."
            })
        except Exception as e:
            return jsonify({"ok": False, "error": f"Error mandando email: {e}"}), 500

    # Si WA esta configurado -> devolver link de WhatsApp
    else:
        from urllib.parse import quote
        phone = CONTACTO["whatsapp"].replace("+", "").replace(" ", "")
        texto = _armar_texto_pedido(items, total, cliente)
        link = f"https://wa.me/{phone}?text={quote(texto)}"
        return jsonify({"ok": True, "modo": "whatsapp", "link": link})


# -----------------------------------------------------------------------------
# Pedido formal: genera PDF, guarda en DB, manda mail con PDF adjunto.
# Reemplaza /api/cotizar cuando el cliente confirma el modal con los datos
# logísticos. El PDF lo recibe Fer por mail; el cliente puede descargarlo
# desde el link /api/pedido/<nro>/pdf.
# -----------------------------------------------------------------------------

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)


def _generar_nro_pedido(conn):
    """Genera un nro de pedido WEB-YYYYMMDD-NNN correlativo del dia."""
    hoy = datetime.now()
    prefijo = hoy.strftime("WEB-%Y%m%d-")
    row = conn.execute(
        "SELECT COUNT(*) FROM pedidos WHERE nro LIKE ?", (prefijo + "%",)
    ).fetchone()
    n = (row[0] or 0) + 1
    return f"{prefijo}{n:03d}"


def _fmt_money_pdf(v):
    """Formatea un numero como $X.XXX,XX (es-AR, 2 decimales)."""
    if v is None:
        v = 0
    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {s}"


def _subtotal_item_pedido(it):
    """Subtotal de un item del pedido (server-side, fuente de verdad)."""
    cant = it.get("cantidad", 0) or 0
    precio = float(it.get("precio_por", 0) or 0)
    uv = (it.get("unidad_venta") or "unidad").lower()
    if uv == "metro":
        largo = float(it.get("largo", 0) or 0)
        return cant * largo * precio
    if uv == "kg":
        kilos = float(it.get("kilos", cant) or 0)
        return kilos * precio
    if uv == "servicio":
        # Servicio: cantidad * precio (caso seguro de carga, cant=1).
        return float(cant) * precio
    # unidad default
    largo_def = float(it.get("largo_default", 0) or 0)
    if largo_def > 1:
        return cant * largo_def * precio
    return cant * precio


def _linea_item_pdf(it, styles):
    """Genera la representacion de un item del PDF (desc, calc, sub)."""
    cant = it.get("cantidad", 0) or 0
    desc = it.get("desc", "?")
    cod = it.get("cod", "?")
    uv = (it.get("unidad_venta") or "unidad").lower()
    precio = float(it.get("precio_por", 0) or 0)

    if uv == "metro":
        largo = float(it.get("largo", 0) or 0)
        sub = _subtotal_item_pedido(it)
        cant_str = f"{cant} u"
        precio_str = f"{_fmt_money_pdf(precio)}/m"
        calc_str = f"{cant} u x {largo} m"
        sub_str = _fmt_money_pdf(sub)
    elif uv == "kg":
        kilos = float(it.get("kilos", cant) or 0)
        sub = _subtotal_item_pedido(it)
        cant_str = f"{kilos:g} kg"
        precio_str = f"{_fmt_money_pdf(precio)}/kg"
        calc_str = f"{kilos:g} kg"
        sub_str = _fmt_money_pdf(sub)
    elif uv == "servicio":
        sub = _subtotal_item_pedido(it)
        cant_str = f"{cant:g} u"
        calc_str = f"{cant:g} u"
        sub_str = _fmt_money_pdf(sub)
        precio_str = _fmt_money_pdf(precio)
    else:
        # Si tiene largo_default > 1 (ej: Perfiles C de 12m) el subtotal es
        # cant * largo_default * precio. Mostramos "X u · Y m" en calc.
        largo_def = float(it.get("largo_default", 0) or 0)
        if largo_def > 1:
            sub = _subtotal_item_pedido(it)
            cant_str = f"{cant:g} u"
            calc_str = f"{cant:g} u x {largo_def:g} m"
            sub_str = _fmt_money_pdf(sub)
        else:
            sub = _subtotal_item_pedido(it)
            cant_str = f"{cant:g} u"
            calc_str = f"{cant:g} u"
            sub_str = _fmt_money_pdf(sub)
        precio_str = _fmt_money_pdf(precio)

    return {
        "cod": cod, "desc": desc, "cant": cant_str, "calc": calc_str,
        "precio_str": precio_str, "sub_str": sub_str, "sub": sub,
    }


def _calcular_seguro_carga(localidad, lugar_entrega):
    """Devuelve el item del seguro de carga o None.

    Reglas (V2.15 — seguro de carga):
      - lugar_entrega == 'retira'   -> None (no se cobra seguro).
      - lugar_entrega == 'domicilio':
          - localidad contiene 'LA RIOJA' -> Capital  $16.000.
          - resto (incluye vacio/NULL)    -> Interior $30.000 (edge case a).
    """
    if (lugar_entrega or "").strip().lower() != "domicilio":
        return None
    loc = (localidad or "").strip().upper()
    if "LA RIOJA" in loc:
        return {
            "cod": "ENVIO-CAP",
            "desc": "Seguro de carga (Capital)",
            "cantidad": 1,
            "unidad_venta": "servicio",
            "precio_por": 16000.0,
        }
    # Incluye: localidad vacia, NULL, otra provincia, etc.
    return {
        "cod": "ENVIO-INT",
        "desc": "Seguro de carga (Interior)",
        "cantidad": 1,
        "unidad_venta": "servicio",
        "precio_por": 30000.0,
    }


def _armar_pdf_pedido(items, total, cliente, logistica, nro, fecha_hora):
    """Devuelve los bytes del PDF del pedido."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Pedido {nro} - HIERRONORT",
    )
    styles = getSampleStyleSheet()

    s_brand = ParagraphStyle(
        "brand", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=20, textColor=colors.HexColor("#c0392b"),
    )
    s_sub = ParagraphStyle(
        "sub", parent=styles["Normal"], fontSize=8.5,
        textColor=colors.HexColor("#6b6660"),
    )
    s_h1 = ParagraphStyle(
        "h1", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=14, textColor=colors.HexColor("#1a1a1a"),
    )
    s_h3 = ParagraphStyle(
        "h3", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=9, textColor=colors.HexColor("#6b6660"),
    )
    s_body = ParagraphStyle(
        "body", parent=styles["Normal"], fontSize=10,
        textColor=colors.HexColor("#1a1a1a"), leading=13,
    )
    s_nota = ParagraphStyle(
        "nota", parent=styles["Normal"], fontSize=9.5,
        textColor=colors.HexColor("#1a1a1a"), leading=12,
    )
    s_total_lbl = ParagraphStyle(
        "totallbl", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10, textColor=colors.HexColor("#27ae60"),
    )
    s_total_val = ParagraphStyle(
        "totalval", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=20, textColor=colors.HexColor("#27ae60"),
    )

    story = []

    # --- Header: brand izq / nro y fecha der
    header_data = [[
        Paragraph("HIERRONORT<br/><font size=8 color='#6b6660'>"
                  "Lista de precios mayorista</font>", s_brand),
        Paragraph(
            f"<font size=11 color='#1a1a1a'><b>{nro}</b></font><br/>"
            f"<font size=9 color='#6b6660'>{fecha_hora}</font>",
            ParagraphStyle("right", parent=styles["Normal"], alignment=2),
        ),
    ]]
    header_tbl = Table(header_data, colWidths=[110 * mm, 60 * mm])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(header_tbl)
    story.append(HRFlowable(width="100%", thickness=2,
                            color=colors.HexColor("#c0392b"),
                            spaceBefore=2, spaceAfter=10))

    # --- Titulo
    story.append(Paragraph("Pedido desde la web", s_h1))
    story.append(Paragraph(
        "Precios mayoristas con descuento aplicado",
        s_sub,
    ))
    story.append(Spacer(1, 6 * mm))

    # --- Cliente
    story.append(Paragraph("CLIENTE", s_h3))
    cliente_lines = []
    nombre = cliente.get("nombre", "?")
    if cliente.get("cod_cliente"):
        nombre = f"{nombre} (cód. {cliente['cod_cliente']})"
    cliente_lines.append(Paragraph(f"<b>{nombre}</b>", s_body))
    contacto = []
    if cliente.get("email"):
        contacto.append(cliente["email"])
    if cliente.get("telefono"):
        contacto.append(cliente["telefono"])
    if contacto:
        cliente_lines.append(Paragraph(" · ".join(contacto), s_body))
    if cliente.get("direccion"):
        cliente_lines.append(Paragraph(cliente["direccion"], s_body))
    story.extend(cliente_lines)
    story.append(Spacer(1, 5 * mm))

    # --- Items
    story.append(Paragraph("ITEMS DEL PEDIDO", s_h3))
    story.append(Spacer(1, 1 * mm))

    data = [["Cód.", "Descripción", "Cantidad", "Precio", "Subtotal"]]
    for it in items:
        info = _linea_item_pdf(it, styles)
        # Descripcion + (calculo) en una sola celda con dos renglones
        desc_html = (f"<b>{info['desc']}</b><br/>"
                     f"<font size=8 color='#6b6660'>{info['calc']}</font>")
        data.append([
            Paragraph(f"<font face='Courier' size=9 color='#2980b9'>"
                      f"<b>{info['cod']}</b></font>", s_body),
            Paragraph(desc_html, s_body),
            Paragraph(info["cant"], ParagraphStyle(
                "r", parent=s_body, alignment=2)),
            Paragraph(info["precio_str"], ParagraphStyle(
                "r", parent=s_body, alignment=2)),
            Paragraph(f"<b>{info['sub_str']}</b>", ParagraphStyle(
                "r", parent=s_body, alignment=2)),
        ])

    tbl = Table(
        data,
        colWidths=[22 * mm, 78 * mm, 22 * mm, 22 * mm, 28 * mm],
        repeatRows=1,
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f3ee")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#6b6660")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#e2ddd6")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#f0ede8")),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 4 * mm))

    # --- Total destacado
    total_data = [[
        Paragraph("TOTAL", s_total_lbl),
        Paragraph(_fmt_money_pdf(total), s_total_val),
    ]]
    total_tbl = Table(total_data, colWidths=[30 * mm, 50 * mm])
    total_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edfaf2")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#27ae60")),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    total_holder = Table(
        [[total_tbl]], colWidths=[170 * mm],
    )
    total_holder.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, 0), "RIGHT"),
    ]))
    story.append(total_holder)
    story.append(Spacer(1, 6 * mm))

    # --- Datos logisticos
    story.append(Paragraph("DATOS LOGÍSTICOS", s_h3))
    story.append(Spacer(1, 1 * mm))

    logi_data = [
        ["Forma de pago:", logistica.get("forma_pago", "?")],
        ["Lugar de entrega:", "Retira en local" if logistica.get("lugar_entrega") == "retira" else "Entrega a domicilio"],
        ["Quien retira/recibe:", f"{logistica.get('retira_nombre', '?')} · {logistica.get('retira_telefono', '?')}"],
    ]
    if logistica.get("lugar_entrega") == "domicilio" and logistica.get("retira_domicilio"):
        logi_data.append(["Domicilio de entrega:", logistica["retira_domicilio"]])
    if logistica.get("notas"):
        logi_data.append(["Notas:", logistica["notas"]])

    logi_rows = [[Paragraph(f"<b>{k}</b>", s_body), Paragraph(v, s_body)]
                 for k, v in logi_data]
    logi_tbl = Table(logi_rows, colWidths=[40 * mm, 130 * mm])
    logi_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(logi_tbl)
    story.append(Spacer(1, 6 * mm))

    # --- Footer
    story.append(HRFlowable(width="100%", thickness=0.5,
                            color=colors.HexColor("#e2ddd6"),
                            spaceBefore=2, spaceAfter=6))
    story.append(Paragraph(
        f"<para alignment='center'>"
        f"<font size=9 color='#1a1a1a'><b>HIERRONORT</b></font> "
        f"<font size=8 color='#6b6660'>"
        f"· {CONTACTO.get('email', 'ventas@hierronort.com.ar')}"
        f"</font><br/>"
        f"<font size=8 color='#6b6660'>"
        f"Te respondemos en las próximas 2 horas hábiles con "
        f"confirmación de stock y precio final."
        f"</font></para>",
        s_body,
    ))

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf


@app.route("/api/pedido", methods=["POST"])
@login_required
def api_pedido():
    """Genera un pedido formal: PDF + mail a Fer + nro de seguimiento."""
    # Bloque E - validacion: si el cliente no tiene los datos personales
    # minimos cargados, lo devolvemos al carrito con un mensaje y un
    # endpoint para que complete el perfil.
    conn = get_db()
    cli = conn.execute(
        "SELECT nombre, razon_social, cuit, direccion, localidad, telefono, email, tipo_cliente FROM clientes WHERE id = ?",
        (session["cliente_id"],)
    ).fetchone()
    conn.close()
    campos_oblig = ("nombre", "razon_social", "cuit", "direccion", "localidad", "telefono", "email", "tipo_cliente")
    faltantes = [c for c in campos_oblig if not (cli[c] if cli else None)]
    if faltantes:
        return jsonify({
            "ok": False,
            "error": "completa estos datos antes de hacer un pedido: " + ", ".join(faltantes),
            "redirect": url_for("mi_cuenta_completar"),
        }), 400
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    total = float(data.get("total", 0) or 0)
    cliente = data.get("cliente", {}) or {}
    logistica = data.get("logistica", {}) or {}

    if not items:
        return jsonify({"ok": False, "error": "Carrito vacio."}), 400

    # Validacion basica
    if not logistica.get("forma_pago") in ("efectivo", "transferencia", "cheque"):
        return jsonify({"ok": False, "error": "Forma de pago invalida."}), 400
    if not logistica.get("lugar_entrega") in ("retira", "domicilio"):
        return jsonify({"ok": False, "error": "Lugar de entrega invalido."}), 400
    if not (logistica.get("retira_nombre") or "").strip():
        return jsonify({"ok": False, "error": "Falta nombre de quien retira/recibe."}), 400
    if not (logistica.get("retira_telefono") or "").strip():
        return jsonify({"ok": False, "error": "Falta telefono de quien retira/recibe."}), 400
    if logistica["lugar_entrega"] == "domicilio" and not (logistica.get("retira_domicilio") or "").strip():
        return jsonify({"ok": False, "error": "Domicilio obligatorio para entrega a domicilio."}), 400

    # Datos del cliente logueado
    conn = get_db()
    cli_row = conn.execute(
        "SELECT * FROM clientes WHERE id = ?", (session["cliente_id"],)
    ).fetchone()
    if not cli_row:
        conn.close()
        return jsonify({"ok": False, "error": "Cliente no encontrado."}), 400
    cli_dict = dict(cli_row)
    # Mezclar lo que viene del front (puede traer datos actualizados)
    cli_full = {
        "nombre": cliente.get("nombre") or cli_dict.get("nombre", ""),
        "cod_cliente": cli_dict.get("cod_cliente", ""),
        "email": cliente.get("email") or cli_dict.get("email", ""),
        "telefono": cliente.get("telefono") or cli_dict.get("telefono", ""),
        "direccion": cliente.get("direccion") or cli_dict.get("direccion", ""),
    }

    # V2.15 — seguro de carga. Si la entrega es a domicilio, agregar item
    # ENVIO-CAP o ENVIO-INT segun la localidad del cliente. Recalcular total
    # en server-side (el front nunca sabe el monto real). El item se agrega
    # a la lista antes de generar PDF + INSERT.
    seguro_item = _calcular_seguro_carga(cli_dict.get("localidad", ""),
                                          logistica.get("lugar_entrega", ""))
    if seguro_item is not None:
        items = list(items) + [seguro_item]

    # V2.16 — descuentos por cliente. Sobrescribir precio_por de cada item con
    # el precio_lista con descuento segun mapeo (ADN/CEMENTO/RESTO). El front
    # puede haber enviado cualquier precio, pero la fuente de verdad es la DB.
    # items de tipo servicio (ENVIO-CAP, ENVIO-INT) se ignoran: ya tienen precio fijo.
    descuentos_cli = {
        "adn": cli_dict.get("descuento_adn"),
        "cemento": cli_dict.get("descuento_cemento"),
        "resto": cli_dict.get("descuento_resto"),
    }
    items_con_desc = []
    for it in items:
        it_copy = dict(it)
        cod = (it_copy.get("cod") or "").strip()
        # servicios del seguro de carga: respetar precio original
        if cod in ("ENVIO-CAP", "ENVIO-INT"):
            items_con_desc.append(it_copy)
            continue
        # buscar precio_lista y rubro en DB
        row = conn.execute(
            "SELECT precio_lista, rubro FROM productos WHERE cod = ?", (cod,)
        ).fetchone()
        if not row:
            # producto no existe: respetar lo que mando el front (caso raro)
            items_con_desc.append(it_copy)
            continue
        nuevo_precio = precio_con_descuento_cliente(
            row["precio_lista"], cod, row["rubro"], descuentos_cli
        )
        it_copy["precio_por"] = nuevo_precio
        items_con_desc.append(it_copy)
    items = items_con_desc
    total = sum(_subtotal_item_pedido(it) for it in items)

    # Generar nro y PDF
    nro = _generar_nro_pedido(conn)
    fecha_hora = datetime.now().strftime("%d/%m/%Y %H:%M hs")
    fecha_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        pdf_bytes = _armar_pdf_pedido(items, total, cli_full, logistica, nro, fecha_hora)
    except Exception as e:
        conn.close()
        return jsonify({"ok": False, "error": f"Error generando PDF: {e}"}), 500

    pdf_filename = f"Pedido_{nro}.pdf"

    # Guardar pedido en DB
    import json as _json
    mail_ok = False
    mail_error = None
    try:
        conn.execute(
            """INSERT INTO pedidos
               (nro, fecha_hora, cliente_id, cliente_nombre, cliente_cod,
                cliente_email, cliente_telefono, cliente_direccion,
                items_json, total,
                forma_pago, lugar_entrega,
                retira_nombre, retira_telefono, retira_domicilio, notas,
                pdf_bytes, pdf_filename, mail_enviado, estado)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'pendiente')""",
            (nro, fecha_iso, cli_dict["id"], cli_full["nombre"],
             cli_full["cod_cliente"], cli_full["email"],
             cli_full["telefono"], cli_full["direccion"],
             _json.dumps(items, ensure_ascii=False), total,
             logistica["forma_pago"], logistica["lugar_entrega"],
             logistica["retira_nombre"].strip(),
             logistica["retira_telefono"].strip(),
             (logistica.get("retira_domicilio") or "").strip() or None,
             (logistica.get("notas") or "").strip() or None,
             pdf_bytes, pdf_filename),
        )
        conn.commit()

        # Mandar mail a Fer con el PDF adjunto
        try:
            cfg = _smtp_config()
            if cfg["password"]:
                from email.mime.application import MIMEApplication
                msg = MIMEMultipart("mixed")
                msg["Subject"] = (
                    f"Pedido {nro} - {cli_full['nombre']} - "
                    f"${total:,.0f}"
                )
                msg["From"] = cfg["from"]
                msg["To"] = cfg["to"]

                cuerpo = _armar_texto_pedido(items, total, cli_full)
                cuerpo += "\n\n--- DATOS LOGISTICOS ---\n"
                fp_label = {"efectivo": "Efectivo", "transferencia": "Transferencia",
                            "cheque": "Cheque (a coordinar)"}.get(
                                logistica["forma_pago"], logistica["forma_pago"])
                le_label = "Retira en local" if logistica["lugar_entrega"] == "retira" \
                    else "Entrega a domicilio"
                cuerpo += f"Forma de pago: {fp_label}\n"
                cuerpo += f"Lugar de entrega: {le_label}\n"
                cuerpo += f"Retira/recibe: {logistica['retira_nombre']} · {logistica['retira_telefono']}\n"
                if logistica["lugar_entrega"] == "domicilio" and logistica.get("retira_domicilio"):
                    cuerpo += f"Domicilio de entrega: {logistica['retira_domicilio']}\n"
                if logistica.get("notas"):
                    cuerpo += f"Notas: {logistica['notas']}\n"

                msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
                part = MIMEApplication(pdf_bytes, Name=pdf_filename)
                part["Content-Disposition"] = (
                    f'attachment; filename="{pdf_filename}"'
                )
                msg.attach(part)
                with smtplib.SMTP(cfg["host"], cfg["port"]) as s:
                    s.starttls()
                    s.login(cfg["user"], cfg["password"])
                    s.sendmail(cfg["from"], [cfg["to"]], msg.as_string())
                mail_ok = True
            else:
                mail_error = "SMTP_PASSWORD no configurado (no se mando mail)"
        except Exception as e:
            mail_error = f"Error SMTP: {e}"

        # Marcar mail_enviado
        conn.execute(
            "UPDATE pedidos SET mail_enviado = ? WHERE nro = ?",
            (1 if mail_ok else 0, nro),
        )
        conn.commit()
    finally:
        conn.close()

    # Respuesta
    pdf_url = f"/api/pedido/{nro}/pdf"
    out = {
        "ok": True,
        "nro_pedido": nro,
        "pdf_url": pdf_url,
        "mail_enviado": mail_ok,
    }
    if mail_error:
        out["mail_error"] = mail_error

    # Si WA esta configurado, devolver link de WhatsApp
    if not _es_placeholder_wa(CONTACTO.get("whatsapp", "")):
        from urllib.parse import quote
        phone = CONTACTO["whatsapp"].replace("+", "").replace(" ", "")
        texto = (
            f"Hola! Te paso mi pedido desde la web.\n"
            f"Nro: {nro}\n"
            f"Total: ${total:,.2f}\n"
            f"Items: {len(items)}\n"
            f"Forma de pago: {logistica['forma_pago']}\n"
            f"Entrega: {'retira en local' if logistica['lugar_entrega'] == 'retira' else 'a domicilio'}\n\n"
            f"PDF: {request.host_url.rstrip('/')}{pdf_url}"
        )
        out["whatsapp_link"] = f"https://wa.me/{phone}?text={quote(texto)}"

    return jsonify(out)


@app.route("/api/pedido/<nro>/pdf")
@login_required
def api_pedido_pdf(nro):
    """Sirve el PDF binario del pedido."""
    conn = get_db()
    row = conn.execute(
        "SELECT pdf_bytes, pdf_filename, cliente_id FROM pedidos WHERE nro = ?",
        (nro,),
    ).fetchone()
    conn.close()
    if not row:
        abort(404)
    # El cliente solo puede descargar sus propios pedidos
    if row["cliente_id"] != session.get("cliente_id"):
        abort(403)
    return send_file(
        io.BytesIO(row["pdf_bytes"]),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=row["pdf_filename"] or f"{nro}.pdf",
    )


# V2.14 — Servir PDF de factura (cliente descarga la factura real, no el PDF del alta)
@app.route("/facturas/<nro>/pdf")
@login_required
def cliente_factura_pdf(nro):
    """Sirve el PDF de la factura. Si la factura tiene archivo_path, ese.
    Si no, fallback al PDF legacy del pedido.
    Solo el dueno de la factura puede descargarla (o admin)."""
    is_admin = session.get("is_admin")
    if not is_admin:
        # Validar que la factura es del cliente
        conn = get_db()
        f = conn.execute(
            "SELECT cliente_id FROM facturas WHERE numero = ?", (nro,)
        ).fetchone()
        conn.close()
        if not f or f["cliente_id"] != session.get("cliente_id"):
            abort(403)
    return _servir_archivo_factura(nro)


# V2.14 — Servir comprobante de pago (cliente o admin)
@app.route("/comprobantes/<int:pago_id>")
@login_required
def cliente_comprobante(pago_id):
    """Sirve el comprobante de pago. Cliente solo los suyos; admin todos."""
    is_admin = session.get("is_admin")
    if is_admin:
        return _servir_comprobante(pago_id)
    return _servir_comprobante(pago_id, cliente_id_check=session.get("cliente_id"))


# V2.14 — Admin: forzar cambio de estado a 'pagado' cuando valida el comprobante
@app.route("/admin/pagos/<int:pago_id>/confirmar", methods=["POST"])
@admin_required
def admin_pago_confirmar(pago_id):
    """Confirma el pago: cambia el estado del pedido a 'pagado' (equivalente a
    'cobrado'), marca la factura como pagada, marca el pago como aprobado.
    Reusado por la vista /admin/pagos-pendientes."""
    conn = get_db()
    pago = conn.execute(
        "SELECT id, cliente_id, factura_id, monto, fecha, metodo, referencia, estado FROM pagos WHERE id = ?",
        (pago_id,),
    ).fetchone()
    if not pago:
        conn.close(); abort(404)
    if pago["estado"] == "aprobado":
        conn.close()
        flash(f"Pago #{pago_id} ya estaba aprobado.", "info")
        return redirect(url_for("admin_pagos_pendientes"))
    # Buscar pedido del cliente que matchee por referencia (que guardamos como nro_factura)
    # Si la referencia es WEB-YYYYMMDD-NNN, ese es el nro del pedido.
    ped = None
    if pago["referencia"]:
        ped = conn.execute(
            "SELECT nro FROM pedidos WHERE nro = ? AND cliente_id = ?",
            (pago["referencia"], pago["cliente_id"]),
        ).fetchone()
    if not ped:
        # Fallback: buscar el pedido aprobado mas reciente del cliente
        ped = conn.execute(
            "SELECT nro FROM pedidos WHERE cliente_id = ? AND estado = 'aprobado' ORDER BY fecha_hora DESC LIMIT 1",
            (pago["cliente_id"],),
        ).fetchone()
    if ped:
        conn.execute("UPDATE pedidos SET estado = 'pagado' WHERE nro = ?", (ped["nro"],))
    if pago["factura_id"]:
        conn.execute(
            "UPDATE facturas SET saldo_pendiente = 0, estado = 'pagada' WHERE id = ?",
            (pago["factura_id"],),
        )
    # Marcar el pago como aprobado
    conn.execute(
        "UPDATE pagos SET estado = 'aprobado' WHERE id = ?",
        (pago_id,),
    )
    conn.commit()
    conn.close()
    flash(f"Pago #{pago_id} aprobado.", "ok")
    return redirect(url_for("admin_pagos_pendientes"))


@app.route("/admin/pagos/<int:pago_id>/rechazar", methods=["POST"])
@admin_required
def admin_pago_rechazar(pago_id):
    """Rechaza el pago: borra la fila de pagos y (si existe) el archivo del
    comprobante. El pedido queda en 'aprobado' (sigue facturado) y el cliente
    puede cargar otro comprobante."""
    conn = get_db()
    pago = conn.execute(
        "SELECT id, comprobante_path FROM pagos WHERE id = ?",
        (pago_id,),
    ).fetchone()
    if not pago:
        conn.close(); abort(404)
    # Borrar archivo del comprobante si existe
    if pago["comprobante_path"]:
        try:
            full = os.path.join(UPLOAD_DIR, pago["comprobante_path"])
            if os.path.isfile(full):
                os.remove(full)
        except Exception:
            pass  # no rompemos por un file missing
    conn.execute("DELETE FROM pagos WHERE id = ?", (pago_id,))
    conn.commit()
    conn.close()
    flash(f"Pago #{pago_id} rechazado y borrado.", "ok")
    return redirect(url_for("admin_pagos_pendientes"))


@app.route("/admin/pagos", endpoint="admin_pagos_pendientes")
@admin_required
def admin_pagos_pendientes():
    """Vista de Pagos con 2 tabs:
    - pendientes: pagos con comprobante y estado != 'aprobado' (NULL o rechazado)
    - confirmados: pagos con estado = 'aprobado' (incluye admin-upload que
      van directo a aprobado).
    Query param: ?tab=pendientes|confirmados (default: pendientes)."""
    tab = (request.args.get("tab") or "pendientes").strip().lower()
    if tab not in ("pendientes", "confirmados"):
        tab = "pendientes"
    conn = get_db()
    # Query base con join a cliente y pedido
    base = """
        SELECT
            p.id, p.cliente_id, p.factura_id, p.monto, p.fecha, p.metodo,
            p.referencia, p.comprobante_path, p.estado,
            c.usuario, c.nombre AS cliente_nombre,
            ped.nro AS pedido_nro, ped.estado AS pedido_estado, ped.total AS pedido_total
        FROM pagos p
        JOIN clientes c ON c.id = p.cliente_id
        LEFT JOIN pedidos ped ON ped.nro = p.referencia
    """
    if tab == "confirmados":
        rows = conn.execute(base + " WHERE p.estado = 'aprobado' ORDER BY p.fecha DESC").fetchall()
    else:
        # pendientes: cualquier pago NO aprobado, con o sin comprobante
        # (pagos en efectivo/cheque cargados por admin o sin comprobante
        # tambien aparecen aca para que el admin los apruebe manualmente)
        rows = conn.execute(base + """
            WHERE (p.estado IS NULL OR p.estado != 'aprobado')
            ORDER BY p.fecha ASC
        """).fetchall()
    # Counts para badges
    n_pendientes = conn.execute("""
        SELECT COUNT(*) FROM pagos
        WHERE (estado IS NULL OR estado != 'aprobado')
    """).fetchone()[0]
    n_confirmados = conn.execute(
        "SELECT COUNT(*) FROM pagos WHERE estado = 'aprobado'"
    ).fetchone()[0]
    conn.close()
    pagos_out = [dict(r) for r in rows]
    return render_template(
        "admin_pagos.html",
        pagos=pagos_out,
        tab=tab,
        n_pendientes=n_pendientes,
        n_confirmados=n_confirmados,
        fmt=fmt_money,
    )


@app.route("/admin/pagos-pendientes/cargar", methods=["GET", "POST"])
@admin_required
def admin_pagos_pendientes_cargar():
    """Admin carga un pago en nombre del cliente (caso WhatsApp/mail).
    Form: cliente (select), pedido (select filtrado por cliente, no cobrados),
    monto (default = total del pedido), forma de pago (dropdown), fecha
    (default hoy), comprobante (file PDF/JPG/PNG).
    Submit: crea fila en pagos con estado='aprobado' y marca el pedido
    como 'pagado' (equivalente a 'cobrado' segun el sistema)."""
    conn = get_db()
    # Lista de clientes (no-admin)
    clientes = conn.execute(
        "SELECT id, usuario, nombre FROM clientes WHERE is_admin = 0 ORDER BY nombre, usuario"
    ).fetchall()
    # Si hay cliente_id en el form/args, cargar pedidos no cobrados de ese cliente
    cid_sel = request.args.get("cliente_id", type=int) or request.form.get("cliente_id", type=int)
    pedidos = []
    cliente_sel = None
    if cid_sel:
        cliente_sel = conn.execute(
            "SELECT id, usuario, nombre FROM clientes WHERE id = ?", (cid_sel,)
        ).fetchone()
        if cliente_sel:
            # Pedidos no cobrados (estado != 'pagado'/'entregado')
            pedidos = conn.execute("""
                SELECT nro, total, estado, fecha_hora FROM pedidos
                WHERE cliente_id = ? AND estado NOT IN ('pagado', 'entregado')
                ORDER BY fecha_hora DESC
            """, (cid_sel,)).fetchall()
    if request.method == "POST":
        cliente_id = request.form.get("cliente_id", type=int)
        pedido_nro = (request.form.get("pedido_nro") or "").strip()
        monto = request.form.get("monto", "").strip()
        metodo = (request.form.get("metodo") or "").strip().lower()
        fecha = (request.form.get("fecha") or "").strip()
        if not (cliente_id and pedido_nro and monto and metodo and fecha):
            conn.close()
            flash("Faltan campos obligatorios (cliente, pedido, monto, forma de pago, fecha).", "error")
            return redirect(url_for("admin_pagos_pendientes_cargar", cliente_id=cliente_id))
        try:
            monto_f = float(monto)
            if monto_f <= 0:
                raise ValueError("monto <= 0")
        except ValueError:
            conn.close()
            flash("Monto invalido.", "error")
            return redirect(url_for("admin_pagos_pendientes_cargar", cliente_id=cliente_id))
        METODOS_VALIDOS = ("efectivo", "transferencia", "cheque")
        if metodo not in METODOS_VALIDOS:
            conn.close()
            flash(f"Forma de pago '{metodo}' no soportada.", "error")
            return redirect(url_for("admin_pagos_pendientes_cargar", cliente_id=cliente_id))
        # Validar pedido pertenece al cliente
        ped = conn.execute(
            "SELECT nro, total, estado FROM pedidos WHERE nro = ? AND cliente_id = ?",
            (pedido_nro, cliente_id),
        ).fetchone()
        if not ped:
            conn.close()
            flash("Pedido no encontrado o no pertenece al cliente.", "error")
            return redirect(url_for("admin_pagos_pendientes_cargar", cliente_id=cliente_id))
        # Validar comprobante (obligatorio)
        if 'comprobante' not in request.files:
            conn.close()
            flash("Falta el comprobante (PDF/JPG/PNG).", "error")
            return redirect(url_for("admin_pagos_pendientes_cargar", cliente_id=cliente_id))
        content, ext, err = _validar_archivo(
            request.files['comprobante'],
            [PDF_MAGIC, JPEG_MAGIC, PNG_MAGIC],
            MAX_COMP_SIZE,
        )
        if err or not content:
            conn.close()
            flash(f"Comprobante invalido: {err or 'archivo vacio'}.", "error")
            return redirect(url_for("admin_pagos_pendientes_cargar", cliente_id=cliente_id))
        # Buscar factura del cliente (puede o no existir)
        fac = conn.execute(
            "SELECT id, numero FROM facturas WHERE cliente_id = ? AND ABS(total - ?) < 0.01 ORDER BY id DESC LIMIT 1",
            (cliente_id, monto_f),
        ).fetchone()
        factura_id = fac["id"] if fac else None
        nro_factura = fac["numero"] if fac else pedido_nro
        # Crear pago con estado='aprobado' directamente
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pagos (factura_id, cliente_id, fecha, monto, metodo, referencia, estado)
            VALUES (?, ?, ?, ?, ?, ?, 'aprobado')
        """, (
            factura_id, cliente_id, fecha, monto_f, metodo, nro_factura,
        ))
        new_pago_id = cur.lastrowid
        comp_path = _guardar_comprobante(new_pago_id, content, ext)
        cur.execute("UPDATE pagos SET comprobante_path = ? WHERE id = ?", (comp_path, new_pago_id))
        # Marcar el pedido como pagado/cobrado
        cur.execute("UPDATE pedidos SET estado = 'pagado' WHERE nro = ?", (pedido_nro,))
        if factura_id:
            cur.execute("UPDATE facturas SET saldo_pendiente = 0, estado = 'pagada' WHERE id = ?", (factura_id,))
        conn.commit()
        conn.close()
        flash(f"Pago #{new_pago_id} registrado en nombre del cliente para pedido {pedido_nro}.", "ok")
        return redirect(url_for("admin_pagos_pendientes"))
    conn.close()
    # GET: renderizar form
    return render_template(
        "admin_pagos_pendientes_cargar.html",
        clientes=clientes,
        cliente_sel=cliente_sel,
        cid_sel=cid_sel,
        pedidos=pedidos,
        fmt=fmt_money,
        hoy=datetime.now().strftime("%Y-%m-%d"),
    )


# -----------------------------------------------------------------------------
# Admin /admin/facturas — Vista de solo lectura con filtros.
# Mockup 2 validado por Fer. Lista todas las facturas (numero, fecha,
# cliente, pedido origen, monto, estado) con filtros: cliente, desde/hasta,
# estado, monto desde/hasta. Acciones por fila: PDF (azul) + Detalle (outline).
# -----------------------------------------------------------------------------
@app.route("/admin/facturas", endpoint="admin_facturas")
@admin_required
def admin_facturas():
    """Lista de facturas con filtros. Solo lectura."""
    # Filtros desde query string
    cid_sel = request.args.get("cliente_id", type=int)
    fecha_desde = (request.args.get("fecha_desde") or "").strip()
    fecha_hasta = (request.args.get("fecha_hasta") or "").strip()
    estado_sel = (request.args.get("estado") or "").strip().lower()
    monto_desde = (request.args.get("monto_desde") or "").strip()
    monto_hasta = (request.args.get("monto_hasta") or "").strip()

    conn = get_db()
    # Clientes para el select de filtro
    clientes = conn.execute(
        "SELECT id, nombre, usuario FROM clientes WHERE is_admin = 0 ORDER BY nombre, usuario"
    ).fetchall()
    # Query base
    sql = """
        SELECT
            f.id, f.numero, f.fecha, f.total, f.saldo_pendiente, f.estado, f.archivo_path,
            f.cliente_id,
            c.nombre AS cliente_nombre, c.usuario AS cliente_usuario,
            ped.nro AS pedido_nro
        FROM facturas f
        JOIN clientes c ON c.id = f.cliente_id
        LEFT JOIN pedidos ped ON ped.cliente_id = f.cliente_id
                                AND ABS(ped.total - f.total) < 0.01
                                AND ped.estado IN ('aprobado', 'pagado', 'entregado')
        WHERE 1=1
    """
    params = []
    if cid_sel:
        sql += " AND f.cliente_id = ?"
        params.append(cid_sel)
    if fecha_desde:
        sql += " AND f.fecha >= ?"
        params.append(fecha_desde)
    if fecha_hasta:
        sql += " AND f.fecha <= ?"
        params.append(fecha_hasta)
    if estado_sel in ("pendiente", "pagada", "anulada"):
        sql += " AND f.estado = ?"
        params.append(estado_sel)
    # Validar monto desde/hasta
    try:
        if monto_desde:
            md = float(monto_desde)
            if md < 0: raise ValueError
            sql += " AND f.total >= ?"
            params.append(md)
    except ValueError:
        monto_desde = ""
    try:
        if monto_hasta:
            mh = float(monto_hasta)
            if mh < 0: raise ValueError
            sql += " AND f.total <= ?"
            params.append(mh)
    except ValueError:
        monto_hasta = ""
    sql += " ORDER BY f.fecha DESC, f.id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    facturas_out = [dict(r) for r in rows]
    return render_template(
        "admin_facturas.html",
        facturas=facturas_out,
        clientes=clientes,
        cid_sel=cid_sel,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estado_sel=estado_sel,
        monto_desde=monto_desde,
        monto_hasta=monto_hasta,
        fmt=fmt_money,
    )


# -----------------------------------------------------------------------------
# Diagnostico temporal: verifica si reportlab esta disponible.
# -----------------------------------------------------------------------------
@app.route("/api/_diag")
def api_diag():
    out = {"ok": True}
    try:
        import reportlab
        out["reportlab"] = reportlab.Version
    except ImportError as e:
        out["reportlab"] = f"NO: {e}"
    return jsonify(out)


# V2.14 — endpoint temporal de migracion (proteger en el futuro o quitar)
@app.route("/admin/_migrate_v2_14", methods=["GET", "POST"])
@admin_required
def admin_migrate_v2_14():
    """Ejecuta las migraciones del V2.14. Solo admin. Idempotente."""
    from flask import current_app
    conn = get_db()
    out = []
    # Schema
    if not _column_exists(conn, "facturas", "archivo_path"):
        conn.execute("ALTER TABLE facturas ADD COLUMN archivo_path TEXT")
        out.append("Added facturas.archivo_path")
    else:
        out.append("facturas.archivo_path ya existe")
    if not _column_exists(conn, "pagos", "comprobante_path"):
        conn.execute("ALTER TABLE pagos ADD COLUMN comprobante_path TEXT")
        out.append("Added pagos.comprobante_path")
    else:
        out.append("pagos.comprobante_path ya existe")
    if not _column_exists(conn, "pedidos", "estado"):
        conn.execute("ALTER TABLE pedidos ADD COLUMN estado TEXT DEFAULT 'pendiente'")
        out.append("Added pedidos.estado (default pendiente)")
    else:
        out.append("pedidos.estado ya existe")
    conn.commit()
    # Migrar PDFs de pedidos a filesystem legacy
    import re as _re
    LEGACY_DIR = os.path.join(BASE_DIR, "uploads", "facturas", "legacy", "2026-pre")
    os.makedirs(LEGACY_DIR, exist_ok=True)
    mig = 0
    skp = 0
    for row in conn.execute("SELECT nro, pdf_bytes FROM pedidos WHERE pdf_bytes IS NOT NULL").fetchall():
        nro = row["nro"]
        pdf = row["pdf_bytes"]
        if not pdf: continue
        safe = _re.sub(r"[^A-Za-z0-9_\-]", "_", nro)
        target = os.path.join(LEGACY_DIR, f"{safe}.pdf")
        if os.path.exists(target):
            skp += 1
            continue
        with open(target, "wb") as f:
            f.write(pdf)
        mig += 1
    conn.close()
    out.append(f"Migrados PDFs: {mig}, skipped: {skp}")
    return jsonify({"ok": True, "log": out})


# ENDPOINT TEMPORAL - SACAR EN PROXIMO CLEANUP
# Migracion peso_kg: ALTER TABLE + UPDATE masivo desde Excel subido a prod.
# Idempotente: si la columna existe, no la agrega. Si el producto ya tiene
# peso_kg, lo sobreescribe con el valor del Excel (que es la fuente de verdad).
# Usa stdlib (zipfile + xml.etree) en vez de openpyxl para no requerir pip install.
def _read_xlsx_simple(xlsx_path, target_cols):
    """Lee un .xlsx con stdlib. Devuelve lista de tuplas con los valores de las
    columnas target_cols (indices 0-based, igual que openpyxl).
    target_cols: lista de indices, ej [1, 3] para COD_ART y KILOS."""
    import zipfile as _zip
    import xml.etree.ElementTree as _et
    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    out = []
    with _zip.ZipFile(xlsx_path) as z:
        # Shared strings (para resolver valores que son strings compartidos)
        shared = []
        try:
            with z.open("xl/sharedStrings.xml") as f:
                root = _et.fromstring(f.read())
            for si in root.findall(f"{NS}si"):
                # Un si puede tener t (texto plano) o r (rich text runs)
                txt = "".join(t.text or "" for t in si.iter(f"{NS}t"))
                shared.append(txt)
        except KeyError:
            pass
        # Sheet 1
        with z.open("xl/worksheets/sheet1.xml") as f:
            root = _et.fromstring(f.read())
        sheet_data = root.find(f"{NS}sheetData")
        rows_xml = sheet_data.findall(f"{NS}row")
        # Saltamos el header (row 1)
        for row in rows_xml[1:]:
            cells = {}
            for c in row.findall(f"{NS}c"):
                ref = c.get("r")  # ej A1, B1
                col_letters = "".join(ch for ch in ref if ch.isalpha())
                # convertir letras a indice 0-based
                col_idx = 0
                for ch in col_letters:
                    col_idx = col_idx * 26 + (ord(ch.upper()) - ord("A") + 1)
                col_idx -= 1
                t_attr = c.get("t")
                v_elem = c.find(f"{NS}v")
                if v_elem is None:
                    cells[col_idx] = None
                    continue
                v = v_elem.text
                if t_attr == "s":
                    # shared string
                    try:
                        cells[col_idx] = shared[int(v)]
                    except (ValueError, IndexError):
                        cells[col_idx] = None
                elif t_attr == "b":
                    cells[col_idx] = bool(int(v))
                else:
                    # number or inline string
                    try:
                        cells[col_idx] = float(v)
                    except (TypeError, ValueError):
                        cells[col_idx] = v
            row_vals = tuple(cells.get(i) for i in target_cols)
            out.append(row_vals)
    return out


@app.route("/admin/_migrate_peso_kg", methods=["GET", "POST"])
@admin_required
def admin_migrate_peso_kg():
    """Carga la columna peso_kg en productos desde el Excel de Fer."""
    import os as _os
    XLSX_PATH = _os.path.join(BASE_DIR, "uploads", "lista_pesos_2026-06-14.xlsx")
    if not _os.path.exists(XLSX_PATH):
        return jsonify({"ok": False, "error": f"Excel no encontrado en {XLSX_PATH}"}), 404

    conn = get_db()
    out = []

    # 1) ALTER TABLE
    if not _column_exists(conn, "productos", "peso_kg"):
        conn.execute("ALTER TABLE productos ADD COLUMN peso_kg REAL")
        out.append("Added productos.peso_kg")
    else:
        out.append("productos.peso_kg ya existe")

    # 2) Leer Excel (cols 1=COD_ART, 3=KILOS, indices 0-based)
    try:
        rows = _read_xlsx_simple(XLSX_PATH, [1, 3])
    except Exception as e:
        conn.close()
        return jsonify({"ok": False, "error": f"Error leyendo Excel: {e}"}), 500

    excel_map = {}
    for cod, kilos in rows:
        if cod and kilos is not None:
            try:
                excel_map[str(cod).strip()] = float(kilos)
            except (TypeError, ValueError):
                pass
    out.append(f"Excel leido: {len(excel_map)} productos con KILOS")

    # 3) UPDATE masivo
    updated = 0
    skipped_no_match = 0
    cur = conn.cursor()
    for cod, kilos in excel_map.items():
        cur.execute("UPDATE productos SET peso_kg = ? WHERE cod = ?", (kilos, cod))
        if cur.rowcount > 0:
            updated += 1
        else:
            skipped_no_match += 1
    conn.commit()

    # 4) Conteos
    total = conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
    with_peso = conn.execute("SELECT COUNT(*) FROM productos WHERE peso_kg IS NOT NULL").fetchone()[0]
    sin_peso = total - with_peso
    adn4 = conn.execute("SELECT cod, peso_kg FROM productos WHERE cod = 'ADN4'").fetchone()
    conn.close()

    out.append(f"UPDATE ejecutados: {updated} (modificados), {skipped_no_match} (cod del Excel no estaba en DB)")
    out.append(f"Total productos: {total}, con peso_kg: {with_peso}, sin peso_kg: {sin_peso}")
    out.append(f"Ejemplo ADN4: {dict(adn4) if adn4 else 'No encontrado'}")

    return jsonify({
        "ok": True,
        "log": out,
        "reporte": {
            "columna_existe": True,
            "total_productos": total,
            "actualizados": updated,
            "con_peso": with_peso,
            "sin_peso": sin_peso,
            "adn4": dict(adn4) if adn4 else None,
        },
    })


# ENDPOINT TEMPORAL - SACAR EN PROXIMO CLEANUP
# Migracion precios: UPDATE masivo desde Excel subido a prod.
# Idempotente: sobreescribe precio_lista con PR_FINAL_UNIDAD (col 8 / indice 7).
# El Excel es la fuente de verdad (Fer, 2026-06-15).
@app.route("/admin/_migrate_precios", methods=["GET", "POST"])
@admin_required
def admin_migrate_precios():
    """Carga precio_lista en productos desde PR_FINAL_UNIDAD del Excel de Fer."""
    import os as _os
    XLSX_PATH = _os.path.join(BASE_DIR, "uploads", "lista_pesos_2026-06-14.xlsx")
    if not _os.path.exists(XLSX_PATH):
        return jsonify({"ok": False, "error": f"Excel no encontrado en {XLSX_PATH}"}), 404

    conn = get_db()
    out = []

    # 1) Leer Excel (cols 1=COD_ART, 7=PR_FINAL_UNIDAD, indices 0-based)
    try:
        rows = _read_xlsx_simple(XLSX_PATH, [1, 7])
    except Exception as e:
        conn.close()
        return jsonify({"ok": False, "error": f"Error leyendo Excel: {e}"}), 500

    excel_map = {}
    for cod, precio in rows:
        if cod and precio is not None:
            try:
                excel_map[str(cod).strip()] = float(precio)
            except (TypeError, ValueError):
                pass
    out.append(f"Excel leido: {len(excel_map)} productos con PR_FINAL_UNIDAD")

    # 2) UPDATE masivo
    updated = 0
    skipped_no_match = 0
    cur = conn.cursor()
    for cod, precio in excel_map.items():
        cur.execute("UPDATE productos SET precio_lista = ? WHERE cod = ?", (precio, cod))
        if cur.rowcount > 0:
            updated += 1
        else:
            skipped_no_match += 1
    conn.commit()

    # 3) Verificacion: comparar 3 productos contra el Excel
    checks = {}
    for cod_check in ("ADN4", "ADN6", "HL10"):
        db_row = conn.execute("SELECT cod, precio_lista FROM productos WHERE cod = ?", (cod_check,)).fetchone()
        excel_val = excel_map.get(cod_check)
        if db_row and excel_val:
            cociente = db_row["precio_lista"] / excel_val if excel_val else None
            checks[cod_check] = {
                "db": db_row["precio_lista"],
                "excel": excel_val,
                "cociente": cociente,
            }
    conn.close()

    out.append(f"UPDATE ejecutados: {updated} (modificados), {skipped_no_match} (cod del Excel no estaba en DB)")
    out.append(f"Verificacion: {checks}")

    return jsonify({
        "ok": True,
        "log": out,
        "reporte": {
            "actualizados": updated,
            "skipped_no_match": skipped_no_match,
            "checks": checks,
        },
    })


# -----------------------------------------------------------------------------
# Panel de cuenta del cliente (mi-cuenta, facturas, pagos)
# -----------------------------------------------------------------------------

def fmt_fecha(s):
    """Convierte 'YYYY-MM-DD' a 'DD/MM/YYYY'."""
    if not s or len(s) < 10:
        return s or ""
    return f"{s[8:10]}/{s[5:7]}/{s[0:4]}"


def get_cliente_or_404(cid):
    """Devuelve el cliente; aborta 404 si no existe o está inactivo."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM clientes WHERE id = ? AND activo = 1", (cid,)
    ).fetchone()
    conn.close()
    if not row:
        abort(404)
    return row


@app.route("/mi-cuenta")
@login_required
def mi_cuenta():
    cliente = get_cliente_or_404(session["cliente_id"])
    conn = get_db()
    # Pedidos del cliente (todos)
    pedidos = conn.execute("""
        SELECT nro, fecha_hora, total, estado, items_json, forma_pago, lugar_entrega
        FROM pedidos WHERE cliente_id = ?
        ORDER BY fecha_hora DESC
    """, (cliente["id"],)).fetchall()
    pedidos_out = []
    for p in pedidos:
        d = dict(p)
        try:
            d["items"] = json.loads(d.get("items_json") or "[]")
        except Exception:
            d["items"] = []
        pedidos_out.append(d)
    # Facturas del cliente
    facturas = conn.execute("""
        SELECT id, numero, fecha, total, saldo_pendiente, estado
        FROM facturas WHERE cliente_id = ?
        ORDER BY fecha DESC, id DESC
    """, (cliente["id"],)).fetchall()
    facturas_out = [dict(f) for f in facturas]
    # Pagos del cliente
    pagos = conn.execute("""
        SELECT id, factura_id, fecha, monto, metodo, referencia
        FROM pagos WHERE cliente_id = ?
        ORDER BY fecha DESC, id DESC
    """, (cliente["id"],)).fetchall()
    pagos_out = [dict(p) for p in pagos]
    # Stats comerciales (3-4 cards)
    total_facturado = sum(f.get("total") or 0 for f in facturas_out)
    total_pagado = sum(p.get("monto") or 0 for p in pagos_out)
    # pendiente_pago = suma de los saldos_pendiente de cada factura (no total -
    # total_pagado, porque eso puede dar negativo si hay pagos parciales o pagos
    # sin factura linkeada). Coincide con el conteo de pagos_pendientes.
    pendiente_pago = sum((f.get("saldo_pendiente") or 0) for f in facturas_out)
    n_pedidos = len(pedidos_out)
    # Pago pendiente: hay al menos una factura con saldo_pendiente > 0
    pagos_pendientes = sum(1 for f in facturas_out if (f.get("saldo_pendiente") or 0) > 0)
    conn.close()
    return render_template(
        "mi_cuenta.html",
        cliente=cliente,
        pedidos=pedidos_out,
        facturas=facturas_out,
        pagos=pagos_out,
        n_pedidos=n_pedidos,
        total_facturado=total_facturado,
        total_pagado=total_pagado,
        pendiente_pago=pendiente_pago,
        pagos_pendientes=pagos_pendientes,
        tab=request.args.get("tab", "pedidos"),
        fmt=fmt_money,
    )


@app.route("/facturas")
@login_required
def facturas_lista():
    cid = session["cliente_id"]
    conn = get_db()
    rows = conn.execute("""
        SELECT id, numero, fecha, total, saldo_pendiente, estado
        FROM facturas
        WHERE cliente_id = ?
        ORDER BY fecha DESC, id DESC
    """, (cid,)).fetchall()
    conn.close()
    return render_template(
        "facturas.html",
        items=[dict(r) for r in rows],
        fmt=fmt_money,
        fmt_fecha=fmt_fecha,
    )


@app.route("/factura/<int:fid>")
@login_required
def factura_detalle(fid):
    cid = session["cliente_id"]
    conn = get_db()
    fac = conn.execute("""
        SELECT * FROM facturas WHERE id = ? AND cliente_id = ?
    """, (fid, cid)).fetchone()
    if not fac:
        conn.close()
        abort(404)
    pagos = conn.execute("""
        SELECT fecha, monto, metodo, referencia
        FROM pagos WHERE factura_id = ?
        ORDER BY fecha DESC, id DESC
    """, (fid,)).fetchall()
    conn.close()
    return render_template(
        "factura_detalle.html",
        fac=fac,
        pagos=[dict(p) for p in pagos],
        fmt=fmt_money,
        fmt_fecha=fmt_fecha,
    )


@app.route("/pagos")
@login_required
def pagos_lista():
    cid = session["cliente_id"]
    conn = get_db()
    rows = conn.execute("""
        SELECT p.id, p.fecha, p.monto, p.metodo, p.referencia,
               f.id AS factura_id, f.numero AS factura_numero
        FROM pagos p
        LEFT JOIN facturas f ON f.id = p.factura_id
        WHERE p.cliente_id = ?
        ORDER BY p.fecha DESC, p.id DESC
    """, (cid,)).fetchall()
    conn.close()
    total_pagado = sum((p["monto"] or 0) for p in rows)
    return render_template(
        "pagos.html",
        items=[dict(r) for r in rows],
        total_pagado=total_pagado,
        fmt=fmt_money,
        fmt_fecha=fmt_fecha,
    )


@app.route("/admin")
@admin_required
def admin():
    """Dashboard admin v2 (Bloque G): 5 stats en vivo + 3 atajos + 3 primeros
    pedidos pendientes + actividad reciente (ultimos 7-10 eventos)."""
    conn = get_db()
    # 1) Clientes activos
    n_activos = conn.execute(
        "SELECT COUNT(*) FROM clientes WHERE is_admin = 0 AND activo = 1"
    ).fetchone()[0]
    # 2) Pedidos pendientes
    n_pendientes_row = conn.execute(
        "SELECT COUNT(*) FROM pedidos WHERE estado = 'pendiente'"
    ).fetchone()
    n_pendientes = n_pendientes_row[0] if n_pendientes_row else 0
    # Pedidos pendientes con +24h
    n_pendientes_24h = conn.execute("""
        SELECT COUNT(*) FROM pedidos
        WHERE estado = 'pendiente'
          AND (julianday('now') - julianday(fecha_hora)) > 1.0
    """).fetchone()[0]
    # 3) Clientes con device X/Y
    n_device = conn.execute("""
        SELECT COUNT(*) FROM clientes
        WHERE is_admin = 0 AND activo = 1 AND device_token IS NOT NULL
    """).fetchone()[0]
    # 4) Datos incompletos (clientes no-admin, activos, sin razon_social o sin cuit o sin direccion)
    n_datos_inc = conn.execute("""
        SELECT COUNT(*) FROM clientes
        WHERE is_admin = 0 AND activo = 1
          AND (razon_social IS NULL OR razon_social = ''
               OR cuit IS NULL OR cuit = ''
               OR direccion IS NULL OR direccion = ''
               OR telefono IS NULL OR telefono = ''
               OR email IS NULL OR email = ''
               OR localidad IS NULL OR localidad = ''
               OR nombre IS NULL OR nombre = '')
    """).fetchone()[0]
    # 5) Productos
    n_productos_row = conn.execute("SELECT COUNT(*) FROM productos").fetchone()
    n_productos = n_productos_row[0] if n_productos_row else 0

    # === V2.5 — 3 stats de ventas ===
    # Rango mes actual y mes anterior (formato YYYY-MM)
    from datetime import datetime
    ahora_dt = datetime.now()
    mes_actual = ahora_dt.strftime("%Y-%m")
    # mes anterior: restar un mes
    if ahora_dt.month == 1:
        mes_anterior = f"{ahora_dt.year - 1}-12"
    else:
        mes_anterior = f"{ahora_dt.year}-{ahora_dt.month - 1:02d}"
    # 6) Facturado este mes: suma total de pedidos facturados/cobrados/entregados
    #    del mes actual (segun la fecha_hora del pedido)
    fact_mes_actual = conn.execute("""
        SELECT COALESCE(SUM(total), 0) FROM pedidos
        WHERE estado IN ('aprobado', 'pagado', 'entregado')
          AND substr(fecha_hora, 1, 7) = ?
    """, (mes_actual,)).fetchone()[0]
    fact_mes_anterior = conn.execute("""
        SELECT COALESCE(SUM(total), 0) FROM pedidos
        WHERE estado IN ('aprobado', 'pagado', 'entregado')
          AND substr(fecha_hora, 1, 7) = ?
    """, (mes_anterior,)).fetchone()[0]
    if fact_mes_anterior > 0:
        fact_var = round((fact_mes_actual - fact_mes_anterior) / fact_mes_anterior * 100, 1)
    else:
        fact_var = 0.0  # sin mes anterior comparable
    # 7) Cobrado este mes: suma monto de tabla pagos del mes actual
    cobr_mes_actual = conn.execute("""
        SELECT COALESCE(SUM(monto), 0) FROM pagos
        WHERE substr(fecha, 1, 7) = ?
    """, (mes_actual,)).fetchone()[0]
    cobr_mes_anterior = conn.execute("""
        SELECT COALESCE(SUM(monto), 0) FROM pagos
        WHERE substr(fecha, 1, 7) = ?
    """, (mes_anterior,)).fetchone()[0]
    if cobr_mes_anterior > 0:
        cobr_var = round((cobr_mes_actual - cobr_mes_anterior) / cobr_mes_anterior * 100, 1)
    else:
        cobr_var = 0.0
    # 8) Pendiente de cobro: total de pedidos facturados (estado='aprobado') menos
    #    lo ya cobrado (suma de pagos contra la factura del pedido). Si un pedido
    #    esta aprobado pero su factura ya fue pagada (caso admin_pedido_cobrar),
    #    el saldo resultante es 0 y queda excluido por el WHERE final.
    #    Si un pedido esta en estado 'pagado' (ya cobrado), NO cuenta como
    #    pendiente (asi no duplicamos con Cobrado del mes).
    pend_cobro_row = conn.execute("""
        SELECT
            COUNT(*) AS n,
            COALESCE(SUM(saldo), 0) AS total_pendiente
        FROM (
            SELECT
                p.total - COALESCE((
                    SELECT SUM(pa.monto) FROM pagos pa
                    WHERE pa.factura_id = f.id
                ), 0) AS saldo
            FROM pedidos p
            LEFT JOIN facturas f
                ON f.cliente_id = p.cliente_id
                AND ABS(f.total - p.total) < 0.01
            WHERE p.estado = 'aprobado'
        )
        WHERE saldo > 0.01
    """).fetchone()
    pend_cobro_count = pend_cobro_row[0] if pend_cobro_row else 0
    pend_cobro_total = pend_cobro_row[1] if pend_cobro_row else 0

    # Pagos pendientes de aprobacion (para badge en navbar/atajos)
    n_pagos_pendientes = conn.execute("""
        SELECT COUNT(*) FROM pagos
        WHERE comprobante_path IS NOT NULL
          AND (estado IS NULL OR estado != 'aprobado')
    """).fetchone()[0]

    # 9) Kilos / toneladas vendidas: suma de cantidad * peso_kg de cada item
    #    en pedidos cuyo estado NO sea 'pendiente' ni 'rechazado'.
    #    Edge cases: item con cod que no existe en productos -> skip.
    #    Producto con peso_kg NULL -> skip.
    kilos_total = 0.0
    pedidos_kilos = conn.execute("""
        SELECT items_json FROM pedidos
        WHERE estado NOT IN ('pendiente', 'rechazado')
    """).fetchall()
    for p in pedidos_kilos:
        try:
            items = json.loads(p[0] or "[]")
        except Exception:
            continue
        for it in items:
            cod = (it.get("cod") or "").strip()
            if not cod or cod in ("ENVIO-CAP", "ENVIO-INT"):
                continue
            try:
                cant = float(it.get("cantidad") or 0)
            except (TypeError, ValueError):
                cant = 0.0
            if cant <= 0:
                continue
            row_p = conn.execute(
                "SELECT peso_kg FROM productos WHERE cod = ?", (cod,)
            ).fetchone()
            if not row_p or row_p[0] is None:
                continue
            try:
                peso = float(row_p[0])
            except (TypeError, ValueError):
                continue
            kilos_total += cant * peso
    toneladas_total = kilos_total / 1000.0

    # Pedidos pendientes para mostrar (3 primeros)
    pedidos_top = conn.execute("""
        SELECT nro, fecha_hora, cliente_nombre, items_json, total, estado
        FROM pedidos
        WHERE estado = 'pendiente'
        ORDER BY fecha_hora DESC
        LIMIT 3
    """).fetchall()
    pedidos_out = []
    for p in pedidos_top:
        d = dict(p)
        try:
            items = json.loads(d.get("items_json") or "[]")
        except Exception:
            items = []
        d["items"] = items
        d["items_resumen"] = ", ".join(
            (it.get("desc") or it.get("cod") or "?") for it in items[:2]
        ) + ("..." if len(items) > 2 else "")
        # Edad del pedido
        try:
            fh = d["fecha_hora"]
            # Calcular horas
            from datetime import datetime
            dt = datetime.strptime(fh.split(".")[0], "%Y-%m-%d %H:%M:%S")
            ahora = datetime.now()
            horas = (ahora - dt).total_seconds() / 3600
            d["edad_horas"] = int(horas)
            d["edad_texto"] = (
                f"Hace {int(horas)}h" if horas < 24
                else f"Hace {int(horas/24)}d {int(horas%24)}h"
            )
        except Exception:
            d["edad_horas"] = 0
            d["edad_texto"] = "—"
        pedidos_out.append(d)

    # Actividad reciente: ultimos 7-10 eventos
    # Sintetizamos desde pedidos, clientes y movimientos manuales
    actividad = []
    # Ultimos pedidos confirmados/aprobados/rechazados
    for p in conn.execute("""
        SELECT nro, fecha_hora, cliente_nombre, estado, total
        FROM pedidos
        ORDER BY fecha_hora DESC LIMIT 6
    """).fetchall():
        d = dict(p)
        if d["estado"] == "aprobado":
            tipo = "aprobado"
            texto = f"<strong>{d['cliente_nombre']}</strong> pedido #{d['nro']} aprobado"
        elif d["estado"] == "rechazado":
            tipo = "rechazado"
            texto = f"<strong>{d['cliente_nombre']}</strong> pedido #{d['nro']} rechazado"
        else:
            tipo = "pedido"
            texto = f"<strong>{d['cliente_nombre']}</strong> confirmo pedido #{d['nro']}"
        actividad.append({
            "ts": d["fecha_hora"],
            "tipo": tipo,
            "texto": texto,
        })
    # Ultimos clientes creados
    for c in conn.execute("""
        SELECT usuario, nombre, created_at
        FROM clientes
        WHERE is_admin = 0
        ORDER BY id DESC LIMIT 3
    """).fetchall():
        d = dict(c)
        # created_at puede ser None; usar updated_at como fallback
        ts = d.get("created_at") or d.get("updated_at") or ""
        actividad.append({
            "ts": ts,
            "tipo": "cliente",
            "texto": f"Cliente <strong>{d.get('nombre') or d['usuario']}</strong> creado",
        })
    # Ultimos devices revocados (no hay tabla de eventos, usamos device_last_login para aproximar)
    # Ordenar actividad por ts desc y tomar 10
    actividad.sort(key=lambda x: x.get("ts") or "", reverse=True)
    actividad = [a for a in actividad if a.get("ts")][:10]

    conn.close()
    return render_template(
        "admin.html",
        n_activos=n_activos,
        n_pendientes=n_pendientes,
        n_pendientes_24h=n_pendientes_24h,
        n_device=n_device,
        n_datos_inc=n_datos_inc,
        n_productos=n_productos,
        fact_mes_actual=fact_mes_actual,
        fact_mes_anterior=fact_mes_anterior,
        fact_var=fact_var,
        cobr_mes_actual=cobr_mes_actual,
        cobr_mes_anterior=cobr_mes_anterior,
        cobr_var=cobr_var,
        pend_cobro_count=pend_cobro_count,
        pend_cobro_total=pend_cobro_total,
        n_pagos_pendientes=n_pagos_pendientes,
        kilos_total=kilos_total,
        toneladas_total=toneladas_total,
        pedidos=pedidos_out,
        actividad=actividad,
        fmt=fmt_money,
    )


# =============================================================================
# Gestion de clientes (FASE 1)
# =============================================================================

TIPOS_CLIENTE = ("responsable_inscripto", "monotributo", "consumidor_final", "exento")
COD_CLIENTE_RE = re.compile(r"^[0-9]{4,10}$")


def _parse_descuento(value):
    """Devuelve float 0-100 o None. Si vacio, None. Si invalido, None silencioso."""
    s = (value or "").strip()
    if not s:
        return None
    try:
        n = float(s)
        if n < 0 or n > 100:
            return None
        return n
    except ValueError:
        return None


def _parse_cliente_form(form):
    """Devuelve (dict, errores) con los campos parseados y validados."""
    out = {}
    errs = []
    out["cod_cliente"] = form.get("cod_cliente", "").strip() or None
    if out["cod_cliente"] and not COD_CLIENTE_RE.match(out["cod_cliente"]):
        errs.append("cod_cliente debe tener entre 4 y 10 dígitos.")
    out["usuario"] = form.get("usuario", "").strip()
    if not out["usuario"]:
        errs.append("usuario es obligatorio.")
    out["nombre"] = form.get("nombre", "").strip() or None
    out["razon_social"] = form.get("razon_social", "").strip() or None
    out["cuit"] = form.get("cuit", "").strip() or None
    out["localidad"] = form.get("localidad", "").strip() or None
    out["direccion"] = form.get("direccion", "").strip() or None
    out["telefono"] = form.get("telefono", "").strip() or None
    out["email"] = form.get("email", "").strip() or None
    tc = form.get("tipo_cliente", "").strip()
    if tc not in TIPOS_CLIENTE:
        errs.append("tipo_cliente invalido.")
    out["tipo_cliente"] = tc
    try:
        out["limite_credito"] = float(form.get("limite_credito") or 0)
    except ValueError:
        out["limite_credito"] = 0
    out["notas"] = form.get("notas", "").strip() or None
    out["is_admin"] = 1 if form.get("is_admin") == "on" else 0
    out["password"] = form.get("password", "").strip()
    return out, errs


@app.route("/admin/buscar")
@admin_required
def admin_buscar():
    """Vista dedicada de busqueda de clientes (Bloque G v2). Caja con
    auto-foco, hint de shortcuts, lista de resultados clickeables."""
    q = (request.args.get("q") or "").strip()
    resultados = []
    if q:
        conn = get_db()
        like = f"%{q}%"
        resultados = conn.execute("""
            SELECT id, nombre, razon_social, cuit, direccion, localidad,
                   telefono, email, usuario, cod_cliente, tipo_cliente,
                   activo, is_admin,
                   device_token, device_label
            FROM clientes
            WHERE is_admin = 0
              AND (nombre LIKE ? OR cod_cliente LIKE ?
                   OR usuario LIKE ? OR cuit LIKE ? OR localidad LIKE ?
                   OR razon_social LIKE ?)
            ORDER BY nombre
        """, (like, like, like, like, like, like)).fetchall()
        conn.close()
    return render_template("admin_buscar.html", q=q, resultados=[dict(r) for r in resultados], fmt=fmt_money)


@app.route("/admin/clientes/<int:cid>/ficha", methods=["GET", "POST"])
@admin_required
def admin_cliente_ficha(cid):
    """Pagina aparte con la ficha completa del cliente + 2 pestanas:
    'Datos del cliente' (campos lectura + notas editables) y 'Pedidos'
    (lista pedidos del cliente con cambio de estado)."""
    conn = get_db()
    cli = conn.execute(
        """SELECT id, cod_cliente, usuario, nombre, razon_social, cuit,
                  email, telefono, direccion, localidad, tipo_cliente,
                  limite_credito, notas, is_admin, activo,
                  descuento_adn, descuento_cemento, descuento_resto,
                  device_token, device_first_login, device_last_login, device_label
             FROM clientes WHERE id = ?""", (cid,)
    ).fetchone()
    if not cli:
        conn.close(); abort(404)
    if not cli:
        conn.close(); abort(404)
    cli_d = dict(cli)
    # Mapear tipo_cliente enum a nombre legible
    tipo_legible = {
        "responsable_inscripto": "Responsable Inscripto",
        "monotributo": "Monotributo",
        "consumidor_final": "Consumidor Final",
        "exento": "Exento",
    }
    cli_d["tipo_cliente_legible"] = tipo_legible.get(
        (cli_d.get("tipo_cliente") or "").lower(),
        cli_d.get("tipo_cliente") or "Sin especificar",
    )
    # Truncar device_token para mostrar
    t = cli_d.get("device_token") or ""
    cli_d["device_token_short"] = (t[:8] + "..." + t[-4:]) if len(t) > 16 else t
    # POST: guardar notas o cambiar estado
    if request.method == "POST":
        accion = (request.form.get("accion") or "").strip()
        if accion == "guardar_notas":
            notas = (request.form.get("notas") or "").strip() or None
            conn.execute(
                "UPDATE clientes SET notas = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (notas, cid)
            )
            conn.commit()
            cli_d["notas"] = notas or ""
            flash("Notas guardadas.", "ok")
        elif accion == "cambiar_estado":
            nro = (request.form.get("nro") or "").strip()
            nuevo = (request.form.get("nuevo_estado") or "").strip().lower()
            if nuevo not in ESTADOS_PEDIDO:
                flash(f"Estado invalido: {nuevo}", "error")
            else:
                row = conn.execute(
                    "SELECT nro, cliente_id FROM pedidos WHERE nro = ?", (nro,)
                ).fetchone()
                if not row or row["cliente_id"] != cid:
                    flash("Pedido no pertenece al cliente.", "error")
                else:
                    conn.execute("UPDATE pedidos SET estado = ? WHERE nro = ?", (nuevo, nro))
                    factura_msg = ""
                    if nuevo == "aprobado":
                        existing = conn.execute(
                            "SELECT id FROM facturas WHERE numero = ?", (nro,)
                        ).fetchone()
                        if not existing:
                            pedido = conn.execute(
                                "SELECT cliente_id, fecha_hora, total FROM pedidos WHERE nro = ?",
                                (nro,)
                            ).fetchone()
                            conn.execute("""
                                INSERT INTO facturas
                                    (cliente_id, numero, fecha, total, saldo_pendiente, estado)
                                VALUES (?, ?, ?, ?, ?, 'pendiente')
                            """, (
                                pedido["cliente_id"], nro,
                                pedido["fecha_hora"].split()[0],
                                pedido["total"], pedido["total"],
                            ))
                            factura_msg = " Factura generada."
                    conn.commit()
                    flash(f"Pedido {nro} → {nuevo}.{factura_msg}", "ok")
        conn.close()
        return redirect(url_for("admin_cliente_ficha", cid=cid))
    # GET: listar pedidos, facturas y pagos del cliente
    peds = conn.execute("""
        SELECT nro, fecha_hora, cliente_nombre, items_json, total, estado,
               forma_pago, lugar_entrega
        FROM pedidos
        WHERE cliente_id = ?
        ORDER BY fecha_hora DESC
    """, (cid,)).fetchall()
    peds_out = []
    for p in peds:
        d = dict(p)
        try:
            d["items"] = json.loads(d.get("items_json") or "[]")
        except Exception:
            d["items"] = []
        peds_out.append(d)
    # Facturas del cliente (asociadas por cliente_id o por total+cliente_id)
    facturas = conn.execute("""
        SELECT id, numero, fecha, total, saldo_pendiente, estado
        FROM facturas
        WHERE cliente_id = ?
        ORDER BY fecha DESC, id DESC
    """, (cid,)).fetchall()
    facturas_out = [dict(f) for f in facturas]
    # Pagos del cliente
    pagos = conn.execute("""
        SELECT id, factura_id, fecha, monto, metodo, referencia
        FROM pagos
        WHERE cliente_id = ?
        ORDER BY fecha DESC, id DESC
    """, (cid,)).fetchall()
    pagos_out = [dict(p) for p in pagos]
    # Stats comerciales
    n_pedidos = len(peds_out)
    n_pendientes = sum(1 for p in peds_out if p.get("estado") == "pendiente")
    # Facturado: suma total de pedidos facturados/cobrados/entregados
    facturado_total = sum(
        p.get("total") or 0
        for p in peds_out
        if p.get("estado") in ("aprobado", "pagado", "entregado")
    )
    # Cobrado: suma de pagos del cliente
    cobrado_total = sum(p.get("monto") or 0 for p in pagos_out)
    # Pendiente de cobro: facturado - cobrado
    pendiente_cobro = max(0, facturado_total - cobrado_total)
    # Counts para tabs
    tab = request.args.get("tab", "pedidos")
    if tab not in ("pedidos", "facturas", "pagos"):
        tab = "pedidos"
    conn.close()
    return render_template(
        "admin_cliente_ficha.html",
        cliente=cli_d,
        pedidos=peds_out,
        facturas=facturas_out,
        pagos=pagos_out,
        tab=tab,
        n_pedidos=n_pedidos,
        n_facturas=len(facturas_out),
        n_pagos=len(pagos_out),
        n_pendientes=n_pendientes,
        facturado_total=facturado_total,
        cobrado_total=cobrado_total,
        pendiente_cobro=pendiente_cobro,
        fmt=fmt_money,
    )


@app.route("/admin/clientes")
@admin_required
def admin_clientes():
    """Lista los clientes NO-admin. Columnas: Cliente (nombre + usuario
    subtexto), Razon social, Localidad, Ultimo pedido, Activo (dot).
    Ordenable por: cliente (nombre), razon_social, localidad, ultimo_pedido,
    estado. Default: nombre ASC."""
    q = (request.args.get("q") or "").strip()
    # Orden: whitelist de campos, default 'nombre', dir default 'asc'
    sort = (request.args.get("sort") or "nombre").strip().lower()
    direction = (request.args.get("dir") or "asc").strip().lower()
    if direction not in ("asc", "desc"):
        direction = "asc"
    # Whitelist: campo SQL -> (label, orderby_sql)
    sort_map = {
        "nombre":      ("Cliente",      "COALESCE(NULLIF(nombre, ''), NULLIF(razon_social, ''), usuario)"),
        "razon_social":("Razón social", "COALESCE(NULLIF(razon_social, ''), NULLIF(nombre, ''), usuario)"),
        "localidad":   ("Localidad",    "COALESCE(NULLIF(localidad, ''), 'zzz')"),
        "ultimo_pedido":("Último pedido","ultimo_pedido_fecha"),
        "estado":      ("Estado",       "activo"),
    }
    if sort not in sort_map:
        sort = "nombre"
    sort_label, orderby = sort_map[sort]
    orderby_sql = f"{orderby} {direction.upper()}, id {direction.upper()}"
    conn = get_db()
    base_filter = """
        FROM clientes
        WHERE is_admin = 0
          AND usuario != 'demo'
          AND usuario NOT LIKE 'test\\_%' ESCAPE '\\'
          AND usuario NOT LIKE 'prueba\\_%' ESCAPE '\\'
    """
    if q:
        like = f"%{q}%"
        rows = conn.execute(f"""
            SELECT id, nombre, razon_social, cuit, direccion, localidad,
                   telefono, email, usuario, cod_cliente, tipo_cliente,
                   limite_credito, notas, is_admin, activo,
                   (SELECT MAX(fecha_hora) FROM pedidos WHERE cliente_id = clientes.id) AS ultimo_pedido_fecha,
                   (SELECT nro FROM pedidos WHERE cliente_id = clientes.id ORDER BY fecha_hora DESC LIMIT 1) AS ultimo_pedido_nro,
                   (SELECT COUNT(*) FROM pedidos WHERE cliente_id = clientes.id) AS n_pedidos
            {base_filter}
              AND (nombre LIKE ? OR cod_cliente LIKE ?
                   OR usuario LIKE ? OR cuit LIKE ? OR localidad LIKE ?
                   OR razon_social LIKE ?)
            ORDER BY activo DESC, {orderby_sql}
        """, (like, like, like, like, like, like)).fetchall()
    else:
        rows = conn.execute(f"""
            SELECT id, nombre, razon_social, cuit, direccion, localidad,
                   telefono, email, usuario, cod_cliente, tipo_cliente,
                   limite_credito, notas, is_admin, activo,
                   (SELECT MAX(fecha_hora) FROM pedidos WHERE cliente_id = clientes.id) AS ultimo_pedido_fecha,
                   (SELECT nro FROM pedidos WHERE cliente_id = clientes.id ORDER BY fecha_hora DESC LIMIT 1) AS ultimo_pedido_nro,
                   (SELECT COUNT(*) FROM pedidos WHERE cliente_id = clientes.id) AS n_pedidos
            {base_filter}
            ORDER BY activo DESC, {orderby_sql}
        """).fetchall()
    conn.close()
    return render_template(
        "admin_clientes.html",
        clientes=[dict(r) for r in rows],
        q=q, fmt=fmt_money,
        sort=sort, direction=direction, sort_label=sort_label,
    )


@app.route("/admin/clientes/nuevo", methods=["GET", "POST"])
@admin_required
def admin_cliente_nuevo():
    if request.method == "GET":
        # V2.6 — modal: redirigir a la lista con ?modal=nuevo para que
        # /admin/clientes abra el modal automaticamente.
        return redirect(url_for("admin_clientes", modal="nuevo"))
    # POST: si es fetch (XHR/AJAX) devuelve JSON. Si es form normal,
    # hace redirect a la pantalla de confirmacion (compatibilidad).
    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )
    # Bloque E (nuevo alcance) - alta minima: SOLO el usuario. La contrasena
    # se genera automaticamente (6 digitos numericos) y se muestra UNA vez.
    usuario = (request.form.get("usuario") or "").strip().lower()
    errs = []
    if not usuario:
        errs.append("usuario es obligatorio.")
    elif not re.match(r"^[a-záéíóúüñ0-9_]{3,20}$", usuario):
        errs.append("usuario debe tener 3-20 chars: letras, numeros y guion bajo.")
    if errs:
        if is_ajax:
            return jsonify({"ok": False, "error": " · ".join(errs)}), 400
        return render_template("admin_cliente_form.html", cliente=None,
                               form_data={"usuario": usuario},
                               mensaje={"tipo": "error", "texto": " · ".join(errs)},
                               fmt=fmt_money), 400
    conn = get_db()
    if conn.execute("SELECT 1 FROM clientes WHERE usuario = ?",
                    (usuario,)).fetchone():
        conn.close()
        if is_ajax:
            return jsonify({"ok": False, "error": f"Ya existe el usuario '{usuario}'."}), 400
        return render_template("admin_cliente_form.html", cliente=None,
                               form_data={"usuario": usuario},
                               mensaje={"tipo": "error",
                                        "texto": f"Ya existe el usuario '{usuario}'."},
                               fmt=fmt_money), 400
    # Generar contrasena: 6 digitos numericos
    pass_plain = f"{secrets.randbelow(1000000):06d}"
    pass_hash = generate_password_hash(pass_plain)
    # Descuentos opcionales (NULL si el input viene vacio o invalido)
    desc_adn = _parse_descuento(request.form.get("descuento_adn"))
    desc_cem = _parse_descuento(request.form.get("descuento_cemento"))
    desc_res = _parse_descuento(request.form.get("descuento_resto"))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO clientes (
            cod_cliente, usuario, nombre, password_hash, password_temporal,
            activo, is_admin, email, telefono, direccion, localidad,
            razon_social, cuit, tipo_cliente, limite_credito, notas,
            geo_radio_km, descuento_adn, descuento_cemento, descuento_resto,
            updated_at
        ) VALUES (NULL, ?, '', ?, 1, 1, 0, NULL, NULL, NULL, NULL, NULL,
                NULL, NULL, 0, NULL, 3.0, ?, ?, ?,
                CURRENT_TIMESTAMP)
    """, (usuario, pass_hash, desc_adn, desc_cem, desc_res))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    if is_ajax:
        return jsonify({
            "ok": True,
            "usuario": usuario,
            "pass": pass_plain,
            "cid": new_id,
        })
    # Fallback para acceso directo a la URL
    return render_template(
        "admin_cliente_form.html",
        cliente=None,
        mensaje=None,
        form_data=None,
        fmt=fmt_money,
        show_modal=True,
        modal_pass=pass_plain,
        modal_usuario=usuario,
        modal_cid=new_id,
    )


@app.route("/admin/clientes/creado", methods=["GET"])
@admin_required
def admin_cliente_creado():
    """Pantalla de confirmacion: muestra la contrasena UNA sola vez
    despues de un alta exitosa. El admin la copia y se la pasa al cliente."""
    cid = request.args.get("cid", type=int)
    pass_plain = request.args.get("_pass", "")
    if not cid or not pass_plain:
        abort(404)
    conn = get_db()
    row = conn.execute(
        "SELECT id, usuario, nombre FROM clientes WHERE id = ?", (cid,)
    ).fetchone()
    conn.close()
    if not row:
        abort(404)
    # NO loguear la pass. Mostrarla una sola vez.
    return render_template(
        "admin_cliente_creado.html",
        cliente=dict(row), pass_plain=pass_plain,
    )


@app.route("/admin/clientes/<int:cid>/tipo", methods=["POST"])
@admin_required
def admin_cliente_tipo(cid):
    """Actualiza SOLO el tipo_cliente del cliente. Usado en la ficha."""
    tipo = (request.form.get("tipo_cliente") or "").strip()
    tipos_validos = ("responsable_inscripto", "monotributo", "consumidor_final", "exento")
    if tipo not in tipos_validos:
        flash("Tipo de cliente invalido.", "error")
        return redirect(url_for("admin_cliente_ficha", cid=cid))
    conn = get_db()
    conn.execute(
        "UPDATE clientes SET tipo_cliente = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (tipo, cid),
    )
    conn.commit()
    conn.close()
    flash("Tipo de cliente actualizado.", "ok")
    return redirect(url_for("admin_cliente_ficha", cid=cid))


@app.route("/admin/clientes/<int:cid>/descuentos", methods=["POST"])
@admin_required
def admin_cliente_descuentos(cid):
    """Actualiza SOLO los 3 campos de descuento del cliente (admin).
    Inputs opcionales; vacio o invalido -> NULL."""
    desc_adn = _parse_descuento(request.form.get("descuento_adn"))
    desc_cem = _parse_descuento(request.form.get("descuento_cemento"))
    desc_res = _parse_descuento(request.form.get("descuento_resto"))
    conn = get_db()
    row = conn.execute("SELECT id, usuario FROM clientes WHERE id = ?", (cid,)).fetchone()
    if not row:
        conn.close(); abort(404)
    conn.execute("""
        UPDATE clientes SET
            descuento_adn = ?, descuento_cemento = ?, descuento_resto = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (desc_adn, desc_cem, desc_res, cid))
    conn.commit()
    conn.close()
    flash(f"Descuentos de {row['usuario']} actualizados.", "ok")
    return redirect(url_for("admin_cliente_ficha", cid=cid))


@app.route("/admin/clientes/<int:cid>/editar", methods=["GET", "POST"])
@admin_required
def admin_cliente_editar(cid):
    conn = get_db()
    cliente = conn.execute("SELECT * FROM clientes WHERE id = ?", (cid,)).fetchone()
    if not cliente:
        conn.close(); abort(404)
    if request.method == "GET":
        conn.close()
        return render_template("admin_cliente_form.html", cliente=dict(cliente),
                               mensaje=None, fmt=fmt_money)
    data, errs = _parse_cliente_form(request.form)
    if errs:
        conn.close()
        return render_template("admin_cliente_form.html", cliente=cliente,
                               mensaje={"tipo": "error", "texto": " · ".join(errs)},
                               fmt=fmt_money), 400
    # cod_cliente ES editable desde el modal Editar (pedido Fer 2.2).
    cur = conn.cursor()
    if data["password"]:
        # Si se cambio la password, marcala como temporal para que Fer
        # se la pase al cliente.
        cur.execute("""
            UPDATE clientes SET
              nombre=?, razon_social=?, cuit=?, cod_cliente=?, localidad=?, direccion=?,
              telefono=?, email=?, tipo_cliente=?, limite_credito=?, notas=?,
              is_admin=?, updated_at=CURRENT_TIMESTAMP,
              password_hash=?, password_temporal=1
            WHERE id=?
        """, (
            data["nombre"] or "", data["razon_social"], data["cuit"], data["cod_cliente"],
            data["localidad"], data["direccion"], data["telefono"],
            data["email"], data["tipo_cliente"], data["limite_credito"],
            data["notas"], data["is_admin"],
            generate_password_hash(data["password"]), cid
        ))
    else:
        cur.execute("""
            UPDATE clientes SET
              nombre=?, razon_social=?, cuit=?, cod_cliente=?, localidad=?, direccion=?,
              telefono=?, email=?, tipo_cliente=?, limite_credito=?, notas=?,
              is_admin=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (
            data["nombre"] or "", data["razon_social"], data["cuit"], data["cod_cliente"],
            data["localidad"], data["direccion"], data["telefono"],
            data["email"], data["tipo_cliente"], data["limite_credito"],
            data["notas"], data["is_admin"], cid
        ))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_cliente_ficha", cid=cid))


@app.route("/admin/clientes/<int:cid>/toggle", methods=["POST"])
@admin_required
def admin_cliente_toggle(cid):
    conn = get_db()
    conn.execute("UPDATE clientes SET activo = 1 - activo, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (cid,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_clientes") + "?msg=toggled")


@app.route("/admin/clientes/<int:cid>/detalle", methods=["GET"])
@admin_required
def admin_cliente_detalle(cid):
    """Devuelve JSON con todos los datos del cliente + pedidos confirmados
    para alimentar el desplegable inline en /admin/clientes."""
    conn = get_db()
    cli = conn.execute(
        """SELECT id, cod_cliente, usuario, nombre, razon_social, cuit,
                  email, telefono, direccion, localidad, tipo_cliente,
                  limite_credito, notas, is_admin, activo,
                  descuento_adn, descuento_cemento, descuento_resto,
                  device_token, device_first_login, device_last_login, device_label
             FROM clientes WHERE id = ?""", (cid,)
    ).fetchone()
    if not cli:
        conn.close(); abort(404)
    if not cli:
        conn.close()
        return jsonify({"ok": False, "error": "Cliente no encontrado"}), 404
    cli_d = dict(cli)
    # Truncar device_token para mostrar
    if cli_d.get("device_token"):
        t = cli_d["device_token"]
        cli_d["device_token_short"] = t[:8] + "..." + t[-4:] if len(t) > 16 else t
    else:
        cli_d["device_token_short"] = None
    # Pedidos confirmados (pendiente|aprobado|rechazado) del cliente
    peds = conn.execute("""
        SELECT nro, fecha_hora, cliente_nombre, items_json, total, estado,
               forma_pago, lugar_entrega
        FROM pedidos
        WHERE cliente_id = ? AND estado IN ('pendiente', 'aprobado', 'rechazado')
        ORDER BY fecha_hora DESC
    """, (cid,)).fetchall()
    peds_out = []
    for p in peds:
        d = dict(p)
        try:
            d["items"] = json.loads(d.get("items_json") or "[]")
        except Exception:
            d["items"] = []
        peds_out.append(d)
    conn.close()
    return jsonify({"ok": True, "cliente": cli_d, "pedidos": peds_out})


@app.route("/admin/clientes/<int:cid>/notas", methods=["POST"])
@admin_required
def admin_cliente_notas(cid):
    """Guarda el campo notas del cliente."""
    notas = (request.form.get("notas") or "").strip()
    conn = get_db()
    conn.execute(
        "UPDATE clientes SET notas = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (notas or None, cid)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "notas": notas})


@app.route("/admin/clientes/<int:cid>/pedido/<nro>/estado", methods=["POST"])
@admin_required
def admin_cliente_pedido_estado(cid, nro):
    """Cambia el estado de un pedido del cliente. Idempotente: si pasa a
    aprobado y ya existe la factura, no duplica."""
    nuevo = (request.form.get("nuevo_estado") or "").strip().lower()
    if nuevo not in ESTADOS_PEDIDO:
        return jsonify({"ok": False, "error": f"Estado invalido: {nuevo}"}), 400
    conn = get_db()
    row = conn.execute(
        "SELECT nro, cliente_id FROM pedidos WHERE nro = ?", (nro,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "Pedido no encontrado"}), 404
    if row["cliente_id"] != cid:
        conn.close()
        return jsonify({"ok": False, "error": "Pedido no pertenece al cliente"}), 400
    conn.execute("UPDATE pedidos SET estado = ? WHERE nro = ?", (nuevo, nro))
    factura_msg = ""
    if nuevo == "aprobado":
        existing = conn.execute(
            "SELECT id FROM facturas WHERE numero = ?", (nro,)
        ).fetchone()
        if not existing:
            pedido = conn.execute(
                "SELECT cliente_id, fecha_hora, total FROM pedidos WHERE nro = ?", (nro,)
            ).fetchone()
            conn.execute("""
                INSERT INTO facturas
                    (cliente_id, numero, fecha, total, saldo_pendiente, estado)
                VALUES (?, ?, ?, ?, ?, 'pendiente')
            """, (
                pedido["cliente_id"], nro, pedido["fecha_hora"].split()[0],
                pedido["total"], pedido["total"],
            ))
            factura_msg = " (factura generada)"
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "estado": nuevo, "msg": f"Estado actualizado{factura_msg}"})


# -----------------------------------------------------------------------------
# Bloque C - gestion de devices (device-binding)
# -----------------------------------------------------------------------------

@app.route("/admin/clientes/<int:cid>/device", methods=["GET"])
@admin_required
def admin_cliente_device(cid):
    """Detalle del device vinculado a un cliente."""
    conn = get_db()
    row = conn.execute(
        """SELECT id, cod_cliente, usuario, nombre, activo, is_admin,
                  device_token, device_first_login, device_last_login, device_label
             FROM clientes WHERE id = ?""", (cid,)
    ).fetchone()
    conn.close()
    if not row:
        abort(404)
    return render_template("admin_cliente_device.html", cliente=dict(row))


@app.route("/admin/clientes/<int:cid>/device/revoke", methods=["POST"])
@admin_required
def admin_cliente_device_revoke(cid):
    """Revoca el device: limpia device_token y los otros campos device_*."""
    conn = get_db()
    row = conn.execute("SELECT id, usuario FROM clientes WHERE id = ?", (cid,)).fetchone()
    if not row:
        conn.close(); abort(404)
    conn.execute("""
        UPDATE clientes SET
            device_token = NULL,
            device_first_login = NULL,
            device_last_login = NULL,
            device_label = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (cid,))
    conn.commit()
    conn.close()
    flash(f"Device revocado para {row['usuario']}.", "ok")
    return redirect(url_for("admin_cliente_device", cid=cid))


# =============================================================================
# Mi Cuenta - edicion
# =============================================================================

@app.route("/bienvenida", methods=["GET", "POST"])
@login_required
def bienvenida():
    """Pantalla BLOQUEANTE para clientes nuevos. Modal full-screen con los
    7 campos obligatorios. No se puede cerrar ni navegar a otra ruta
    hasta que esten todos llenos. Al guardar, redirige al home real (/)."""
    cid = session["cliente_id"]
    conn = get_db()
    cli = conn.execute(
        """SELECT id, cod_cliente, usuario, nombre, razon_social, cuit,
                  email, telefono, direccion, localidad, tipo_cliente,
                  limite_credito, notas, is_admin, activo
             FROM clientes WHERE id = ?""", (cid,)
    ).fetchone()
    if not cli:
        conn.close(); abort(404)
    cli_d = dict(cli)
    # Si ya completo los 7 datos, redirigir al home
    campos_oblig = ("nombre", "razon_social", "cuit", "direccion", "localidad", "telefono", "email")
    if not any(not (cli_d.get(c)) for c in campos_oblig):
        conn.close()
        return redirect(url_for("rubros"))
    if request.method == "POST":
        errs = []
        data = {}
        for c in campos_oblig:
            v = (request.form.get(c) or "").strip()
            if not v:
                errs.append(f"{c} es obligatorio.")
            data[c] = v
        if errs:
            conn.close()
            return render_template(
                "bienvenida.html",
                cliente=cli_d,
                form_data=data,
                mensaje={"tipo": "error", "texto": " · ".join(errs)},
            ), 400
        conn.execute("""
            UPDATE clientes SET
              nombre=?, razon_social=?, cuit=?, direccion=?, localidad=?,
              telefono=?, email=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (data["nombre"], data["razon_social"], data["cuit"],
              data["direccion"], data["localidad"],
              data["telefono"], data["email"], cid))
        conn.commit()
        # Actualizar session
        session["cliente_nombre"] = data["nombre"]
        session["cliente_email"] = data["email"]
        session["cliente_telefono"] = data["telefono"]
        session["cliente_direccion"] = data["direccion"]
        # Limpiar el flag para que el modal no vuelva a aparecer.
        session.pop("show_welcome_modal", None)
        conn.close()
        return redirect(url_for("rubros"))
    conn.close()
    return render_template("bienvenida.html", cliente=cli_d, form_data=None, mensaje=None)


@app.route("/mi-cuenta/completar", methods=["GET", "POST"])
@login_required
def mi_cuenta_completar():
    """Pagina OBLIGATORIA de primer login. El cliente debe llenar los 7
    datos personales (nombre, razon_social, cuit, direccion, localidad,
    telefono, email) + tipo_cliente antes de poder navegar. NO se puede
    salir sin completar - la sesion queda marcada como 'datos_completos=1'."""
    cid = session["cliente_id"]
    conn = get_db()
    cli = conn.execute(
        "SELECT id, usuario, nombre, razon_social, cuit, direccion, localidad, telefono, email, tipo_cliente FROM clientes WHERE id = ?",
        (cid,)
    ).fetchone()
    if not cli:
        conn.close(); abort(404)

    # Helper: que campos faltan (8 campos, incluido tipo_cliente)
    campos_oblig = ("nombre", "razon_social", "cuit", "direccion", "localidad", "telefono", "email", "tipo_cliente")
    faltantes_v = [c for c in campos_oblig if not (cli[c] if c in cli.keys() else None)]

    if request.method == "GET":
        conn.close()
        return render_template("mi_cuenta_completar.html",
                               cliente=dict(cli), faltantes=faltantes_v)

    # POST: validar y guardar
    errs = []
    data = {}
    for c in campos_oblig:
        v = (request.form.get(c) or "").strip()
        if not v:
            errs.append(f"{c} es obligatorio.")
        data[c] = v
    # Validar que tipo_cliente sea uno de los 4 valores
    tipos_validos = ("responsable_inscripto", "monotributo", "consumidor_final", "exento")
    if data.get("tipo_cliente") and data["tipo_cliente"] not in tipos_validos:
        errs.append("tipo_cliente invalido.")
    if errs:
        conn.close()
        return render_template("mi_cuenta_completar.html",
                               cliente=dict(cli), faltantes=faltantes_v,
                               form_data=data,
                               mensaje={"tipo": "error", "texto": " · ".join(errs)}), 400

    conn.execute("""
        UPDATE clientes SET
          nombre=?, razon_social=?, cuit=?, direccion=?, localidad=?,
          telefono=?, email=?, tipo_cliente=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (data["nombre"], data["razon_social"], data["cuit"],
          data["direccion"], data["localidad"],
          data["telefono"], data["email"], data["tipo_cliente"], cid))
    conn.commit()

    # Refrescar session con los datos para que navbar los muestre
    session["cliente_nombre"] = data["nombre"]
    session["cliente_email"] = data["email"]
    session["cliente_telefono"] = data["telefono"]
    session["cliente_direccion"] = data["direccion"]
    conn.close()
    flash("Listo, ya podes hacer pedidos.", "ok")
    return redirect(url_for("rubros"))


@app.route("/mi-cuenta/editar", methods=["GET", "POST"])
@login_required
def mi_cuenta_editar():
    """Edita solo los datos personales del cliente. NO muestra ni edita
    usuario ni contrasena (eso lo maneja el admin desde /admin/clientes)."""
    cid = session["cliente_id"]
    conn = get_db()
    if request.method == "GET":
        cliente = conn.execute(
            "SELECT * FROM clientes WHERE id = ?", (cid,)
        ).fetchone()
        conn.close()
        if not cliente:
            abort(404)
        return render_template("mi_cuenta_editar.html", cliente=dict(cliente))
    # POST: actualizar
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre es obligatorio.", "error")
        return redirect(url_for("mi_cuenta_editar"))
    razon_social = request.form.get("razon_social", "").strip() or None
    cuit = request.form.get("cuit", "").strip() or None
    localidad = request.form.get("localidad", "").strip() or None
    direccion = request.form.get("direccion", "").strip() or None
    telefono = request.form.get("telefono", "").strip() or None
    email = request.form.get("email", "").strip() or None
    conn.execute("""
        UPDATE clientes SET
          nombre=?, razon_social=?, cuit=?, localidad=?, direccion=?,
          telefono=?, email=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (
        nombre, razon_social, cuit, localidad, direccion, telefono,
        email, cid
    ))
    conn.commit()
    session["cliente_nombre"] = nombre
    session["cliente_email"] = email or ""
    session["cliente_telefono"] = telefono or ""
    session["cliente_direccion"] = direccion or ""
    conn.close()
    flash("Datos actualizados.", "ok")
    return redirect(url_for("mi_cuenta"))


@app.route("/mi-cuenta/cambiar-password", methods=["POST"])
@login_required
def mi_cuenta_cambiar_password():
    cid = session["cliente_id"]
    actual = request.form.get("actual", "")
    nueva = request.form.get("nueva", "")
    repetir = request.form.get("repetir", "")
    if not (actual and nueva and repetir):
        flash("Completá los tres campos.", "error")
        return redirect(url_for("mi_cuenta"))
    if nueva != repetir:
        flash("La nueva contraseña no coincide.", "error")
        return redirect(url_for("mi_cuenta"))
    if len(nueva) < 4:
        flash("La nueva contraseña debe tener al menos 4 caracteres.", "error")
        return redirect(url_for("mi_cuenta"))
    conn = get_db()
    row = conn.execute("SELECT password_hash FROM clientes WHERE id = ?", (cid,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], actual):
        conn.close()
        flash("La contraseña actual es incorrecta.", "error")
        return redirect(url_for("mi_cuenta"))
    conn.execute("UPDATE clientes SET password_hash = ?, password_temporal = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                 (generate_password_hash(nueva), cid))
    conn.commit()
    conn.close()
    flash("Contraseña actualizada.", "ok")
    return redirect(url_for("mi_cuenta"))


@app.route("/admin/reset", methods=["POST"])
@admin_required
def admin_reset():
    """Recarga productos desde data.json sin tocar clientes."""
    from init_db import seed_productos  # type: ignore
    seed_productos(DATA_JSON, DB_PATH)
    flash("Lista de precios recargada.", "ok")
    return redirect(url_for("admin"))


# -----------------------------------------------------------------------------
# Bloque E - Gestion de pedidos (admin)
# -----------------------------------------------------------------------------

ESTADOS_PEDIDO = ("pendiente", "aprobado", "rechazado", "entregado", "pagado")


@app.route("/admin/pedidos")
@admin_required
def admin_pedidos():
    """Bloque V2.1: lista de pedidos web con 4 filtros (Pendientes /
    Facturados / Cobrados / Entregados), filas colapsables con tabla
    de items + acciones, sin boton Rechazar (Fer no lo usa), flag +24h
    para pedidos pendientes viejos. Transiciones de estado:
    pendiente -> aprobado, aprobado -> entregado, aprobado -> pagado."""
    from datetime import datetime
    filtro = (request.args.get("f") or "pendientes").strip().lower()
    if filtro not in ("todos", "pendientes", "facturados", "cobrados", "entregados"):
        filtro = "pendientes"
    conn = get_db()
    # Counts por filtro (para badges)
    counts = {
        "todos": conn.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0],
        "pendientes": conn.execute("SELECT COUNT(*) FROM pedidos WHERE estado = 'pendiente'").fetchone()[0],
        "facturados": conn.execute("SELECT COUNT(*) FROM pedidos WHERE estado = 'aprobado'").fetchone()[0],
        "cobrados":   conn.execute("SELECT COUNT(*) FROM pedidos WHERE estado = 'pagado'").fetchone()[0],
        "entregados": conn.execute("SELECT COUNT(*) FROM pedidos WHERE estado = 'entregado'").fetchone()[0],
    }
    # Pedidos segun filtro
    if filtro == "todos":
        rows = conn.execute("SELECT * FROM pedidos ORDER BY fecha_hora DESC").fetchall()
    elif filtro == "pendientes":
        rows = conn.execute("SELECT * FROM pedidos WHERE estado = 'pendiente' ORDER BY fecha_hora DESC").fetchall()
    elif filtro == "facturados":
        rows = conn.execute("SELECT * FROM pedidos WHERE estado = 'aprobado' ORDER BY fecha_hora DESC").fetchall()
    elif filtro == "cobrados":
        rows = conn.execute("SELECT * FROM pedidos WHERE estado = 'pagado' ORDER BY fecha_hora DESC").fetchall()
    elif filtro == "entregados":
        rows = conn.execute("SELECT * FROM pedidos WHERE estado = 'entregado' ORDER BY fecha_hora DESC").fetchall()
    conn.close()
    ahora = datetime.now()
    pedidos_out = []
    for r in rows:
        d = dict(r)
        try:
            d["items"] = json.loads(d.get("items_json") or "[]")
        except Exception:
            d["items"] = []
        # Edad del pedido en horas
        try:
            fh = (d.get("fecha_hora") or "").split(".")[0]
            dt = datetime.strptime(fh, "%Y-%m-%d %H:%M:%S")
            d["edad_horas"] = (ahora - dt).total_seconds() / 3600
            d["es_viejo"] = d["edad_horas"] > 24
        except Exception:
            d["edad_horas"] = 0
            d["es_viejo"] = False
        pedidos_out.append(d)
    return render_template(
        "admin_pedidos.html",
        pedidos=pedidos_out,
        filtro=filtro,
        counts=counts,
        estados=ESTADOS_PEDIDO,
        fmt=fmt_money,
    )


@app.route("/admin/pedidos/<nro>/estado", methods=["POST"])
@admin_required
def admin_pedido_estado(nro):
    """Cambia el estado de un pedido con validaciones bloqueantes:
    - pendiente -> aprobado (facturado): requiere nro_factura
    - aprobado -> pagado (cobrado): requiere forma_pago + fecha_pago
    - aprobado/pagado -> entregado: sin requisitos extra
    - cualquier otro cambio: permitido sin requisitos (admin override)."""
    nuevo = (request.form.get("nuevo_estado") or "").strip().lower()
    if nuevo not in ESTADOS_PEDIDO:
        flash(f"Estado invalido: {nuevo}", "error")
        return redirect(url_for("admin_pedidos"))
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM pedidos WHERE nro = ?", (nro,)
    ).fetchone()
    if not row:
        conn.close(); abort(404)
    estado_actual = row["estado"]
    # Validaciones bloqueantes
    if estado_actual == "pendiente" and nuevo == "aprobado":
        nro_factura = (request.form.get("nro_factura") or "").strip()
        if not nro_factura:
            conn.close()
            flash("Para facturar un pedido es obligatorio ingresar el numero de factura.", "error")
            return redirect(url_for("admin_pedido_facturar", nro=nro))
    if estado_actual == "aprobado" and nuevo == "pagado":
        forma_pago = (request.form.get("forma_pago_pago") or "").strip()
        fecha_pago = (request.form.get("fecha_pago") or "").strip()
        if not forma_pago or not fecha_pago:
            conn.close()
            flash("Para cobrar un pedido es obligatorio ingresar forma de pago y fecha.", "error")
            return redirect(url_for("admin_pedido_cobrar", nro=nro))
    conn.execute(
        "UPDATE pedidos SET estado = ? WHERE nro = ?", (nuevo, nro)
    )
    # Si pasa a aprobado (facturado), crear/actualizar factura con nro_factura
    factura_msg = ""
    if estado_actual == "pendiente" and nuevo == "aprobado":
        nro_factura = (request.form.get("nro_factura") or "").strip()
        existing = conn.execute(
            "SELECT id FROM facturas WHERE numero = ?", (nro_factura,)
        ).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO facturas
                    (cliente_id, numero, fecha, total, saldo_pendiente, estado)
                VALUES (?, ?, ?, ?, ?, 'pendiente')
            """, (
                row["cliente_id"], nro_factura, row["fecha_hora"].split()[0],
                row["total"], row["total"],
            ))
            factura_msg = f" Factura {nro_factura} generada."
        else:
            factura_msg = f" Factura {nro_factura} (ya existia) actualizada."
    # Si pasa a pagado, registrar el pago en tabla pagos
    pago_msg = ""
    if estado_actual == "aprobado" and nuevo == "pagado":
        forma_pago = (request.form.get("forma_pago_pago") or "").strip()
        fecha_pago = (request.form.get("fecha_pago") or "").strip()
        # Buscar factura_id asociada
        fac = conn.execute(
            "SELECT id, numero FROM facturas WHERE cliente_id = ? AND total = ? ORDER BY id DESC LIMIT 1",
            (row["cliente_id"], row["total"]),
        ).fetchone()
        factura_id = fac["id"] if fac else None
        nro_factura = fac["numero"] if fac else nro
        conn.execute("""
            INSERT INTO pagos (factura_id, cliente_id, fecha, monto, metodo, referencia)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            factura_id, row["cliente_id"], fecha_pago, row["total"],
            forma_pago, nro_factura,
        ))
        # Marcar factura como pagada
        if factura_id:
            conn.execute(
                "UPDATE facturas SET saldo_pendiente = 0, estado = 'pagada' WHERE id = ?",
                (factura_id,),
            )
        pago_msg = f" Pago {forma_pago} ${row['total']:.2f} registrado."
    conn.commit()
    conn.close()
    flash(f"Pedido {nro} → {nuevo}.{factura_msg}{pago_msg}", "ok")
    # Volver al filtro apropiado
    filtro_volver = {
        "pendiente": "pendientes",
        "aprobado": "facturados",
        "pagado": "cobrados",
        "entregado": "entregados",
        "rechazado": "pendientes",
    }.get(nuevo, "pendientes")
    return redirect(url_for("admin_pedidos", f=filtro_volver))


@app.route("/admin/pedidos/<nro>/facturar", methods=["GET", "POST"])
@admin_required
def admin_pedido_facturar(nro):
    """Form para facturar un pedido pendiente. Pide el nro_factura.
    El form hace POST a /admin/pedidos/<nro>/estado con nuevo_estado=aprobado
    + nro_factura. Si ya esta aprobado, redirige."""
    conn = get_db()
    row = conn.execute(
        "SELECT nro, cliente_nombre, cliente_id, estado, total FROM pedidos WHERE nro = ?",
        (nro,),
    ).fetchone()
    conn.close()
    if not row:
        abort(404)
    if row["estado"] != "pendiente":
        flash(f"Este pedido ya esta en estado '{row['estado']}'.", "error")
        return redirect(url_for("admin_pedidos"))
    if request.method == "POST":
        # Reenviar al endpoint de estado
        nro_factura = (request.form.get("nro_factura") or "").strip()
        if not nro_factura:
            flash("Numero de factura obligatorio.", "error")
            return redirect(url_for("admin_pedido_facturar", nro=nro))
        # Validar que no exista otra factura con ese numero
        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM facturas WHERE numero = ?", (nro_factura,)
        ).fetchone()
        if existing:
            conn.close()
            flash(f"Ya existe la factura {nro_factura}. Usa otro numero.", "error")
            return redirect(url_for("admin_pedido_facturar", nro=nro))
        # V2.14: PDF de factura (opcional, pero recomendado)
        archivo_path = None
        if 'factura_pdf' in request.files:
            pdf_file = request.files['factura_pdf']
            content, ext, err = _validar_archivo(pdf_file, [PDF_MAGIC], MAX_PDF_SIZE)
            if err:
                conn.close()
                flash(f"PDF no valido: {err}", "error")
                return redirect(url_for("admin_pedido_facturar", nro=nro))
            if content:
                archivo_path = _guardar_factura_pdf(nro_factura, content)
        # Crear factura + cambiar estado
        conn.execute(
            "UPDATE pedidos SET estado = 'aprobado' WHERE nro = ?", (nro,)
        )
        conn.execute("""
            INSERT INTO facturas (cliente_id, numero, fecha, total, saldo_pendiente, estado, archivo_path)
            VALUES (?, ?, ?, ?, ?, 'pendiente', ?)
        """, (
            row["cliente_id"] if "cliente_id" in row.keys() else 0,
            nro_factura,
            datetime.now().strftime("%Y-%m-%d"),
            row["total"], row["total"],
            archivo_path,
        ))
        conn.commit()
        conn.close()
        msg = f"Pedido {nro} facturado como {nro_factura}."
        if archivo_path: msg += f" PDF guardado."
        flash(msg, "ok")
        return redirect(url_for("admin_pedidos", f="facturados"))
    # GET: mostrar form
    # Sugerir un numero de factura default
    conn = get_db()
    last_num = conn.execute(
        "SELECT numero FROM facturas ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    sugerido = ""
    if last_num:
        num = last_num["numero"]
        # Intentar incrementar sufijo numerico
        import re as _re
        m = _re.search(r"(\d+)$", num)
        if m:
            sugerido = num[:m.start()] + str(int(m.group(1)) + 1).zfill(len(m.group(1)))
    return render_template(
        "admin_pedido_facturar.html",
        nro=nro, cliente_nombre=row["cliente_nombre"], total=row["total"],
        nro_factura_sugerido=sugerido, fmt=fmt_money,
    )


@app.route("/admin/pedidos/<nro>/cobrar", methods=["GET", "POST"])
@admin_required
def admin_pedido_cobrar(nro):
    """Form para cobrar un pedido facturado. Pide forma_pago y fecha_pago.
    El form hace POST a /admin/pedidos/<nro>/estado con nuevo_estado=pagado
    + forma_pago_pago + fecha_pago."""
    conn = get_db()
    row = conn.execute(
        "SELECT nro, cliente_nombre, cliente_id, estado, total, forma_pago FROM pedidos WHERE nro = ?",
        (nro,),
    ).fetchone()
    # Buscar factura asociada para mostrar el nro_factura arriba
    nro_factura = None
    if row:
        fac = conn.execute(
            "SELECT numero FROM facturas WHERE cliente_id = ? AND ABS(total - ?) < 0.01 ORDER BY id DESC LIMIT 1",
            (row["cliente_id"], row["total"]),
        ).fetchone()
        if fac:
            nro_factura = fac["numero"]
    conn.close()
    if not row:
        abort(404)
    if row["estado"] != "aprobado":
        flash(f"Este pedido esta en estado '{row['estado']}', no se puede cobrar.", "error")
        return redirect(url_for("admin_pedidos"))
    # FIX 1: precargar forma_pago del pedido para que se muestre readonly en el form
    forma_pago_pedido = (row["forma_pago"] or "").strip()
    if request.method == "POST":
        forma_pago = (request.form.get("forma_pago_pago") or "").strip()
        fecha_pago = (request.form.get("fecha_pago") or "").strip()
        if not forma_pago or not fecha_pago:
            flash("Forma de pago y fecha son obligatorios.", "error")
            return redirect(url_for("admin_pedido_cobrar", nro=nro))
        # Buscar factura
        conn = get_db()
        fac = conn.execute(
            "SELECT id, numero FROM facturas WHERE cliente_id = ? AND ABS(total - ?) < 0.01 ORDER BY id DESC LIMIT 1",
            (row["cliente_id"], row["total"]),
        ).fetchone()
        factura_id = fac["id"] if fac else None
        nro_factura = fac["numero"] if fac else nro
        # Insertar pago
        conn.execute("""
            INSERT INTO pagos (factura_id, cliente_id, fecha, monto, metodo, referencia)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            factura_id, row["cliente_id"], fecha_pago, row["total"],
            forma_pago, nro_factura,
        ))
        # Cambiar estado del pedido
        conn.execute(
            "UPDATE pedidos SET estado = 'pagado' WHERE nro = ?", (nro,)
        )
        # Marcar factura como pagada
        if factura_id:
            conn.execute(
                "UPDATE facturas SET saldo_pendiente = 0, estado = 'pagada' WHERE id = ?",
                (factura_id,),
            )
        conn.commit()
        conn.close()
        flash(f"Pedido {nro} cobrado: {forma_pago} el {fecha_pago}.", "ok")
        return redirect(url_for("admin_pedidos", f="cobrados"))
    # GET: mostrar form
    return render_template(
        "admin_pedido_cobrar.html",
        nro=nro, cliente_nombre=row["cliente_nombre"], total=row["total"],
        nro_factura=nro_factura, forma_pago=forma_pago_pedido,
        hoy=datetime.now().strftime("%Y-%m-%d"), fmt=fmt_money,
    )


# FIX 3 — Eliminar un pedido (pendiente o aprobado). Cascade: borra pagos
# y factura asociada si los hay.
@app.route("/admin/pedidos/<nro>/eliminar", methods=["POST"], endpoint="admin_pedido_eliminar")
@admin_required
def admin_pedido_eliminar(nro):
    conn = get_db()
    row = conn.execute("SELECT nro, estado, cliente_id, total FROM pedidos WHERE nro = ?", (nro,)).fetchone()
    if not row:
        conn.close()
        abort(404)
    # Borro pagos referidos a la factura del pedido (si existe)
    fac = conn.execute(
        "SELECT id FROM facturas WHERE cliente_id = ? AND ABS(total - ?) < 0.01 ORDER BY id DESC LIMIT 1",
        (row["cliente_id"], row["total"]),
    ).fetchone()
    if fac:
        conn.execute("DELETE FROM pagos WHERE factura_id = ?", (fac["id"],))
        conn.execute("DELETE FROM facturas WHERE id = ?", (fac["id"],))
    conn.execute("DELETE FROM pedidos WHERE nro = ?", (nro,))
    conn.commit()
    conn.close()
    flash(f"Pedido {nro} eliminado.", "ok")
    return redirect(url_for("admin_pedidos"))


# V2.14 — Cliente carga su comprobante de pago
@app.route("/mi-cuenta/pagos/nuevo", methods=["GET", "POST"])
@login_required
def cliente_pago_nuevo():
    """El cliente carga un pago subiendo comprobante (PDF/JPG/PNG) + metodo + fecha.
    Solo para pedidos en estado 'aprobado' (facturado). Crea fila en pagos
    con comprobante_path. El admin confirma el cambio a 'pagado' aparte."""
    cid = session["cliente_id"]
    nro = (request.args.get("nro") or request.form.get("nro") or "").strip()
    conn = get_db()
    if nro:
        # Asegurar que el pedido es del cliente y esta facturado
        row = conn.execute(
            "SELECT nro, total, estado FROM pedidos WHERE nro = ? AND cliente_id = ?",
            (nro, cid),
        ).fetchone()
        if not row:
            conn.close(); abort(404)
        if row["estado"] != "aprobado":
            conn.close()
            flash(f"Tu pedido #{nro} no esta en estado 'facturado' (esta en '{row['estado']}').", "error")
            return redirect(url_for("mi_cuenta", tab="pagos"))
    if request.method == "POST":
        if not nro:
            conn.close()
            flash("Falta el pedido.", "error")
            return redirect(url_for("mi_cuenta", tab="pedidos"))
        forma_pago = (request.form.get("metodo") or "").strip()
        fecha_pago = (request.form.get("fecha") or "").strip()
        if not forma_pago or not fecha_pago:
            conn.close()
            flash("Forma de pago y fecha son obligatorios.", "error")
            return redirect(url_for("cliente_pago_nuevo", nro=nro))
        # Normalizar a lowercase y validar contra CHECK constraint
        # (la DB acepta solo efectivo/transferencia/cheque).
        # Las opciones Tarjeta/MercadoPago/Otro del template se rechazan
        # con 400 claro en vez de explotar con 500.
        METODOS_VALIDOS = ("efectivo", "transferencia", "cheque")
        forma_pago_norm = forma_pago.lower()
        if forma_pago_norm not in METODOS_VALIDOS:
            conn.close()
            flash(
                f"Forma de pago '{forma_pago}' no soportada. Usar: Efectivo, "
                f"Transferencia o Cheque. Para otros medios consultar al admin.",
                "error",
            )
            return redirect(url_for("cliente_pago_nuevo", nro=nro))
        # Validar archivo
        if 'comprobante' not in request.files:
            conn.close()
            flash("Falta el comprobante (PDF/JPG/PNG).", "error")
            return redirect(url_for("cliente_pago_nuevo", nro=nro))
        content, ext, err = _validar_archivo(
            request.files['comprobante'],
            [PDF_MAGIC, JPEG_MAGIC, PNG_MAGIC],
            MAX_COMP_SIZE,
        )
        if err:
            conn.close()
            flash(f"Archivo no valido: {err}", "error")
            return redirect(url_for("cliente_pago_nuevo", nro=nro))
        # Buscar factura
        fac = conn.execute(
            "SELECT id, numero FROM facturas WHERE cliente_id = ? AND ABS(total - ?) < 0.01 ORDER BY id DESC LIMIT 1",
            (cid, row["total"]),
        ).fetchone()
        factura_id = fac["id"] if fac else None
        nro_factura = fac["numero"] if fac else nro
        # Crear pago (sin cambiar estado: lo hace el admin al confirmar)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pagos (factura_id, cliente_id, fecha, monto, metodo, referencia)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            factura_id, cid, fecha_pago, row["total"],
            forma_pago_norm, nro_factura,
        ))
        new_pago_id = cur.lastrowid
        # Guardar comprobante con el id del pago
        comp_path = _guardar_comprobante(new_pago_id, content, ext)
        conn.execute(
            "UPDATE pagos SET comprobante_path = ? WHERE id = ?",
            (comp_path, new_pago_id),
        )
        conn.commit()
        conn.close()
        flash(f"Comprobante de pago enviado. El administrador lo confirmara en breve.", "ok")
        return redirect(url_for("mi_cuenta", tab="pagos"))
    conn.close()
    # GET: mostrar form con el pedido seleccionado
    if not nro:
        flash("Selecciona un pedido facturado para pagar.", "info")
        return redirect(url_for("mi_cuenta", tab="pedidos"))
    return render_template(
        "cliente_pago_nuevo.html",
        nro=nro, total=row["total"], fmt=fmt_money,
        hoy=datetime.now().strftime("%Y-%m-%d"),
    )


@app.route("/admin/pedidos/<nro>/remito")
@admin_required
def admin_pedido_remito(nro):
    """Sirve el PDF del pedido para imprimir como remito. Sin chequeo de
    cliente_id porque el admin puede descargar cualquier pedido."""
    conn = get_db()
    row = conn.execute(
        "SELECT pdf_bytes, pdf_filename FROM pedidos WHERE nro = ?",
        (nro,),
    ).fetchone()
    conn.close()
    if not row or not row["pdf_bytes"]:
        abort(404)
    return send_file(
        io.BytesIO(row["pdf_bytes"]),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=row["pdf_filename"] or f"{nro}.pdf",
    )


@app.route("/admin/pedidos/<nro>/editar", methods=["GET", "POST"])
@admin_required
def admin_pedido_editar(nro):
    """Editar items de un pedido antes de aprobarlo. Permite cambiar
    cantidad y precio unitario de cada item. Recalcula el total.
    El pedido sigue en estado 'pendiente' (no se cambia aca)."""
    conn = get_db()
    row = conn.execute(
        "SELECT nro, cliente_nombre, items_json, total, estado, forma_pago, lugar_entrega FROM pedidos WHERE nro = ?",
        (nro,),
    ).fetchone()
    if not row:
        conn.close(); abort(404)
    if row["estado"] not in ("pendiente", "aprobado"):
        conn.close()
        flash(f"No se puede editar un pedido en estado {row['estado']}.", "error")
        return redirect(url_for("admin_pedidos"))
    items = json.loads(row["items_json"] or "[]")
    if request.method == "POST":
        # Form: cod[], desc[], cantidad[], precio_por[], unidad[]
        cods        = request.form.getlist("cod[]")
        descs       = request.form.getlist("desc[]")
        cantidades  = request.form.getlist("cantidad[]")
        precios     = request.form.getlist("precio_por[]")
        unidades    = request.form.getlist("unidad_venta[]")
        nuevos_items = []
        for i, cod in enumerate(cods):
            try:
                cant = float(cantidades[i]) if i < len(cantidades) else 0
            except ValueError:
                cant = 0
            try:
                prec = float(precios[i]) if i < len(precios) else 0
            except ValueError:
                prec = 0
            nuevos_items.append({
                "cod": (cod or "").strip(),
                "desc": (descs[i] if i < len(descs) else "").strip(),
                "precio_por": prec,
                "unidad_venta": (unidades[i] if i < len(unidades) else "unidad").strip(),
                "cantidad": cant,
                "largo_default": (items[i].get("largo_default", 12) if i < len(items) else 12),
            })
        nuevo_total = sum(it["precio_por"] * it["cantidad"] for it in nuevos_items)
        conn.execute(
            "UPDATE pedidos SET items_json = ?, total = ? WHERE nro = ?",
            (json.dumps(nuevos_items, ensure_ascii=False), round(nuevo_total, 2), nro),
        )
        conn.commit()
        conn.close()
        flash(f"Pedido {nro} actualizado. Total: ${round(nuevo_total,2):,.2f}".replace(",", "."), "ok")
        # Volver al detalle (filtro 'pendientes' o 'facturados' segun estado)
        f = "facturados" if row["estado"] == "aprobado" else "pendientes"
        return redirect(url_for("admin_pedidos", f=f) + f"#det-1")
    conn.close()
    return render_template(
        "admin_pedido_editar.html",
        nro=nro,
        cliente_nombre=row["cliente_nombre"],
        estado=row["estado"],
        items=items,
        total=row["total"],
        fmt=fmt_money,
    )


# -----------------------------------------------------------------------------
# Error handlers
# -----------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ENDPOINT TEMPORAL - SACAR EN PROXIMO CLEANUP
# -----------------------------------------------------------------------------
# V2.14 - Reset de data de prueba en prod
# 1) Backup de la DB a /home/hierronort/backups/hierronort.db.pre-reset-2026-06-14.bak
# 2) GET devuelve conteos actuales SIN TOCAR NADA
# 3) POST ejecuta el reset (borrar data de prueba en una sola transaccion)
# -----------------------------------------------------------------------------
@app.route("/admin/_reset_prueba_v1", methods=["GET", "POST"])
@admin_required
def admin_reset_prueba_v1():
    """GET: muestra conteos actuales. POST: ejecuta el reset.
    SOLO se ejecuta POST cuando Fer/Victoria den GO explicito."""
    import shutil, glob
    conn = get_db()
    counts = {
        "clientes_total": conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0],
        "clientes_no_admin": conn.execute("SELECT COUNT(*) FROM clientes WHERE is_admin = 0").fetchone()[0],
        "pedidos": conn.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0],
        "facturas": conn.execute("SELECT COUNT(*) FROM facturas").fetchone()[0],
        "pagos": conn.execute("SELECT COUNT(*) FROM pagos").fetchone()[0],
        "productos": conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0],
        "rubros": conn.execute("SELECT COUNT(*) FROM rubros").fetchone()[0],
    }
    # Archivos fisicos: listar por carpeta
    archivos = {}
    for subdir, label in [
        (os.path.join(FACTURAS_DIR, "legacy", "2026-pre"), "facturas_legacy_2026-pre"),
        (COMPROBANTES_DIR, "comprobantes"),
        (os.path.join(FACTURAS_DIR, "2026", "06"), "facturas_2026_06"),
    ]:
        if os.path.exists(subdir):
            files = [os.path.basename(f) for f in glob.glob(os.path.join(subdir, "*")) if os.path.isfile(f)]
            archivos[label] = {"path": subdir, "count": len(files), "files": files}
        else:
            archivos[label] = {"path": subdir, "count": 0, "files": []}
    conn.close()
    if request.method == "GET":
        return jsonify({"ok": True, "counts": counts, "archivos": archivos, "action": "GET (sin tocar nada)"})
    # POST: ejecutar reset en una sola transaccion
    import datetime as _dt
    log = []
    log.append(f"Reset iniciado: {_dt.datetime.now().isoformat()}")
    log.append(f"Conteos pre-reset: {counts}")
    try:
        conn = get_db()
        # 1) DELETE pagos
        n_pagos = conn.execute("SELECT COUNT(*) FROM pagos").fetchone()[0]
        conn.execute("DELETE FROM pagos")
        log.append(f"DELETE FROM pagos: {n_pagos} borrados")
        # 2) DELETE facturas
        n_fac = conn.execute("SELECT COUNT(*) FROM facturas").fetchone()[0]
        conn.execute("DELETE FROM facturas")
        log.append(f"DELETE FROM facturas: {n_fac} borradas")
        # 3) DELETE pedidos
        n_ped = conn.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]
        conn.execute("DELETE FROM pedidos")
        log.append(f"DELETE FROM pedidos: {n_ped} borrados")
        # 4) DELETE clientes no-admin
        n_cli = conn.execute("SELECT COUNT(*) FROM clientes WHERE is_admin = 0").fetchone()[0]
        conn.execute("DELETE FROM clientes WHERE is_admin = 0")
        log.append(f"DELETE FROM clientes WHERE is_admin=0: {n_cli} borrados")
        # 5) Reset auto-increment
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('clientes','facturas','pagos')")
        log.append("sqlite_sequence reseteado")
        conn.commit()
        conn.close()
    except Exception as e:
        log.append(f"ERROR en DB: {e}")
        return jsonify({"ok": False, "log": log, "error": str(e)}), 500

    # 6) Borrar archivos fisicos
    archivos_borrados = {}
    for subdir, label in [
        (os.path.join(FACTURAS_DIR, "legacy", "2026-pre"), "facturas_legacy"),
        (COMPROBANTES_DIR, "comprobantes"),
        (os.path.join(FACTURAS_DIR, "2026", "06"), "facturas_2026_06"),
    ]:
        if os.path.exists(subdir):
            files = glob.glob(os.path.join(subdir, "*"))
            count = 0
            for f in files:
                if os.path.isfile(f):
                    try:
                        os.remove(f)
                        count += 1
                    except Exception as e:
                        log.append(f"  No se pudo borrar {f}: {e}")
            archivos_borrados[label] = count
            log.append(f"Borrados {count} archivos en {subdir}")
        else:
            archivos_borrados[label] = 0

    # Conteos post-reset
    conn = get_db()
    counts_post = {
        "clientes_total": conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0],
        "clientes_no_admin": conn.execute("SELECT COUNT(*) FROM clientes WHERE is_admin = 0").fetchone()[0],
        "pedidos": conn.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0],
        "facturas": conn.execute("SELECT COUNT(*) FROM facturas").fetchone()[0],
        "pagos": conn.execute("SELECT COUNT(*) FROM pagos").fetchone()[0],
    }
    conn.close()
    log.append(f"Conteos post-reset: {counts_post}")
    return jsonify({"ok": True, "log": log, "counts_post": counts_post,
                    "archivos_borrados": archivos_borrados})


# -----------------------------------------------------------------------------
# Entry
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# MODO MANTENIMIENTO — 2026-06-16
# Toggleable desde /admin/_maintenance_on y /admin/_maintenance_off (sin auth,
# para que el bot de facturas pueda apagarlo cuando termine). Cuando esta
# prendido, todas las rutas devuelven 503 "En mantenimiento" salvo:
#   - /admin/_maintenance_* (para togglear)
#   - /static/* (CSS, imagenes — para que la pagina 503 se vea prolija)
# -----------------------------------------------------------------------------
_MAINTENANCE_MODE = False

@app.before_request
def _maintenance_gate():
    if not _MAINTENANCE_MODE:
        return None
    p = request.path or "/"
    # Permitir togglear y assets
    if p.startswith("/admin/_maintenance_") or p.startswith("/static/"):
        return None
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>En mantenimiento</title>"
        "<style>body{font-family:system-ui;background:#0f172a;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}"
        ".box{text-align:center;padding:40px;max-width:520px;}"
        "h1{color:#f87171;margin:0 0 12px;}"
        "p{color:#cbd5e1;line-height:1.5;}</style></head><body>"
        "<div class='box'><h1>🛠 En mantenimiento</h1>"
        "<p>Estamos actualizando datos. Volvé a intentar en unos minutos.</p>"
        "</div></body></html>"
    ), 503, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/admin/_maintenance_on", methods=["GET", "POST"], endpoint="_maintenance_on")
def _maintenance_on():
    global _MAINTENANCE_MODE
    _MAINTENANCE_MODE = True
    return {"ok": True, "maintenance": True}

@app.route("/admin/_maintenance_off", methods=["GET", "POST"], endpoint="_maintenance_off")
def _maintenance_off():
    global _MAINTENANCE_MODE
    _MAINTENANCE_MODE = False
    return {"ok": True, "maintenance": False}

@app.route("/admin/_maintenance_status", methods=["GET"], endpoint="_maintenance_status")
def _maintenance_status():
    return {"ok": True, "maintenance": _MAINTENANCE_MODE}

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print("Base de datos no encontrada. Ejecutá: python init_db.py")
    app.run(host="0.0.0.0", port=5000, debug=True)
