"""Fix: popular el resto de rubros con LIKE."""
import sqlite3
DB = r"C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\hierronort.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# Canos (con Ñ)
cur.execute("UPDATE rubros SET imagen = 'canos.png' WHERE nombre LIKE 'CAÑOS%' OR nombre LIKE 'CANOS%'")
print(f"canos: {cur.rowcount} rows")

# Alambres y derivados
cur.execute("""
    UPDATE rubros SET imagen = 'alambres.png'
    WHERE nombre LIKE 'ALAMBRE%'
       OR nombre LIKE 'AL.NEGRO%'
       OR nombre LIKE 'ELECTROSOLDADAS%'
       OR nombre LIKE 'MEDIANA%'
       OR nombre LIKE 'BOYERO%'
""")
print(f"alambres: {cur.rowcount} rows")

# Chapas - todos los subrubros
cur.execute("UPDATE rubros SET imagen = 'chapas.png' WHERE nombre LIKE 'CHAPA%' OR nombre LIKE 'CHAPAS%' OR nombre LIKE 'CH %' OR nombre LIKE 'GALVANIZADAS LISAS' OR nombre LIKE 'GALVA%' OR nombre LIKE 'CINCA%' OR nombre LIKE 'TRASLUCIDA%' OR nombre LIKE 'METAL DESPLEGADO%'")
print(f"chapas: {cur.rowcount} rows")

# Perfiles
cur.execute("UPDATE rubros SET imagen = 'perfiles.png' WHERE nombre LIKE 'PERFILES%' OR nombre LIKE 'NEGRO BISELADO%' OR nombre LIKE 'TUBOS%' OR nombre LIKE 'CONDUIT%'")
print(f"perfiles: {cur.rowcount} rows")

# Cumbreras
cur.execute("UPDATE rubros SET imagen = 'cumbreras.png' WHERE nombre LIKE 'CUMBRERAS%'")
print(f"cumbreras: {cur.rowcount} rows")

# Varios - todo lo que no encaje en otra categoria
cur.execute("""
    UPDATE rubros SET imagen = 'varios.png'
    WHERE imagen IS NULL
      AND nombre NOT LIKE 'CAÑOS%' AND nombre NOT LIKE 'CANOS%'
      AND nombre NOT LIKE 'CHAPA%' AND nombre NOT LIKE 'CHAPAS%' AND nombre NOT LIKE 'CH %'
      AND nombre NOT LIKE 'GALVANIZADAS%' AND nombre NOT LIKE 'GALVA%' AND nombre NOT LIKE 'CINCA%' AND nombre NOT LIKE 'TRASLUCIDA%'
      AND nombre NOT LIKE 'METAL DESPLEGADO%'
      AND nombre NOT LIKE 'PERFILES%' AND nombre NOT LIKE 'NEGRO BISELADO%' AND nombre NOT LIKE 'TUBOS%' AND nombre NOT LIKE 'CONDUIT%'
      AND nombre NOT LIKE 'ALAMBRE%' AND nombre NOT LIKE 'AL.NEGRO%' AND nombre NOT LIKE 'ELECTROSOLDADAS%' AND nombre NOT LIKE 'MEDIANA%' AND nombre NOT LIKE 'BOYERO%'
      AND nombre NOT LIKE 'CUMBRERAS%'
      AND nombre NOT IN ('HIERRO DE CONSTRUCCION', 'ACERO INOXIDABLE')
""")
print(f"varios (resto): {cur.rowcount} rows")

conn.commit()

print("\n=== Estado final ===")
rows = cur.execute("SELECT nombre, imagen FROM rubros ORDER BY nombre").fetchall()
con_imagen = sum(1 for r in rows if r[1])
print(f"  {con_imagen}/{len(rows)} rubros con imagen")
# Agrupar por imagen
from collections import Counter
contador = Counter(r[1] or '(null)' for r in rows)
for img, n in sorted(contador.items(), key=lambda x: -x[1]):
    print(f"  {img:20s} {n} rubros")

conn.close()
