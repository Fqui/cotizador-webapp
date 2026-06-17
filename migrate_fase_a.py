"""
FASE A — Migracion v2 del modelo de datos.

Columnas nuevas: slug_grupo, slug_categoria, slug_subcategoria, configurable_en_metros, es_chapa_para_techo.
Reglas (version final confirmada con Fernando):

  1. CINCA ACAN y CINCA T101 (sin CUMB)         -> chapas-para-techo/cincalum, cm=1
  2. CUMBRERAS CINCALUM (CCA, CCT)              -> cumbreras/cumbreras-cinca-{acan,t101}, NO chapas
  3. GALVANIZADA / PREPINTADA:
       LISA  -> chapas/{galvanizada-lisa | prepintada-lisa},     cm=0
       ACAN/T101 -> chapas-para-techo/{galvanizada | prepintada}, cm=1
  4. POLICARBONATO (CH POLICARBONATO + CUMBRERAS POLICARBONATO) -> chapas-para-techo/policarbonato, cm=1, 52 variantes
  5. MALLAS JOB-SHOP                            -> alambres/mallas-job-shop, cm=0
  6. ELECTROSOLDADAS                            -> hierro-de-construccion/mallas, cm=0
  7. ACERO INOXIDABLE                           -> chapas/acero-inoxidable, cm=0
  8. MEDIANA Y ALTA RESISTENCIA                 -> alambres/mediana-y-alta-resistencia, cm=0
  9. CUMBRERAS POLICARBONATO                    -> chapas-para-techo/policarbonato, cm=1
"""
import sqlite3
import re
import unicodedata
import shutil
from datetime import datetime

DB = r"C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\hierronort.db"

# -----------------------------------------------------------------------------
# Backup
# -----------------------------------------------------------------------------
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = f"{DB}.bak.{ts}"
shutil.copy2(DB, backup_path)
print(f"[backup] {backup_path}")

# -----------------------------------------------------------------------------
# Connect
# -----------------------------------------------------------------------------
conn = sqlite3.connect(DB)
c = conn.cursor()

# 1) Add columns (idempotente)
existing = [r[1] for r in c.execute("PRAGMA table_info(productos)").fetchall()]
to_add = [
    ("slug_grupo", "TEXT"),
    ("slug_categoria", "TEXT"),
    ("slug_subcategoria", "TEXT"),
    ("configurable_en_metros", "INTEGER DEFAULT 0"),
    ("es_chapa_para_techo", "INTEGER DEFAULT 0"),
    ("largo_default", "REAL"),
]
for col, decl in to_add:
    if col not in existing:
        c.execute(f"ALTER TABLE productos ADD COLUMN {col} {decl}")
        print(f"[schema] ADD COLUMN {col} {decl}")
    else:
        print(f"[schema] {col} ya existe")

# Limpia valores previos (por si se re-ejecuta)
c.execute("""UPDATE productos SET slug_grupo=NULL, slug_categoria=NULL,
              slug_subcategoria=NULL, configurable_en_metros=0,
              es_chapa_para_techo=0, largo_default=NULL""")

# 2) Helpers de mapeo
def sg_chapa_techo(cat, sub=None, cm=1):
    """chapas-para-techo: slug_grupo=chapas-para-techo, slug_categoria=cat, slug_subcategoria=sub"""
    return ("chapas-para-techo", cat, sub, cm, 1)

def sg_chapa(cat, sub=None, cm=0):
    """chapas: slug_grupo=chapas, slug_categoria=cat, slug_subcategoria=sub"""
    return ("chapas", cat, sub, cm, 0)

# -----------------------------------------------------------------------------
# Reglas por cod / desc
# -----------------------------------------------------------------------------

def map_producto(cod, desc, rubro):
    """Devuelve (slug_grupo, slug_categoria, slug_subcategoria, configurable_en_metros, es_chapa_para_techo) o None si no matchea."""
    s = f"{cod} {desc}".upper()
    r = rubro.upper() if rubro else ""

    # --- Regla 1: CINCA ACAN y CINCA T101 (sin CUMB) -> chapas-para-techo/cincalum ---
    if r == "CINCA ACANALADA":
        return sg_chapa_techo(cat="cincalum", sub="acanalada", cm=1)
    if r == "CINCA T101":
        return sg_chapa_techo(cat="cincalum", sub="trapezoidal-t101", cm=1)

    # --- Regla 2: CUMBRERAS CINCALUM (CCA, CCT) ---
    if r == "CUMBRERAS CINCALUM":
        if "T101" in s:
            return ("cumbreras", "cumbreras-cinca-t101", None, 0, 0)
        if "ACAN" in s:
            return ("cumbreras", "cumbreras-cinca-acan", None, 0, 0)
        return ("cumbreras", "cumbreras-otros-materiales", None, 0, 0)

    # --- Regla 3: GALVANIZADAS LISAS y GALVA ACANALADA ---
    if r == "GALVANIZADAS LISAS":
        return sg_chapa(cat="galvanizada-lisa", cm=0)
    if r == "GALVA ACANALADA":
        return sg_chapa_techo(cat="galvanizada", sub="acanalada", cm=1)

    # --- Regla 3 (cont): CHAPAS PREPINTADAS ---
    if r == "CHAPAS PREPINTADAS":
        if "T101" in s or "ACAN" in s:
            sub = "trapezoidal-t101" if "T101" in s else "acanalada"
            return sg_chapa_techo(cat="prepintada", sub=sub, cm=1)
        # LISA (sin T101 ni ACAN) -> chapas/prepintada-lisa
        return sg_chapa(cat="prepintada-lisa", cm=0)

    # --- Regla 4: POLICARBONATO ---
    if r in ("CH POLICARBONATO",):
        return sg_chapa_techo(cat="policarbonato", cm=1)

    # --- Regla 5: MALLAS JOB-SHOP (aun no hay productos en DB) ---
    if r == "MALLAS JOB-SHOP":
        return ("alambres", "mallas-job-shop", None, 0, 0)

    # --- Regla 6: ELECTROSOLDADAS -> hierro-de-construccion/mallas ---
    if r == "ELECTROSOLDADAS":
        return ("hierro-de-construccion", "mallas", None, 0, 0)

    # --- Regla 7: ACERO INOXIDABLE -> chapas/acero-inoxidable ---
    if r == "ACERO INOXIDABLE":
        return sg_chapa(cat="acero-inoxidable", cm=0)

    # --- Regla 8: MEDIANA Y ALTA RESISTENCIA ---
    if r == "MEDIANA Y ALTA RESISTENCIA":
        return ("alambres", "mediana-y-alta-resistencia", None, 0, 0)

    # --- Otras chapas: estampada, decorativa, antideslizante, importada ---
    if r == "CHAPAS ESTAMPADAS":
        return sg_chapa(cat="chapa-estampada", cm=0)
    if r == "CHAPA DECORATIVA":
        return sg_chapa(cat="chapa-decorativa", cm=0)
    if r == "CHAPAS ANTIDESLIZANTES":
        return sg_chapa(cat="chapa-antideslizante", cm=0)
    if r in ("METAL DESPLEGADO",):
        return sg_chapa(cat="chapa-importada", cm=0)
    if r == "CHAPAS LAMINADAS EN CALIENTE":
        return sg_chapa(cat="chapa-importada", cm=0)

    # --- Traslucidas ---
    if r in ("TRASLUCIDA ACANALADA", "TRASLUCIDA T101"):
        return sg_chapa_techo(cat="traslucidas", cm=1)

    # --- Caños ---
    if r == "CAÑOS ESTRUCTURALES":
        # subcat: redondos / cuadrados / rectangulares
        sub = None
        if "CUADR" in s: sub = "cuadrados"
        elif "RECT" in s: sub = "rectangulares"
        elif "REDON" in s: sub = "redondos"
        return ("canos", "canos-estructurales", sub, 0, 0)
    if r == "CAÑOS MECANICOS":
        return ("canos", "canos-mecanicos", None, 0, 0)
    if r == "TUBOS SCHEDULE 40-80":
        return ("canos", "tubos-schedule-40-80", None, 0, 0)
    if r == "CAÑOS GALVANIZADOS":
        return ("canos", "canos-galvanizados", None, 0, 0)
    if r == "NEGRO BISELADO":
        return ("canos", "negro-biselado", None, 0, 0)
    if r == "CONDUIT GALVANIZADO":
        return ("canos", "conduit-galvanizado", None, 0, 0)
    if r == "CAÑOS EPOXI":
        return ("canos", "canos-epoxi", None, 0, 0)

    # --- Perfiles ---
    if r == "PERFILES C":
        sub = "perfil-c-galvanizado" if "GALV" in s else "perfil-c"
        return ("perfiles", "perfiles-c", sub, 0, 0)
    if r == "PERFILES PESADOS":
        # subcat: por tipo. Heuristica simple
        sub = "perfiles-pesados"  # placeholder, ver tabla_perfiles_tipo abajo
        return ("perfiles", "perfiles-pesados", sub, 0, 0)
    if r == "PERFILES COMERCIALES":
        return ("perfiles", "perfiles-comerciales", "perfiles-comerciales", 0, 0)

    # --- Alambres ---
    if r in ("AL.NEGRO/CORDON/TRENZA", "ALAMBRE NEGRO"):
        return ("alambres", "alambre-negro", None, 0, 0)
    if r == "ALAMBRE GALVANIZADO":
        return ("alambres", "alambre-galvanizado", None, 0, 0)
    if r == "ALAMBRE TEJIDO":
        return ("alambres", "alambre-tejido", None, 0, 0)
    if r == "BOYERO / VID":
        return ("alambres", "boyero-vid", None, 0, 0)

    # --- Varios ---
    if r in ("CLAVOS", "ELECTRODOS", "RODAMIENTOS", "ACCESORIOS P/AGRO",
             "AISLACION TERMICA", "PLACAS DE YESO", "PUA Y CONCERTINA",
             "CEMENTICIO"):
        # subcat = nombre slugified
        slug_r = re.sub(r"[^a-z0-9]+", "-", r.lower()).strip("-")
        return ("varios", slug_r, None, 0, 0)

    # --- Cumbreras otros (sin CINCALUM) ---
    if r == "CUMBRERAS GALVANIZADAS":
        return ("cumbreras", "cumbreras-otros-materiales", "galvanizada", 0, 0)
    if r == "CUMBRERAS PREPINTADAS":
        return ("cumbreras", "cumbreras-otros-materiales", "prepintada", 0, 0)

    # --- HIERRO DE CONSTRUCCION: subcat por descripcion ---
    if r == "HIERRO DE CONSTRUCCION":
        if "ADN" in s:
            return ("hierro-de-construccion", "adn", None, 0, 0)
        if "LISO" in s:
            return ("hierro-de-construccion", "hierro-liso", None, 0, 0)
        return ("hierro-de-construccion", "adn", None, 0, 0)

    return None  # no mapeado

# 3) Apply mapping
print("\n[mapeo] aplicando reglas...")
rows = c.execute("SELECT cod, descripcion, rubro FROM productos").fetchall()
mapped, unmapped = 0, []
for cod, desc, rubro in rows:
    res = map_producto(cod, desc, rubro)
    if res is None:
        unmapped.append((cod, desc, rubro))
        continue
    sg, sc, ssub, cm, ect = res
    c.execute("""
        UPDATE productos
        SET slug_grupo=?, slug_categoria=?, slug_subcategoria=?,
            configurable_en_metros=?, es_chapa_para_techo=?
        WHERE cod=?
    """, (sg, sc, ssub, cm, ect, cod))
    mapped += 1

print(f"  {mapped} productos mapeados, {len(unmapped)} sin matchear")

if unmapped:
    print("\n[unmapped] (van a 'varios' por defecto, revisar):")
    for cod, desc, rubro in unmapped[:20]:
        print(f"  {cod:25s}  {desc[:50]:50s}  [{rubro}]")
    if len(unmapped) > 20:
        print(f"  ... y {len(unmapped) - 20} mas")

# 4) POLICARBONATO: SKIP por instruccion de Victoria
# (los 2 productos base quedan mapeados a chapas-para-techo/policarbonato via map_producto)
print("\n[policarbonato] SKIP — 2 productos base quedan como chapas-para-techo/policarbonato (sin 52 variantes)")

conn.commit()
print("  commit")

# 5) Resumen
print("\n[resumen final]")
total = c.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
print(f"  total productos: {total}")
poly_count = c.execute("SELECT COUNT(*) FROM productos WHERE slug_subcategoria='policarbonato'").fetchone()[0]
print(f"  policarbonato: {poly_count}")

print("\n[por grupo/categoria]:")
for sg, sc, n in c.execute("""
    SELECT slug_grupo, slug_categoria, COUNT(*)
    FROM productos
    GROUP BY slug_grupo, slug_categoria
    ORDER BY slug_grupo, slug_categoria
""").fetchall():
    print(f"  {sg:25s} / {sc:35s}  {n}")

conn.close()
print(f"\n[done] backup: {backup_path}")
