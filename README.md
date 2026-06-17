# HIERRONORT â€” Webapp de Precios

App web para mostrar la lista de precios mayorista con descuentos aplicados por cliente.

## CaracterÃ­sticas

- **Login** por cliente (usuario + contraseÃ±a, hash seguro).
- **5 pantallas**: Login â†’ Rubros â†’ Lista de productos â†’ BÃºsqueda â†’ Detalle.
- **Descuentos automÃ¡ticos**:
  - CÃ³digos que empiezan con `ADN` â†’ **35% off**
  - Resto â†’ **34% off**
- **BÃºsqueda en vivo** por cÃ³digo o descripciÃ³n.
- **Panel admin** para crear/baja clientes y recargar la lista.
- **Responsive** (mobile-first, funciona en celular y desktop).

## Stack

- Python 3.10+
- Flask 3.x
- SQLite (base local)
- HTML + CSS + JS vanilla (sin frameworks)

## CÃ³mo correrlo

```bash
# 1) Instalar dependencias
pip install flask

# 2) Inicializar la base (carga data.json y crea 2 clientes por defecto)
python init_db.py

# 3) Arrancar el servidor
python app.py
```

AbrÃ­ `http://localhost:5000` en el navegador.

### Usuarios por defecto

| Usuario | ContraseÃ±a | Rol |
|---------|-----------|-----|
| `admin` | `admin123`   | Administrador (puede ver el panel admin) |
| `demo`  | `demo1234`   | Cliente normal |

## Estructura

```
hierronort-webapp/
â”œâ”€â”€ app.py              # Flask: rutas, auth, lÃ³gica de descuento
â”œâ”€â”€ init_db.py          # Crea la DB y carga los productos
â”œâ”€â”€ data.json           # Productos y rubros (entrada)
â”œâ”€â”€ hierronort.db       # Base SQLite (generada)
â”œâ”€â”€ .secret_key         # Clave de sesiÃ³n Flask (generada)
â”œâ”€â”€ static/
â”‚   â”œâ”€â”€ style.css
â”‚   â””â”€â”€ app.js
â””â”€â”€ templates/
    â”œâ”€â”€ base.html
    â”œâ”€â”€ login.html
    â”œâ”€â”€ rubros.html
    â”œâ”€â”€ productos.html
    â”œâ”€â”€ detalle.html
    â”œâ”€â”€ buscar.html
    â”œâ”€â”€ admin.html
    â””â”€â”€ 404.html
```

## Datos

- **data.json** se genera con `exportar_webapp.py` a partir del Excel limpio de la lista.
- Si te llega una lista nueva, regenerÃ¡ el JSON y corrÃ© `Recargar productos` desde el panel admin, o volvÃ© a correr `python init_db.py`.

## Reglas de orden

- Rubros agrupados en 8 grupos: HIERRO, CHAPAS, CAÃ‘OS, PERFILES, ALAMBRES, ACERO INOX, VARIOS, CUMBRERAS.
- Dentro de cada rubro, los productos se ordenan por tamaÃ±o (extraÃ­do de la descripciÃ³n):
  1. ADN: por diÃ¡metro (4, 6, 8, â€¦)
  2. Con `X` en la descripciÃ³n (CAÃ‘OS, chapas): primer nÃºmero
  3. Resto: primer nÃºmero en la descripciÃ³n

## PrÃ³ximos pasos (no incluidos en esta primera versiÃ³n)

- Subida de Excel directamente desde el admin (en vez de regenerar `data.json` a mano).
- HTTPS y hosting en la nube (Render, Railway, Fly.io, etc.).
- Reset de contraseÃ±a por mail.
- Historial de cambios de precio.
