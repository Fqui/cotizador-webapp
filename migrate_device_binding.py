"""
Bloque A - Migracion device-binding.
- Backup automatico de la DB
- ALTER TABLE: agregar 4 columnas para device-binding
- DELETE: borrar los 5 clientes demo (deja admin + demo)
- UPDATE: resetear password_temporal en los 2 que quedan
- Verificacion final

Riesgo: bajo. Solo DB, no toca codigo.
"""
import shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path(r'C:\Users\Usuario\.mavis\agents\coder\workspace\hierronort-webapp\hierronort.db')
DEMO_USUARIOS = ['corralon', 'hiersur', 'matplat', 'acerbona', 'constructor']
KEEP_USUARIOS = ['admin', 'demo']

def backup_db():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = DB_PATH.with_suffix(f'.db.bak.{ts}')
    shutil.copy2(DB_PATH, backup)
    print(f'[BACKUP] {backup}')
    return backup

def main():
    if not DB_PATH.exists():
        print(f'[ERROR] No existe {DB_PATH}')
        sys.exit(1)

    print(f'[INFO] DB target: {DB_PATH}')
    print(f'[INFO] Demo a borrar: {DEMO_USUARIOS}')
    print(f'[INFO] A mantener: {KEEP_USUARIOS}')
    print()

    backup_db()
    print()

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    print('[1/4] ALTER TABLE - agregar columnas device')
    cols_to_add = [
        ('device_token', 'TEXT'),
        ('device_first_login', 'TEXT'),
        ('device_last_login', 'TEXT'),
        ('device_label', 'TEXT'),
    ]
    for col_name, col_type in cols_to_add:
        try:
            cur.execute(f'ALTER TABLE clientes ADD COLUMN {col_name} {col_type}')
            print(f'  + {col_name} {col_type}')
        except sqlite3.OperationalError as e:
            if 'duplicate column' in str(e).lower():
                print(f'  ~ {col_name} ya existe, skip')
            else:
                raise
    conn.commit()
    print()

    print('[2/4] DELETE - borrar 5 clientes demo')
    placeholders = ','.join('?' * len(DEMO_USUARIOS))
    cur.execute(f'SELECT id, usuario, nombre FROM clientes WHERE usuario IN ({placeholders})', DEMO_USUARIOS)
    to_delete = cur.fetchall()
    print(f'  A borrar ({len(to_delete)} filas):')
    for row in to_delete:
        print(f'    id={row[0]} usuario={row[1]} nombre={row[2]}')
    cur.execute(f'DELETE FROM clientes WHERE usuario IN ({placeholders})', DEMO_USUARIOS)
    conn.commit()
    print(f'  Borradas: {cur.rowcount} filas')
    print()

    print('[3/4] UPDATE - reset password_temporal en admin y demo')
    placeholders = ','.join('?' * len(KEEP_USUARIOS))
    cur.execute(f'SELECT id, usuario, password_temporal FROM clientes WHERE usuario IN ({placeholders})', KEEP_USUARIOS)
    for row in cur.fetchall():
        print(f'  id={row[0]} usuario={row[1]} password_temporal={row[2]} -> 0')
    cur.execute(f'UPDATE clientes SET password_temporal = 0 WHERE usuario IN ({placeholders})', KEEP_USUARIOS)
    conn.commit()
    print(f'  Actualizadas: {cur.rowcount} filas')
    print()

    print('[4/4] Verificacion final')
    cur.execute('SELECT id, cod_cliente, usuario, nombre, activo, is_admin, password_temporal, device_token, device_label FROM clientes ORDER BY id')
    rows = cur.fetchall()
    print(f'  Total clientes: {len(rows)}')
    for row in rows:
        print(f'    id={row[0]} cod={row[1] or "-"} usuario={row[2]} nombre={row[3]} activo={row[4]} admin={row[5]} pwd_tmp={row[6]} device_token={row[7] or "NULL"} device_label={row[8] or "NULL"}')
    print()

    print('[5/4] Verificacion schema')
    cur.execute('PRAGMA table_info(clientes)')
    cols = [r[1] for r in cur.fetchall()]
    print(f'  Total columnas: {len(cols)}')
    new_cols = ['device_token', 'device_first_login', 'device_last_login', 'device_label']
    for nc in new_cols:
        present = '[OK]' if nc in cols else '[FALTA]'
        print(f'    {present} {nc}')

    conn.close()
    print()
    print('[OK] Bloque A completo')

if __name__ == '__main__':
    main()
