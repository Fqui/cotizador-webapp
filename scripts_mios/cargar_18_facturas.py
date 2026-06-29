"""
Carga 17 facturas a la DB prod. Schema de pedidos:
nro (PK TEXT), fecha_hora, cliente_id, cliente_nombre, cliente_cod, cliente_email,
cliente_telefono, cliente_direccion, items_json, total, forma_pago, lugar_entrega,
retira_nombre, retira_telefono, retira_domicilio, notas, pdf_bytes, pdf_filename,
mail_enviado, estado, nro_factura
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = "/home/hierronort/hierronort-webapp/hierronort.db"

# CUIT -> id_cliente (mapeo manual, el coder lo actualiza si hay diff)
CUIT_TO_ID = {
    "20-12330901-5": 5,   # REYES PEDRO WALDO
    "20-14298753-9": 16,  # TOLEDO RAMON OMAR (chequear)
    "20-17212018-1": 13,  # PEREZ NICOLAS FELIPE
    "20-20229661-1": 10,  # LAZOVICH JUAN
    "20-22013862-4": 14,  # QUINTERO JORGE ALBERTO
    "20-22137077-6": 34,  # PAEZ LUIS ARIEL (recien cargado)
    "20-27451261-0": 36,  # NIETO RAMON FRANCISCO (recien cargado)
    "20-35890768-8": 17,  # VEGA RAUL AGUSTIN
    "20-94112500-0": 8,   # REJAS CHAMBI MIJAEL
    "23-10224391-9": 7,   # GALDEANO PAEZ CESAR FELIX
    "23-25119283-9": 32,  # TAPIA ARIEL ALFREDO (chequear)
    "27-43791802-9": 35,  # LUNA SOFIA DANIELA (recien cargado)
    "30-67186424-3": 31,  # LAURI AGROPECUARIA SA
    "30-71072403-9": 4,   # IMPREGNADORA RIOJANA SRL
    "30-71575674-5": 39,  # LA POCITANA SRL (recien cargado)
    "30-62357331-8": None,  # HIERRONORT (no es cliente)
}

# 17 facturas a cargar
FACTURAS = [
    {
        "nro_factura": "0064-00000018-B", "fecha": "2026-06-23", "cuit": "27-43791802-9",
        "items": [
            {"cod": "ADN8", "cantidad": 60, "precio_unitario": 8806.36, "importe": 528381.60},
            {"cod": "ADN4", "cantidad": 40, "precio_unitario": 2669.01, "importe": 106760.40},
            {"cod": "SEGUR010", "cantidad": 1, "precio_unitario": 13900.53, "importe": 13900.53},
        ],
        "peso_kg": 322.0, "cae": "86250876376506",
        "subtotal": 526067.13, "iva": 111475.00, "total": 637542.13,
    },
    {
        "nro_factura": "0064-00000019-B", "fecha": "2026-06-24", "cuit": "20-27451261-0",
        "items": [
            {"cod": "PC10050152", "cantidad": 24, "precio_unitario": 7023.81, "importe": 168571.44},
            {"cod": "SEGUR010", "cantidad": 1, "precio_unitario": 13900.53, "importe": 13900.53},
        ],
        "peso_kg": 82.6, "cae": "86250977625784",
        "subtotal": 168550.04, "iva": 35395.41, "total": 203945.45,
    },
    {
        "nro_factura": "0064-00000050-A", "fecha": "2026-06-25", "cuit": "30-71575674-5",
        "items": [
            {"cod": "LANACA501212", "cantidad": 45, "precio_unitario": 93078.74, "importe": 4188543.50},
        ],
        "peso_kg": 45.0, "cae": "86261091530072",
        "subtotal": 4188543.50, "iva": 879594.13, "total": 5068137.63,
    },
    {
        "nro_factura": "0064-00000052-A", "fecha": "2026-06-25", "cuit": "20-12330901-5",
        "items": [
            {"cod": "PC8050152", "cantidad": 48, "precio_unitario": 6019.21, "importe": 288922.08},
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 26910.84, "importe": 26910.84},
        ],
        "peso_kg": 624.0, "cae": "86261116301202",
        "subtotal": 1315421.09, "iva": 276649.43, "total": 1592070.52,
    },
    {
        "nro_factura": "0064-00000054-A", "fecha": "2026-06-25", "cuit": "20-12330901-5",
        "items": [
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 27893.55, "importe": 27893.55},
            {"cod": "TORAR2", "cantidad": 1500, "precio_unitario": 100.26, "importe": 150390.00},
            {"cod": "TORAR1", "cantidad": 250, "precio_unitario": 94.79, "importe": 23697.50},
            {"cod": "PC80501516", "cantidad": 60, "precio_unitario": 5475.75, "importe": 328545.00},
        ],
        "peso_kg": 324.8, "cae": "86261121805515",
        "subtotal": 530526.25, "iva": 111411.51, "total": 641937.76,
    },
    {
        "nro_factura": "0064-00000057-A", "fecha": "2026-06-26", "cuit": "20-30149015-2",
        "items": [
            {"cod": "PL3418", "cantidad": 2, "precio_unitario": 5915.04, "importe": 11830.08},
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 28830.84, "importe": 28830.84},
            {"cod": "ESC303012", "cantidad": 5, "precio_unitario": 15637.04, "importe": 78185.20},
            {"cod": "ESC252512", "cantidad": 10, "precio_unitario": 12929.41, "importe": 129294.10},
            {"cod": "ESC202012", "cantidad": 20, "precio_unitario": 10379.37, "importe": 207587.40},
        ],
        "peso_kg": 190.83, "cae": "86261262412287",
        "subtotal": 455727.66, "iva": 95702.31, "total": 551429.97,
    },
    {
        "nro_factura": "0064-00000058-A", "fecha": "2026-06-26", "cuit": "20-22137077-6",
        "items": [
            {"cod": "TORAR2", "cantidad": 1000, "precio_unitario": 97.81, "importe": 97810.00},
            {"cod": "EST305012", "cantidad": 5, "precio_unitario": 20939.81, "importe": 104699.05},
            {"cod": "ESC202012", "cantidad": 5, "precio_unitario": 10379.37, "importe": 51896.85},
            {"cod": "ESC303012", "cantidad": 5, "precio_unitario": 15637.04, "importe": 78185.20},
            {"cod": "AN1218", "cantidad": 5, "precio_unitario": 7279.69, "importe": 36398.45},
            {"cod": "PL118", "cantidad": 5, "precio_unitario": 7914.18, "importe": 39570.90},
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 29298.13, "importe": 29298.13},
            {"cod": "ADN16", "cantidad": 10, "precio_unitario": 28341.50, "importe": 283415.00},
            {"cod": "PC80401516", "cantidad": 48, "precio_unitario": 4786.13, "importe": 229734.24},
        ],
        "peso_kg": 1033.65, "cae": "86261303445315",
        "subtotal": 2000685.55, "iva": 420133.97, "total": 2420819.52,
    },
    {
        "nro_factura": "0064-00000059-A", "fecha": "2026-06-26", "cuit": "23-10224391-9",
        "items": [
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 29298.13, "importe": 29298.13},
            {"cod": "EST408016", "cantidad": 5, "precio_unitario": 40620.93, "importe": 203104.65},
            {"cod": "EST206016", "cantidad": 5, "precio_unitario": 26489.55, "importe": 132447.75},
            {"cod": "EST205016", "cantidad": 5, "precio_unitario": 23013.22, "importe": 115066.10},
            {"cod": "EST204016", "cantidad": 5, "precio_unitario": 19586.97, "importe": 97934.85},
            {"cod": "ESC707016", "cantidad": 3, "precio_unitario": 47845.32, "importe": 143535.96},
            {"cod": "ESC606016", "cantidad": 3, "precio_unitario": 40666.10, "importe": 121998.30},
            {"cod": "ESC505016", "cantidad": 3, "precio_unitario": 33687.55, "importe": 101062.65},
            {"cod": "ESC404016", "cantidad": 5, "precio_unitario": 26738.32, "importe": 133691.60},
            {"cod": "ESC303016", "cantidad": 5, "precio_unitario": 19766.69, "importe": 98833.45},
        ],
        "peso_kg": 756.05, "cae": "86261314454460",
        "subtotal": 1733060.66, "iva": 363951.74, "total": 2097012.40,
    },
    {
        "nro_factura": "0064-00000060-A", "fecha": "2026-06-26", "cuit": "23-10224391-9",
        "items": [
            {"cod": "AN13418", "cantidad": 5, "precio_unitario": 25289.66, "importe": 126448.30},
            {"cod": "CERR014", "cantidad": 50, "precio_unitario": 7148.26, "importe": 357413.00},
            {"cod": "CERR008", "cantidad": 50, "precio_unitario": 5857.52, "importe": 292876.00},
            {"cod": "ELECTCO32PA", "cantidad": 10, "precio_unitario": 8710.99, "importe": 87109.90},
            {"cod": "ELECTCO2PA", "cantidad": 10, "precio_unitario": 12888.69, "importe": 128886.90},
            {"cod": "ELECTCO25PA", "cantidad": 20, "precio_unitario": 9000.27, "importe": 180005.40},
            {"cod": "GUIAPC4", "cantidad": 2, "precio_unitario": 61446.97, "importe": 122893.94},
            {"cod": "CARROPG4", "cantidad": 6, "precio_unitario": 10092.21, "importe": 60553.26},
            {"cod": "PL118", "cantidad": 10, "precio_unitario": 7914.18, "importe": 79141.80},
            {"cod": "PL3418", "cantidad": 8, "precio_unitario": 5915.04, "importe": 47320.32},
        ],
        "peso_kg": 1154.56, "cae": "86261315072182",
        "subtotal": 2495597.83, "iva": 524074.55, "total": 3019672.38,
    },
    {
        "nro_factura": "0064-00000061-A", "fecha": "2026-06-26", "cuit": "23-10224391-9",
        "items": [
            {"cod": "METALD2701620", "cantidad": 3, "precio_unitario": 37390.37, "importe": 112171.11},
        ],
        "peso_kg": 51.0, "cae": "86261315363631",
        "subtotal": 112171.11, "iva": 23555.93, "total": 135727.04,
    },
    {
        "nro_factura": "0064-00000064-A", "fecha": "2026-06-27", "cuit": "20-22013862-4",
        "items": [
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 29298.13, "importe": 29298.13},
            {"cod": "ESC202012", "cantidad": 20, "precio_unitario": 10379.37, "importe": 207587.40},
            {"cod": "ESC303012", "cantidad": 10, "precio_unitario": 15637.04, "importe": 156370.40},
            {"cod": "EST306016", "cantidad": 6, "precio_unitario": 29943.85, "importe": 179663.10},
            {"cod": "AN112316", "cantidad": 6, "precio_unitario": 30583.59, "importe": 183501.54},
        ],
        "peso_kg": 342.36, "cae": "86261388694703",
        "subtotal": 756420.57, "iva": 158847.32, "total": 915267.89,
    },
    {
        "nro_factura": "0064-00000065-A", "fecha": "2026-06-27", "cuit": "20-35890768-8",
        "items": [
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 29298.13, "importe": 29298.13},
            {"cod": "ADN16", "cantidad": 1, "precio_unitario": 28341.50, "importe": 28341.50},
            {"cod": "PC80401516", "cantidad": 36, "precio_unitario": 4861.20, "importe": 175003.20},
            {"cod": "ADN4", "cantidad": 100, "precio_unitario": 1799.42, "importe": 179942.00},
            {"cod": "MALLAQ131", "cantidad": 10, "precio_unitario": 56580.21, "importe": 565802.10},
            {"cod": "ALN14", "cantidad": 100, "precio_unitario": 2490.74, "importe": 249074.00},
            {"cod": "ESC202016", "cantidad": 15, "precio_unitario": 13013.62, "importe": 195204.30},
            {"cod": "EST204016", "cantidad": 15, "precio_unitario": 19886.81, "importe": 298302.15},
            {"cod": "EST406016", "cantidad": 12, "precio_unitario": 33885.62, "importe": 406627.44},
            {"cod": "ESC252512", "cantidad": 15, "precio_unitario": 13128.17, "importe": 196922.55},
        ],
        "peso_kg": 1250.93, "cae": "86261389021017",
        "subtotal": 2748333.34, "iva": 577151.00, "total": 3325484.34,
    },
    {
        "nro_factura": "0064-00000066-A", "fecha": "2026-06-27", "cuit": "20-14752558-4",
        "items": [
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 28990.10, "importe": 28990.10},
            {"cod": "PINTXT72", "cantidad": 2, "precio_unitario": 28371.07, "importe": 56742.14},
            {"cod": "CHCT10127250", "cantidad": 1, "precio_unitario": 24663.64, "importe": 24663.64},
            {"cod": "PL3418", "cantidad": 3, "precio_unitario": 6304.21, "importe": 18912.63},
            {"cod": "EST204012", "cantidad": 2, "precio_unitario": 16494.21, "importe": 32988.42},
            {"cod": "ESC303012", "cantidad": 3, "precio_unitario": 16663.34, "importe": 49990.02},
            {"cod": "ESC404016", "cantidad": 1, "precio_unitario": 28493.16, "importe": 28493.16},
            {"cod": "ESC404012", "cantidad": 3, "precio_unitario": 22461.45, "importe": 67384.35},
            {"cod": "CHGALL2748", "cantidad": 2, "precio_unitario": 24244.62, "importe": 48489.24},
            {"cod": "CHNF2012", "cantidad": 11, "precio_unitario": 30308.04, "importe": 333388.44},
        ],
        "peso_kg": 391.42, "cae": "86261391474764",
        "subtotal": 953773.18, "iva": 200292.37, "total": 1154065.55,
    },
    {
        "nro_factura": "0065-00000023-A", "fecha": "2026-06-25", "cuit": "20-12330901-5",
        "items": [
            {"cod": "CHCT10125450", "cantidad": 18, "precio_unitario": 50248.45, "importe": 904472.10},
            {"cod": "CHCT10125800", "cantidad": 8, "precio_unitario": 89328.69, "importe": 714629.52},
        ],
        "peso_kg": 719.2, "cae": "86261123001326",
        "subtotal": 1619155.07, "iva": 340012.56, "total": 1959167.63,
    },
    {
        "nro_factura": "0065-00000026-A", "fecha": "2026-06-26", "cuit": "20-22137077-6",
        "items": [
            {"cod": "M152525", "cantidad": 30, "precio_unitario": 18900.30, "importe": 567009.00},
            {"cod": "ALN17", "cantidad": 100, "precio_unitario": 2535.39, "importe": 253539.00},
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 29298.13, "importe": 29298.13},
        ],
        "peso_kg": 1018.9, "cae": "86261303445315",
        "subtotal": 2214191.50, "iva": 464980.22, "total": 2679171.72,
    },
    {
        "nro_factura": "0065-00000027-A", "fecha": "2026-06-26", "cuit": "23-10224391-9",
        "items": [
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 29298.13, "importe": 29298.13},
            {"cod": "EST408016", "cantidad": 5, "precio_unitario": 40620.93, "importe": 203104.65},
            {"cod": "ESC606016", "cantidad": 3, "precio_unitario": 40666.10, "importe": 121998.30},
            {"cod": "ADN6", "cantidad": 50, "precio_unitario": 4107.83, "importe": 205391.50},
            {"cod": "ALN17", "cantidad": 100, "precio_unitario": 2535.39, "importe": 253539.00},
            {"cod": "SEGUR010", "cantidad": 1, "precio_unitario": 13900.53, "importe": 13900.53},
        ],
        "peso_kg": 306.0, "cae": "86261315363631",
        "subtotal": 583886.76, "iva": 122615.22, "total": 706501.98,
    },
    {
        "nro_factura": "0065-00000029-A", "fecha": "2026-06-27", "cuit": "20-22013862-4",
        "items": [
            {"cod": "EST408016", "cantidad": 12, "precio_unitario": 40620.93, "importe": 487451.16},
            {"cod": "SEGUR011", "cantidad": 1, "precio_unitario": 29298.13, "importe": 29298.13},
        ],
        "peso_kg": 438.0, "cae": "86261388694703",
        "subtotal": 740813.76, "iva": 154570.89, "total": 895384.65,
    },
]


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Backup
    backup = f"/home/hierronort/backups/hierronort.db.pre-18-facturas-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    cur.execute(f"VACUUM INTO '{backup}'")
    print(f"Backup: {backup}")

    for f in FACTURAS:
        # Buscar cliente_id
        cuit = f["cuit"]
        cur.execute("SELECT id FROM clientes WHERE cuit = ?", (cuit,))
        row = cur.fetchone()
        if not row:
            print(f"ERROR: cliente con cuit {cuit} no existe")
            continue
        cliente_id = row[0]

        # Verificar que no exista ya
        cur.execute("SELECT id FROM pedidos WHERE nro_factura = ?", (f["nro_factura"],))
        if cur.fetchone():
            print(f"SKIP: {f['nro_factura']} ya existe")
            continue

        # Sacar datos del cliente
        cur.execute("SELECT nombre, cod_cliente, email, telefono, direccion FROM clientes WHERE id = ?", (cliente_id,))
        cli = cur.fetchone()
        cli_nombre = cli[0] or ""
        cli_cod = cli[1] or ""
        cli_email = cli[2] or ""
        cli_tel = cli[3] or ""
        cli_dir = cli[4] or ""

        items_json = json.dumps(f["items"])

        cur.execute("""
            INSERT INTO pedidos (
                nro, fecha_hora, cliente_id, cliente_nombre, cliente_cod,
                cliente_email, cliente_telefono, cliente_direccion,
                items_json, total, forma_pago, lugar_entrega,
                retira_nombre, retira_telefono, retira_domicilio,
                notas, mail_enviado, estado, nro_factura
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f["nro_factura"], f["fecha"] + " 00:00:00", cliente_id, cli_nombre, cli_cod,
            cli_email, cli_tel, cli_dir,
            items_json, f["total"], "efectivo", "entrega_domicilio",
            "", "", "",
            f"CAE: {f.get('cae', '')} | PESO: {f['peso_kg']} kg", 0, "aprobado", f["nro_factura"]
        ))
        pedido_id = cur.lastrowid
        print(f"OK: {f['nro_factura']} -> id={pedido_id}, total={f['total']}")

    conn.commit()
    conn.close()
    print("\nListo. DB commiteada.")


if __name__ == "__main__":
    main()