"""
Carga de 10 facturas de junio 2026 a la DB prod.
Ejecutar: python cargar_10_facturas.py
"""
import sqlite3
import os
import json
from datetime import datetime

# Configuracion
DB_PATH = "/home/hierronort/hierronort-webapp/hierronort.db"
VENDEDOR_ID = 1  # Quintero Pedraza Fernando
FACTURAS = [
    # (nro_completo, fecha, cliente_cuit, cliente_cod, items, condicion, lugar, peso)
    {
        "nro_completo": "0064-00000035-A",
        "pv": "0064", "nc": "00000035", "letra": "A",
        "fecha": "2026-06-18",
        "cliente_cuit": "23-10224391-9",
        "cliente_cod": "0259766",
        "items": [
            ("SEGUR011", 1, 28617.7248),
            ("RUEDA60CS", 10, 9373.9594),
            ("RUEDA50CS", 10, 8229.7712),
            ("ADN8", 100, 6884.8566),
            ("ADN6", 100, 4055.1527),
            ("ESC606016", 5, 39642.4245),
            ("ESC252516", 10, 15880.9152),
            ("ESC202016", 10, 12493.5732),
            ("ESC404012", 5, 20544.0093),
            ("ESC303012", 10, 15243.0392),
            ("ESC252512", 20, 12603.5518),
            ("ESC202012", 30, 10118.0345),
            ("AN11218", 10, 20062.8250),
            ("AN11418", 10, 17420.1412),
            ("AN118", 10, 13483.0813),
        ],
        "subtotal": 3101035.96,
        "iva_21": 651217.55,
        "total": 3752253.51,
        "condicion_venta": "Cta. Cte. - Cheques o Deposito a 48 hs F.F.",
        "lugar_entrega": "entrega_domicilio",
        "peso_kg": 1621.0,
        "cae": "86250217871655",
    },
    {
        "nro_completo": "0065-00000021-A",
        "pv": "0065", "nc": "00000021", "letra": "A",
        "fecha": "2026-06-18",
        "cliente_cuit": "23-10224391-9",
        "cliente_cod": "0259766",
        "items": [
            ("CHNC12122244", 1, 95483.4279),
            ("CHNC14122244", 1, 78581.5636),
            ("CHNF18122244", 3, 54483.1904),
            ("CHNF20122244", 3, 40032.7871),
            ("CHNF1612", 2, 48516.2026),
            ("CHNF1812", 3, 37903.2832),
            ("CHNF2012", 3, 27724.1702),
        ],
        "subtotal": 751527.69,
        "iva_21": 157820.81,
        "total": 909348.50,
        "condicion_venta": "Cta. Cte. - Cheques o Deposito a 48 hs F.F.",
        "lugar_entrega": "entrega_domicilio",
        "peso_kg": 417.1,
        "cae": "86250218899595",
    },
    {
        "nro_completo": "0064-00000039-A",
        "pv": "0064", "nc": "00000039", "letra": "A",
        "fecha": "2026-06-19",
        "cliente_cuit": "23-10224391-9",
        "cliente_cod": "0259766",
        "items": [
            ("EST205016", 5, 22433.9090),
            ("EST408016", 5, 39598.4262),
            ("ESC505016", 3, 32839.6211),
            ("ESR13812", 5, 14287.8285),
            ("ESR11412", 5, 12779.5176),
            ("ESR112", 10, 10100.5425),
            ("ESC303012", 10, 15243.0392),
            ("EST102012", 10, 7525.6712),
            ("ESC151512", 10, 7436.8728),
            ("ESC101012", 10, 6180.3123),
            ("CARROPG3", 10, 7719.9689),
            ("GUIAPC3", 4, 31556.7856),
            ("ADN10", 30, 10725.8817),
            ("PC80401516", 60, 4666.0761),
            ("PLP1316R12", 5, 13035.1053),
            ("PLP1316R10", 5, 13035.1053),
            ("AN112316", 5, 29830.1657),
            ("AN218", 5, 28943.6812),
            ("EST204016", 20, 19092.2914),
        ],
        "subtotal": 2620115.62,
        "iva_21": 550224.28,
        "total": 3170339.90,
        "condicion_venta": "Cta. Cte. - Cheques o Deposito a 48 hs F.F.",
        "lugar_entrega": "entrega_domicilio",
        "peso_kg": 1258.89,
        "cae": "86250351451968",
    },
    {
        "nro_completo": "0065-00000022-A",
        "pv": "0065", "nc": "00000022", "letra": "A",
        "fecha": "2026-06-19",
        "cliente_cuit": "23-10224391-9",
        "cliente_cod": "0259766",
        "items": [
            ("CHNF1812", 3, 37903.2832),
            ("CHGALL2548", 5, 25577.5047),
            ("CHGALL2748", 5, 22176.9874),
        ],
        "subtotal": 352482.31,
        "iva_21": 74021.29,
        "total": 426503.60,
        "condicion_venta": "Cta. Cte. - Cheques o Deposito a 48 hs F.F.",
        "lugar_entrega": "entrega_domicilio",
        "peso_kg": 170.8,
        "cae": "86250351795745",
    },
    {
        "nro_completo": "0064-00000041-A",
        "pv": "0064", "nc": "00000041", "letra": "A",
        "fecha": "2026-06-19",
        "cliente_cuit": "20-22013862-4",
        "cliente_cod": "70020",
        "items": [
            ("SEGUR011", 1, 28617.7248),
            ("ADN8", 50, 6992.4325),
            ("ADN6", 50, 4118.5145),
            ("ESC202012", 20, 10273.6966),
            ("ESR5816", 10, 8617.3406),
            ("EST306016", 10, 29637.3814),
            ("EST40602", 6, 37401.9100),
            ("ALN17", 100, 2517.6364),
        ],
        "subtotal": 1648361.33,
        "iva_21": 346155.88,
        "total": 1994517.21,
        "condicion_venta": "Cta. Cte. - Cheques o Deposito a 48 hs F.F.",
        "lugar_entrega": "entrega_domicilio",
        "peso_kg": 843.3,
        "cae": "86250411377441",
    },
    {
        "nro_completo": "0064-00000042-A",
        "pv": "0064", "nc": "00000042", "letra": "A",
        "fecha": "2026-06-22",
        "cliente_cuit": "20-22013862-4",
        "cliente_cod": "70020",
        "items": [
            ("EST304012", 10, 17966.7285),
        ],
        "subtotal": 179667.29,
        "iva_21": 37730.13,
        "total": 217397.42,
        "condicion_venta": "Cta. Cte. - Cheques o Deposito a 48 hs F.F.",
        "lugar_entrega": "entrega_domicilio",
        "peso_kg": 80.6,
        "cae": "86250677461862",
    },
    {
        "nro_completo": "0064-00000015-B",
        "pv": "0064", "nc": "00000015", "letra": "B",
        "fecha": "2026-06-22",
        "cliente_cuit": "20-94112500-0",
        "cliente_cod": "0258420",
        "items": [
            ("CHNF2012", 2, 34519.9483),
            ("CHCA25450", 5, 59498.5431),
            ("M152525", 10, 20016.5098),
            ("ALN16", 30, 2974.1910),
            ("SEGUR011", 1, 35098.5687),
            ("EST203012", 15, 15528.6238),
        ],
        "subtotal": 763596.17,
        "iva_21": 160355.20,
        "total": 923951.37,
        "condicion_venta": "Cta. Cte. - Cheques o Deposito a 48 hs F.F.",
        "lugar_entrega": "entrega_domicilio",
        "peso_kg": 350.95,
        "cae": "86250737953187",
    },
    {
        "nro_completo": "0064-00000045-A",
        "pv": "0064", "nc": "00000045", "letra": "A",
        "fecha": "2026-06-22",
        "cliente_cuit": "30-67186424-3",
        "cliente_cod": "0366213",
        "items": [
            ("SEGUR011", 1, 29007.0816),
            ("M1525R8423", 140, 11686.8593),
            ("AN1316", 100, 21565.6087),
        ],
        "subtotal": 3821728.25,
        "iva_21": 802562.93,
        "total": 4624291.18,
        "condicion_venta": "Cta. Cte. - Cheques o Deposito a 48 hs F.F.",
        "lugar_entrega": "entrega_domicilio",
        "peso_kg": 1831.4,
        "cae": "86250743714947",
    },
    {
        "nro_completo": "0064-00000037-A",
        "pv": "0064", "nc": "00000037", "letra": "A",
        "fecha": "2026-06-19",
        "cliente_cuit": "23-25119283-9",
        "cliente_cod": "95090",
        "items": [
            ("SEGUR011", 1, 29026.5494),
            ("BISTORN25100", 16, 4116.2712),
            ("PL118", 2, 8313.1681),
            ("ESC151516", 4, 10041.0589),
            ("EST408016", 12, 42644.4590),
            ("EST20402", 2, 24272.9511),
            ("EST208016", 6, 36384.3172),
        ],
        "subtotal": 930262.77,
        "iva_21": 195355.18,
        "total": 1125617.96,
        "condicion_venta": "Cta. Cte. - Cheques o Deposito a 48 hs F.F.",
        "lugar_entrega": "entrega_domicilio",
        "peso_kg": 372.7,
        "cae": "86250337609160",
    },
    {
        "nro_completo": "0064-00000043-A",
        "pv": "0064", "nc": "00000043", "letra": "A",
        "fecha": "2026-06-22",
        "cliente_cuit": "20-14752558-4",
        "cliente_cod": "18806",
        "items": [
            ("CHCT10127300", 2, 28410.9828),
            ("EST307012", 2, 26874.0003),
            ("ESC151512", 2, 7806.0506),
            ("SEGUR011", 1, 27892.7560),
        ],
        "subtotal": 154074.82,
        "iva_21": 32355.71,
        "total": 186430.54,  # segun el PDF del presupuesto
        "condicion_venta": "Cta. Cte. - Cheques o Deposito a 48 hs F.F.",
        "lugar_entrega": "entrega_domicilio",
        "peso_kg": 54.98,
        "cae": "09156660",
    },
]


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Backup
    backup = f"/home/hierronort/backups/hierronort.db.pre-10-facturas-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    cur.execute(f"VACUUM INTO '{backup}'")
    print(f"Backup: {backup}")

    for f in FACTURAS:
        # Buscar cliente_id
        cur.execute("SELECT id, descuentos_por_categoria FROM clientes WHERE cuit = ?", (f["cliente_cuit"],))
        row = cur.fetchone()
        if not row:
            print(f"ERROR: cliente {f['cliente_cuit']} no existe")
            continue
        cliente_id = row[0]

        # Verificar que no exista ya
        nro = f"{f['pv']}-{f['nc']}-{f['letra']}"
        cur.execute("SELECT id FROM pedidos WHERE numero = ?", (nro,))
        if cur.fetchone():
            print(f"SKIP: {nro} ya existe")
            continue

        # Insertar pedido
        items_json = json.dumps([
            {"cod": c, "cantidad": cant, "precio_unitario": pu, "importe": cant * pu}
            for c, cant, pu in f["items"]
        ])

        cur.execute("""
            INSERT INTO pedidos (
                numero, fecha_hora, cliente_id, vendedor_id, items_json,
                subtotal, iva, total, condicion_venta, lugar_entrega,
                peso_kg, estado, saldo_pendiente, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (
            nro, f"{f['fecha']} 00:00:00", cliente_id, VENDEDOR_ID, items_json,
            f["subtotal"], f["iva_21"], f["total"],
            f["condicion_venta"], f["lugar_entrega"],
            f["peso_kg"], "aprobado", 0.0
        ))
        pedido_id = cur.lastrowid
        print(f"OK: {nro} -> id={pedido_id}, total={f['total']}")

    conn.commit()
    conn.close()
    print("\nListo. DB commiteada.")


if __name__ == "__main__":
    main()