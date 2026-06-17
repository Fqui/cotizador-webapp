// HIERRONORT — front-end helpers
// Formateo monetario estilo AR (separador de miles '.', decimales ',')

function formatMoney(n) {
  if (n == null || isNaN(n)) return '—';
  return '$' + Number(n).toFixed(2)
    .replace('.', ',')
    .replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

// =============================================================================
// Carrito — localStorage
// =============================================================================
const CARRITO_KEY = 'hn_carrito';
const DEVICE_KEY = 'hn_device_token';

function getCarrito() {
  try { return JSON.parse(localStorage.getItem(CARRITO_KEY) || '[]'); }
  catch { return []; }
}

function saveCarrito(items) {
  localStorage.setItem(CARRITO_KEY, JSON.stringify(items));
}

// Bloque A — device-binding. Si el server setea la cookie hn_device_token
// (login primer), la copiamos a localStorage. Si la cookie no esta, usamos
// la que ya esta en localStorage. Asi, en cada request mandamos el mismo token.
function syncDeviceTokenFromCookie() {
  var m = document.cookie.match(/(?:^|;\s*)hn_device_token=([^;]+)/);
  if (m && m[1]) {
    var fromCookie = decodeURIComponent(m[1]);
    var fromLS = localStorage.getItem(DEVICE_KEY) || '';
    if (fromCookie !== fromLS) {
      localStorage.setItem(DEVICE_KEY, fromCookie);
    }
  }
}
syncDeviceTokenFromCookie();

// Devuelve la unidad normalizada: 'kg' -> 'kilo' solo para variantes CSS
function getUnidad(it) {
  return it.unidad_venta || 'unidad';
}

// Factor que multiplica el precio unitario segun la unidad de venta
// Si el producto viene por metro (largo_default > 1, ej: Perfiles C 12m),
// el stepper es por unidades (1 = 1 barra = 12m) y el subtotal = unidades * 12 * precio/metro.
function factorUnidad(it) {
  const u = getUnidad(it);
  if (u === 'metro') {
    return (parseFloat(it.largo) || 0) * (parseInt(it.cantidad, 10) || 0);
  }
  if (u === 'kg') {
    return parseFloat(it.kilos) || parseInt(it.cantidad, 10) || 0;
  }
  const cant = parseInt(it.cantidad, 10) || 1;
  const largoDef = parseFloat(it.largo_default) || 0;
  if (largoDef > 1) {
    return cant * largoDef;
  }
  return cant;
}

function subtotalItem(it) {
  return (it.precio_por || 0) * factorUnidad(it);
}

// Etiqueta legible para el carrito / WhatsApp / email
function etiquetaUnidad(it) {
  const u = getUnidad(it);
  if (u === 'metro') {
    return `${(it.largo || 0).toFixed(2).replace('.', ',')} m × ${it.cantidad || 1} u`;
  }
  if (u === 'kg') {
    const k = it.kilos || it.cantidad || 0;
    return `${k.toString().replace('.', ',')} kg`;
  }
  return `${it.cantidad || 1} u`;
}

function carritoCount() {
  return getCarrito().reduce((s, i) => s + (parseInt(i.cantidad, 10) || 1), 0);
}

function agregarAlCarrito(item) {
  // item: {cod, desc, precio_por, tipo, unidad_venta, cantidad?, largo?, kilos?}
  const items = getCarrito();
  // Merge si coincide cod + misma unidad + misma medida (largo o kilos)
  const idx = items.findIndex(i =>
    i.cod === item.cod &&
    getUnidad(i) === getUnidad(item) &&
    (getUnidad(item) !== 'metro' || parseFloat(i.largo) === parseFloat(item.largo)) &&
    (getUnidad(item) !== 'kg' || parseFloat(i.kilos) === parseFloat(item.kilos))
  );
  if (idx >= 0) {
    items[idx].cantidad = (parseInt(items[idx].cantidad, 10) || 0) + (parseInt(item.cantidad, 10) || 1);
  } else {
    items.push(item);
  }
  saveCarrito(items);
  actualizarBadgeCarrito();
  mostrarToastExito(item);
}

function quitarDelCarrito(cod) {
  saveCarrito(getCarrito().filter(i => i.cod !== cod));
  actualizarBadgeCarrito();
}

function vaciarCarrito() {
  saveCarrito([]);
  actualizarBadgeCarrito();
}

function actualizarBadgeCarrito() {
  const badge = document.getElementById('cart-badge');
  if (!badge) return;
  const n = carritoCount();
  badge.textContent = n;
  badge.style.display = n > 0 ? 'flex' : 'none';
}

// Toast
let _toastTimer = null;
function _buildToastEl() {
  const el = document.createElement('div');
  el.id = 'toast';
  el.className = 'toast';
  el.setAttribute('role', 'status');
  el.setAttribute('aria-live', 'polite');
  el.innerHTML = `
    <span class="check" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
    </span>
    <div class="text"></div>
    <a class="toast-link" href="/carrito">Ver carrito →</a>
  `;
  document.body.appendChild(el);
  return el;
}

function mostrarToast(mensaje) {
  // Legacy: toast de texto simple (compatibilidad)
  let el = document.getElementById('toast');
  if (!el || !el.classList.contains('toast')) el = _buildToastEl();
  el.classList.add('toast');
  el.querySelector('.text').innerHTML = `<strong>${escapeHtml(mensaje)}</strong>`;
  el.classList.add('toast--show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.classList.remove('toast--show'); }, 3200);
}

function mostrarToastExito(item) {
  // Formato segun toast-format.md:
  //   UNIDAD: "X u de [nombre] agregada(s)"
  //   METRO:  "X m de [nombre] agregada" (cant=1) | "X m x Y u de [nombre] agregadas" (cant>1)
  //   KILO:   "X kg de [nombre] agregados"
  const el = _buildToastEl();
  const uv = getUnidad(item);
  const nombre = (item.desc || 'Producto').trim();
  const fmtN = (n, d) => Number(n).toFixed(d || 2).replace('.', ',');

  let msg = '';
  if (uv === 'metro') {
    const largo = parseFloat(item.largo) || 0;
    const cant = parseInt(item.cantidad, 10) || 1;
    if (cant === 1) {
      msg = `${fmtN(largo)} m de ${nombre} agregada`;
    } else {
      msg = `${fmtN(largo)} m x ${cant} u de ${nombre} agregadas`;
    }
  } else if (uv === 'kg') {
    const kilos = parseFloat(item.kilos) || parseFloat(item.cantidad) || 0;
    msg = `${fmtN(kilos, kilos % 1 ? 1 : 0)} kg de ${nombre} agregados`;
  } else {
    const cant = parseInt(item.cantidad, 10) || 1;
    const verbo = cant === 1 ? 'agregada' : 'agregadas';
    msg = `${cant} u de ${nombre} ${verbo}`;
  }

  el.querySelector('.text').innerHTML = `<strong>${escapeHtml(msg)}</strong>`;
  el.classList.add('toast--show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.classList.remove('toast--show'); }, 3000);
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function generarTextoCarrito(items, total, cli) {
  const fecha = new Date().toLocaleDateString('es-AR');
  const lineas = items.map(it => {
    const sub = subtotalItem(it);
    return `• ${it.cod} — ${it.desc}  (${etiquetaUnidad(it)})  =  ${formatMoney(sub)}`;
  });
  let txt = `*Cotización HIERRONORT* (${fecha})\n`;
  if (cli && cli.nombre) txt += `Cliente: ${cli.nombre}\n`;
  if (cli && cli.localidad) txt += `Localidad: ${cli.localidad}\n`;
  txt += '\n' + lineas.join('\n') + '\n\n*TOTAL: ' + formatMoney(total) + '*';
  if (cli && cli.obs) txt += `\n\nObservaciones: ${cli.obs}`;
  return txt;
}

function generarLinkWhatsApp(items, total, cli) {
  if (!CONTACTO || !CONTACTO.whatsapp) return '#';
  const txt = encodeURIComponent(generarTextoCarrito(items, total, cli || {}));
  const phone = CONTACTO.whatsapp.replace(/[^0-9]/g, '');
  return `https://wa.me/${phone}?text=${txt}`;
}

function generarLinkMail(items, total, cli) {
  const c = cli || {};
  const subject = encodeURIComponent(`Cotización HIERRONORT — ${c.nombre || 'Pedido'}`);
  const body = encodeURIComponent(generarTextoCarrito(items, total, c));
  const to = (CONTACTO && CONTACTO.email) || '';
  return `mailto:${to}?subject=${subject}&body=${body}`;
}

// Init
document.addEventListener('DOMContentLoaded', () => {
  const first = document.querySelector('.login-form input');
  if (first && !first.value) first.focus();
  actualizarBadgeCarrito();
  initGlobalSearch();
  initHamburger();
});

// =============================================================================
// Menu hamburguesa (mobile): abre/cierra el dropdown con los botones del topbar
// =============================================================================
function initHamburger() {
  const btn = document.getElementById('hamburger-btn');
  const menu = document.getElementById('topbar-actions');
  if (!btn || !menu) return;

  btn.addEventListener('click', function(e) {
    e.stopPropagation();
    const open = menu.classList.toggle('open');
    btn.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  // Cerrar al click fuera
  document.addEventListener('click', function(e) {
    if (!menu.classList.contains('open')) return;
    if (menu.contains(e.target) || btn.contains(e.target)) return;
    menu.classList.remove('open');
    btn.classList.remove('open');
    btn.setAttribute('aria-expanded', 'false');
  });

  // Cerrar al click en un link del menu (navega)
  menu.addEventListener('click', function(e) {
    if (e.target.closest('a')) {
      menu.classList.remove('open');
      btn.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
    }
  });

  // Cerrar con Escape
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && menu.classList.contains('open')) {
      menu.classList.remove('open');
      btn.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
    }
  });
}

// =============================================================================
// Buscador global del topbar
// =============================================================================
function initGlobalSearch() {
  const wrap = document.getElementById('global-search');
  const input = document.getElementById('global-q');
  const results = document.getElementById('global-results');
  if (!wrap || !input || !results) return;

  let timer = null;
  let activeIdx = -1;
  let currentRows = [];

  function close() {
    results.hidden = true;
    results.innerHTML = '';
    activeIdx = -1;
    currentRows = [];
  }
  function open() { results.hidden = false; }
  function highlight(idx) {
    const items = results.querySelectorAll('.gs-item');
    items.forEach((el, i) => el.classList.toggle('is-active', i === idx));
    activeIdx = idx;
    if (items[idx]) items[idx].scrollIntoView({ block: 'nearest' });
  }

  function render(rows) {
    currentRows = rows;
    if (!rows.length) {
      results.innerHTML = '<div class="gs-empty">Sin coincidencias. Enter para ver todos los resultados.</div>';
    } else {
      results.innerHTML = rows.map(r => {
        const uv = r.unidad_venta || 'unidad';
        const uvText = uv === 'kg' ? 'kilo' : uv;
        const per = uv === 'metro' ? '/m' : (uv === 'kg' ? '/kg' : '');
        return `
          <a class="gs-item" href="/producto/${r.cod}" data-idx="">
            <div class="gs-item-info">
              <div class="gs-item-desc">${r.desc}</div>
              <div class="gs-item-meta">
                <span class="cod-chip">${r.cod}</span>
                <span class="muted">· ${r.rubro}</span>
              </div>
            </div>
            <div class="gs-item-price">${formatMoney(r.precio_final)}<span style="font-size:10px;color:var(--muted)">${per}</span></div>
          </a>`;
      }).join('');
      results.innerHTML += '<div class="gs-foot">Enter para ver todos los resultados</div>';
      // Asignar indices
      results.querySelectorAll('.gs-item').forEach((el, i) => el.dataset.idx = i);
    }
    activeIdx = -1;
    open();
  }

  function search(q) {
    q = q.trim();
    if (q.length < 2) { close(); return; }
    fetch('/api/buscar?q=' + encodeURIComponent(q))
      .then(r => r.json())
      .then(render)
      .catch(() => close());
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => search(input.value), 200);
  });

  input.addEventListener('keydown', (e) => {
    const items = results.querySelectorAll('.gs-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (items.length) highlight(Math.min(activeIdx + 1, items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (items.length) highlight(Math.max(activeIdx - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const it = items[activeIdx];
      if (it && it.href) {
        window.location = it.href;
      } else {
        window.location = '/buscar?q=' + encodeURIComponent(input.value);
      }
    } else if (e.key === 'Escape') {
      close();
      input.blur();
    }
  });

  // Cerrar al hacer click afuera
  document.addEventListener('click', (e) => {
    if (!wrap.contains(e.target)) close();
  });
}
