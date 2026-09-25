# Desk Dashboard (CEO X)

Dashboard técnico interno MVP. **Sin paywall, sin login.** Branding original (no Warren Bife / Warren Score).

Ruta del proyecto: `/workspace/desk-dashboard/`

## Cómo refrescar

```bash
cd /workspace/desk-dashboard
python3 build.py
```

Luego abrí `index.html` (servidor estático o file://). Si usás file:// y el navegador bloquea `fetch`, serví la carpeta:

```bash
cd /workspace/desk-dashboard && python3 -m http.server 8765
# http://127.0.0.1:8765/
```

Requisitos de entorno:

- Alpaca: `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` (también acepta los nombres del SDK `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY`). Si faltan, `build.py` corta con un error claro (sin mostrar valores).
- Opcionales Alpaca: `ALPACA_DATA_URL` (default `https://data.alpaca.markets`) y `ALPACA_FEED` (default `iex`; `sip` requiere plan pago).
- Finnhub: `FINNHUB_API_KEY` en el entorno; fallback local `.finnhub_env` (proyecto o `/home/box/.finnhub_env`) o `box-secrets.json` (no commitear secretos). Sin key, earnings se omiten y los logos salen de la cache.

Dependencias: **stdlib** (`urllib`, `json`, etc.). `requirements.txt` vacío a propósito.

## Publicar online (GitHub Pages + PWA)

URL final: <https://tabaqueriaparanaarg-beep.github.io/desk-dashboard/> (todas las rutas son relativas, funciona en sub-path).

1. Crear el repo **`desk-dashboard`** en la cuenta `tabaqueriaparanaarg-beep` y subir el contenido de esta carpeta a la rama `main` (el `.gitignore` excluye `.venv`, `__pycache__`, `_site` y archivos de keys).
2. **Settings → Secrets and variables → Actions → New repository secret**, crear los 3 secrets:
   - `ALPACA_API_KEY`
   - `ALPACA_SECRET_KEY`
   - `FINNHUB_API_KEY`
3. **Settings → Pages → Build and deployment → Source: _GitHub Actions_**.
4. El workflow `.github/workflows/update-and-deploy.yml` corre:
   - en cada push a `main`,
   - de lunes a viernes a las **21:30 UTC (18:30 Buenos Aires)**, después del cierre de EE.UU.,
   - manualmente: **Actions → "Update data & deploy to GitHub Pages" → Run workflow**.
   
   Regenera `datos.json` con `python build.py` y publica solo los archivos del sitio (`_site/`). Si el build falla, se publica el `datos.json` que ya está en el repo. El `datos.json` actualizado **no** se commitea de vuelta (vive solo en el deploy).
5. Instalar como app: abrir la URL en Chrome/Edge (Instalar app) o en iPhone Safari → Compartir → *Agregar a inicio*. El service worker (`sw.js`) cachea el shell y los logos (cache-first) y pide `datos.json` siempre a la red primero (fallback offline a la última copia).

> Al cambiar `app.js` / `styles.css`, subir el `?v=` en `index.html` y en `SHELL_ASSETS` + `VERSION` de `sw.js`.

## Qué hace `build.py`

1. Lee `universe.json` (~70 tickers US / proxies CEDEAR / ETFs).
2. Baja barras diarias (~250 sesiones) desde Alpaca Data API (feed IEX, batches, reintentos 429).
3. Calcula indicadores y **Desk Score 0–100**.
4. KPIs de universo + earnings de la semana (Finnhub, falla soft).
5. Calcula **Retorno Top 10** (últimas 10 ruedas vs SPY), la columna **Entró** (racha en el Top 10, últimas 30 sesiones) y escribe todo en `datos.json`.
6. Baja logos faltantes (Finnhub `profile2`, falla soft) y agrega `logo` por fila + mapa `logos`.

Símbolos sin barras suficientes se omiten y quedan en `failures`.

## Fórmulas (resumen)

| Pieza | Peso / definición |
|--------|-------------------|
| **Desk Score** | `0.25·Tendencia + 0.30·Fuerza_RS + 0.30·Contracción + 0.15·Setup` (pilares 0–100) |
| **Entró (Top 10)** | Fecha en que el ticker entró al Top 10 en la racha actual, más las ruedas de esa racha |
| **Tendencia (~25%)** | Precio vs SMA50 / EMA200, pendientes ~5d, estructura SMA50&gt;EMA200 |
| **Fuerza RS (~30%)** | Percentil del *relative performance* vs SPY (~126d / 6m; fallback 63d) + bonus por aceleración 1m |
| **RS Score** | Percentil 0–100 de `(retorno_ticker − retorno_SPY)` en el universo scored |
| **Contracción (~30%)** | Proxy VCP: ATR actual / ATR~60d, vol realizada 20 vs 60, RSI no extremo, dry-up de volumen |
| **Setup (~15%)** | Cercanía a EMA200/SMA50 + dry-up + RSI neutro |
| **Vol rel** | Volumen último día / media 20 sesiones |
| **Dist EMA200** | `(close / EMA200 − 1) × 100` |
| **Puntos de pilar (ficha)** | score 0–100 del pilar × peso: Tendencia /25, Fuerza RS /30, Contracción /30, Setup /15 (antes de penalizaciones) |
| **Rango 52 semanas** | mín/máx de high-low en las últimas 252 sesiones; posición % = (cierre − mín) / (máx − mín) |
| **RS semanal (ficha)** | mismo percentil de RS Score, recalculado al último cierre de cada una de las últimas 16 semanas ISO. El último punto es el RS Score publicado |

Flags opcionales (penalty suave): `extendido_vs_ema200`, `atr_elevado`, `posible_distribucion`, `rsi_sobrecompra` / `rsi_sobreventa`.

Detalle completo también en `datos.json` → clave `formulas`.

## UI

- Español, estructura semántica + clases `dd-*` y `data-*` para que puedas restylear.
- Dark fintech (#FF6B35), responsive (KPIs 2-col en móvil, filtros wrap, tabla con scroll y columnas sticky).
- **Disclaimer:** no es recomendación de compra.

### UI refresh vs datos

- Botón **Actualizar** + auto cada **5 min** solo recargan `datos.json` (pausa si la pestaña está oculta).
- Datos de mercado: `python3 build.py` (manual o cron).

### Régimen

Reglas (`datos.json` → `regime` / `formulas.regime`):

- `pct_above_ema200 >= 60` → **alcista**
- `40–60` → **mixto**
- `< 40` → **bajista**
- Soft override: SPY bajo EMA200 + label alcista → **mixto**

`regime_stub` es alias de `regime` (back-compat).


### Retorno Top 10 del Desk Score

Panel después de los KPIs: retorno de las últimas **10 ruedas** del Top 10 por Desk Score, con sparkline SVG, score y barra de retorno (verde/rojo). Compara el retorno medio del Top 10 vs SPY en la misma ventana.

- En cada `python3 build.py` se regenera `datos.json` → `top10_return`.
- Sin rebuild completo del universo: `python3 patch_top10_return.py` (solo Top 10 + SPY vía Alpaca). No recomputa la racha «Entró» (hace falta el historial largo); copia `ranking[].entro` a las filas del panel.

### Entró (racha en el Top 10)

Columna **Entró** en el panel Top 10 y en el ranking. Para cada ticker que hoy está en el Top 10, muestra la fecha en que empezó su racha actual (sin huecos) y cuántas ruedas lleva, por ejemplo `12/09 · 9 ruedas`.

En cada build, sin archivos de historia y sin llamadas extra a la API:

1. Se toman las últimas **30** sesiones de SPY dentro de las barras diarias que ya se bajaron.
2. Se recomputa el Desk Score de todo el universo truncando cada serie en esa fecha (mismos pilares y penalizaciones).
3. Se camina desde hoy hacia atrás hasta la primera sesión en la que el ticker no estaba en el Top 10. Esa sesión siguiente es la entrada.

Si la racha cubre las 30 sesiones, no se vio el inicio: `antes del DD/MM · >30 ruedas`.

**Aproximación:** el Desk Score no usa earnings ni ningún otro dato de Finnhub (sólo precio, volumen y SPY). La reconstrucción histórica es la misma fórmula que el ranking del día; no hay pilar “congelado”. Si más adelante un pilar dependiera de un dato puntual no histórico, habría que dejarlo fijo en la ventana.

El resultado queda en `ranking[].entro`, `top10_return.rows[].entro` y el bloque `top10_entry` (`label`, `date`, `sessions`, `censored`, `lookback_sessions`). Fuera del Top 10 actual, `entro` es `null`.

### Ficha del ticker

Al tocar una fila del ranking o del Top 10 se abre `#/t/TICKER` (el botón atrás y el retroceso del navegador vuelven al ranking). La ficha usa datos que `build.py` ya calcula:

- **Desk Score** en un gauge, y los cuatro pilares en puntos reales (Tendencia 25, Fuerza RS 30, Contracción 30, Setup 15). Es el mismo score 0–100 × peso, antes de las penalizaciones suaves (−5 extendido, −4 distribución, −3 ATR alto).
- **Rango de 52 semanas**: mínimo, máximo y posición % del cierre sobre las últimas 252 sesiones (o las que haya).
- **Gate de tendencia**: precio frente a la EMA200 y si la EMA200 sube o baja contra su valor de ~5 sesiones atrás, con la distancia en %.
- **Penalizaciones**: los mismos `flags`. Si no hay, «Sin penalizaciones activas».
- **Entró**: la racha del Top 10, si el ticker está adentro.
- **Resultados**: fecha (y BMO/AMC) si el ticker está en `earnings` de la semana.
- **Evolución del RS Score**: ver la definición abajo. Fechas compartidas en `rs_weekly.dates`; cada fila trae `rs_weekly` (16 números como mucho).

**Definición del RS semanal.** En cada uno de los últimos 16 cierres semanales (última sesión de cada semana ISO del calendario de SPY, incluida la semana en curso) se recalcula el mismo relativo que el RS Score: retorno del ticker menos retorno de SPY en ~126 sesiones (fallback 63). Ese valor se convierte en percentil 0–100 dentro de los símbolos que tienen barra ese día. No es el pilar Fuerza RS: ese pilar suma un bonus de aceleración a 1 mes. El último punto de la serie es el RS Score publicado en la columna RS, para que el gráfico cierre en el mismo número. El texto completo viaja en `datos.json` → `rs_weekly.definition` y en `formulas.rs_weekly`.

### Logos de empresas

- Fuente: Finnhub `/stock/profile2?symbol=TICKER` → campo `logo`; se guarda en `assets/logos/<TICKER>.<ext>` (formato real: png/svg/jpg).
- `assets/logos/index.json`: `ticker → archivo` o `null` (sin logo; también se cachea para no re-pedirlo).
- Cache: si el archivo existe o hay `null` no se vuelve a pedir. Rate limit: ~1.1 s entre llamadas (free tier 60/min). Errores de red no se cachean y nunca rompen el build.
- CEDEARs: se usa el ticker subyacente US (el `symbol` de `universe.json`; soporta `underlying`/`us_symbol` si se agregan).
- Sin rebuild completo: `python3 fetch_logos.py` (baja faltantes y parchea `datos.json`). Flags: `--force` (re-pide todo, incluso nulls), `--symbols AAPL,MELI`, `--no-patch`.
- `datos.json`: campo `logo` (ruta relativa o `null`) en `ranking`, `top10_return.rows` y `earnings`, más mapa top-level `logos`.
- UI: logo redondo 20px (18px móvil) sobre fondo claro a la izquierda del ticker; sin logo o si falla la imagen → círculo con gradiente naranja e iniciales. `loading="lazy"`.
- ETFs (SPY, QQQ, XL*…) no tienen logo en Finnhub → fallback.

### Filtros ranking

Kind (Todos / US / CEDEAR proxy / ETF), toggles Sobre EMA200 y RS > 70, búsqueda por ticker. Contador "Mostrando X de Y" (cliente).

## Archivos

- `universe.json` — universo editable
- `build.py` — pipeline
- `fetch_logos.py` — logos standalone (Finnhub) + patch de `datos.json`
- `assets/logos/` — logos cacheados + `index.json`
- `datos.json` — salida (generada)
- `index.html` / `app.js` / `styles.css` — front
- `requirements.txt` — sin deps externas
- `manifest.webmanifest` / `sw.js` / `assets/icon-*.png` — PWA
- `.github/workflows/update-and-deploy.yml` — actualización diaria + deploy a Pages

## Seguridad

No guardar ni imprimir API keys. No crear paywall ni login.
