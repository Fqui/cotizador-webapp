"""
Migracion: sacar METAL DESPLEGADO y CHAPAS PERFORADAS de chapa-importada,
moverlas al grupo chapas como categorias propias.

- 9 productos CHPERF*  -> slug_categoria = 'chapas-perforadas'
- 9 productos METALD*  -> slug_categoria = 'metal-desplegado'
  (mas METALCIELO que es metal desplegado aunque no arranque con METALD)

Ya estan en unidad_venta='unidad', configurable_en_metros=0,
es_chapa_para_techo=0, slug_grupo='chapas'. Solo cambia slug_categoria.

Idempotente: si ya estan migrados, no hace nada.
"""

import sqlite3
import shutil
import sys

DB = 'hierronort.db'

# Solo los cods que hay que mover (los que se mantienen en chapa-importada
# son los 39 que NO son CHPERF ni METAL)
PERFORADAS = ["CHPERF1820", "CHPERF183", "CHPERF185", "CHPERF201010",
              "CHPERF203", "CHPERF205", "CHPERF20T", "CHPERF20TC"]
DESPLEGADO = ["METALCIELO", "METALD2701620", "METALD2703030", "METALD3003030",
              "METALD4503030", "METALD6703060", "METALD7505050", "METALD7505080",
              "METALD9003030", "METALDGRAPES"]

def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # 1. Verificar estado actual
    cur.execute("""
      SELECT slug_categoria, COUNT(*) FROM productos
      WHERE cod IN ({})
         OR cod IN ({})
      GROUP BY slug_categoria
    """.format(
        ','.join('?' * len(PERFORADAS)),
        ','.join('?' * len(DESPLEGADO))
    ), PERFORADAS + DESPLEGADO)
    print('Estado actual:')
    for r in cur.fetchall():
        print(f'  {r[0]}: {r[1]} productos')

    # 2. Mover chapas perforadas
    cur.execute("""
      UPDATE productos
      SET slug_categoria = 'chapas-perforadas'
      WHERE cod IN ({})
    """.format(','.join('?' * len(PERFORADAS))), PERFORADAS)
    perf = cur.rowcount
    print(f'  chapas-perforadas: {perf} productos actualizados')

    # 3. Mover metal desplegado
    cur.execute("""
      UPDATE productos
      SET slug_categoria = 'metal-desplegado'
      WHERE cod IN ({})
    """.format(','.join('?' * len(DESPLEGADO))), DESPLEGADO)
    despl = cur.rowcount
    print(f'  metal-desplegado:  {despl} productos actualizados')

    con.commit()

    # 4. Verificar post-migracion
    cur.execute("""
      SELECT slug_grupo, slug_categoria, COUNT(*) FROM productos
      WHERE slug_categoria IN ('chapas-perforadas', 'metal-desplegado', 'chapa-importada')
      GROUP BY slug_grupo, slug_categoria
      ORDER BY slug_categoria
    """)
    print('Estado final:')
    for r in cur.fetchall():
        print(f'  {r[0]:10s} | {r[1]:25s} | {r[2]:3d}')

    con.close()
    print(f'\nTotal movido: {perf + despl} productos')

if __name__ == '__main__':
    main()
