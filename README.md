# Angus

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
   - en cada push a `main` (con el mercado abierto no guarda el historial),
   - de lunes a viernes a las **21:30 UTC (18:30 Buenos Aires)**, después del cierre de EE.UU.,
   - cada 30 minutos en la ventana 9:30–16:00 ET (verano e invierno); si Alpaca dice que está cerrado, esa corrida se saltea,
   - manualmente: **Actions → "Update data & deploy to GitHub Pages" → Run workflow**.
   
   Regenera `datos.json` con `python build.py` y publica solo los archivos del sitio (`_site/`). Si el build falla, se publica el `datos.json` que ya está en el repo. El `datos.json` actualizado **no** se commitea de vuelta (vive solo en el deploy).
5. Instalar como app: abrir la URL en Chrome/Edge (Instalar app) o en iPhone Safari → Compartir → *Agregar a inicio*. El service worker (`sw.js`) cachea el shell y los logos (cache-first) y pide `datos.json` siempre a la red primero (fallback offline a la última copia).

> Al cambiar `app.js` / `styles.css`, subir el `?v=` en `index.html` y en `SHELL_ASSETS` + `VERSION` de `sw.js`.

## Qué hace `build.py`

1. Lee `universe.json` (~70 tickers US / proxies CEDEAR / ETFs).
2. Baja barras diarias (~250 sesiones) desde Alpaca Data API (feed IEX, batches, reintentos 429).
3. Calcula indicadores y **Desk Score 0–100**.
4. KPIs de universo + earnings de la semana (Finnhub, falla soft).
5. Calcula **Retorno Top 10** (últimas 10 ruedas vs SPY), la columna **Entró** (racha en el Top 10, últimas 30 sesiones), la **simulación walk-forward** del Top 10 contra SPY, la **vista por sectores** y escribe todo en `datos.json`.
6. Baja logos faltantes (Finnhub `profile2`, falla soft) y agrega `logo` por fila + mapa `logos`.

Símbolos sin barras suficientes se omiten y quedan en `failures`.

## Fórmulas (resumen)

| Pieza | Peso / definición |
|--------|-------------------|
| **Desk Score (v3)** | Percentil 0–100 del **momentum 12-1** en el universo; × 0,5 si el cierre está bajo la EMA200. Sin penalizaciones. Ver «Desk Score v3» abajo |
| **Momentum 12-1** | `close[hace 21 ruedas] / close[hace 252 ruedas] − 1` (12 meses salteando el último). Con menos de 12 meses de historia: 6-1 (flag `momentum_6m`); con menos de 6: score 0 (flag `sin_historia_momentum`) |
| **Entró (Top 10)** | Fecha en que el ticker entró al Top 10 en la racha actual, más las ruedas de esa racha |
| **Walk-forward Top 10** | Cada último cierre semanal, Top 10 equiponderado con datos solo hasta ese cierre, vs SPY comprar y mantener |
| **Tendencia (info)** | Precio vs SMA50 / EMA200, pendientes ~5d, estructura SMA50&gt;EMA200 |
| **Fuerza RS (info)** | Percentil del *relative performance* vs SPY (~126d / 6m; fallback 63d) + bonus por aceleración 1m |
| **RS Score** | Percentil 0–100 de `(retorno_ticker − retorno_SPY)` en el universo scored |
| **Contracción (info)** | Proxy VCP: ATR actual / ATR~60d, vol realizada 20 vs 60, RSI no extremo, dry-up de volumen |
| **Vol rel** | Volumen último día / media 20 sesiones |
| **Dist EMA200** | `(close / EMA200 − 1) × 100` |
| **Pilares (ficha)** | Momentum sobre 100 (lo único que entra). Tendencia, Fuerza RS y Contracción en 0–100, como referencia |
| **Rango 52 semanas** | mín/máx de high-low en las últimas 252 sesiones; posición % = (cierre − mín) / (máx − mín) |
| **RS semanal (ficha)** | mismo percentil de RS Score, recalculado al último cierre de cada una de las últimas 16 semanas ISO. El último punto es el RS Score publicado |

Flags informativos (desde v3 no restan puntos): `extendido_vs_ema200`, `atr_elevado`, `posible_distribucion`, `rsi_sobrecompra` / `rsi_sobreventa`, `momentum_6m`, `sin_historia_momentum`.

### Desk Score v3 (nov-2026): por qué cambió

Hasta v2 el score era `0.30·Tendencia + 0.35·Fuerza_RS + 0.35·Contracción` con penalizaciones. Un backtest walk-forward de ago-2021 a nov-2026 (Top 10 equiponderado, 10 bps por lado) mostró que no ordenaba:

| Top 10 semanal, anual promedio | v2 | v3 (momentum 12-1) | Universo equiponderado | SPY |
|---|---|---|---|---|
| 61 acciones originales | 8,6 % | 25,2 % | 16,6 % | 12,0 % |
| Universo amplio (380) | 4,8 % | 64,5 % | 17,6 % | 12,0 % |

- En v2, el quintil de score más alto rendía **peor** que el resto a 4 semanas. Contracción restaba en los dos universos y Tendencia no distinguía entre acciones.
- El momentum 12-1 fue la única señal con el quintil alto claramente arriba en los dos universos.
- **Límites:** el universo es el de hoy (sesgo de supervivencia, que infla mucho el número del universo amplio); son ~5 años de un mercado que premió a los líderes; el Top 10 por momentum tiene más volatilidad que el SPY (24 % anual en las 61, 41 % en el amplio) y el momentum tiene caídas bruscas cuando el mercado da vuelta.
- Para repetirlo: `python3 backtest_largo.py` (baja barras de Alpaca a `.cache_backtest_bars.json`) y después `python3 backtest_pilares.py` (usa la cache, mide cada pilar y el universo de 61).

### Variantes del Top 10 y simulación mensual (nov-2026)

La página arranca en el **Top 10 con CEDEAR** (`TOP10_DEFAULT_VARIANT = "cedear"`): solo acciones con la marca `cedear` de `universe.json`, para que todo lo que muestra se pueda comprar desde Argentina. Un selector cambia entre **Con CEDEAR / Todas** y **Normal / Conservadora**. Los ETFs no entran a ningún Top 10.

- **Conservadora** (`desk_score_cons`, `rank_cons`): percentil de momentum 12-1 ÷ volatilidad anualizada de 126 ruedas (`vol_126d_pct`), × 0,5 bajo la EMA200. En el backtest cae menos que el v3 y rinde menos.
- `top10_variants` trae el retorno y la atribución de cada variante. `top10_return` y `top10_attribution` siguen siendo los de la variante por defecto. «Entró» se calcula solo para esa.
- La **simulación** rebalancea una vez por mes (último cierre semanal del mes), mide 52 semanas y trae un libro por variante en `top10_walkforward.books`, cada uno con la línea del **universo equiponderado** (`universe` en la curva). Una simulación publicada con otro tipo de rebalanceo no se reutiliza.

| Top 10 mensual, ago-2021 a nov-2026 | Amplio | Caída máx. | 61 originales | Caída máx. |
|---|---|---|---|---|
| Todas | 66,7 % | −33,5 % | 22,7 % | −18,4 % |
| Con CEDEAR | 33,1 % | −31,5 % | 21,7 % | −23,8 % |
| Con CEDEAR, conservadora | 22,6 % | −22,0 % | 19,8 % | −15,1 % |
| SPY | 11,9 % | −23,9 % | 11,9 % | −23,9 % |

### Limpieza de secciones (nov-2026)

Una auditoría de todas las señales (276 semanas, ago-2021 a nov-2026, universo amplio y 61 originales) encontró que el escáner de patrones, la confluencia y la rotación (RRG) no anticipan el retorno de las 4 semanas siguientes; la rotación incluso funciona al revés (lo «rezagado» rindió más que lo «liderando» en 5 de 6 años). Por eso:

- **Salen de la página:** Señales (confluencia y escáner), Rotación (RRG), RS semanal, Podio del día, Números del universo e Historial del semáforo. La barra queda en Resumen, Score y Análisis; los links viejos (`#senales`, `#rotacion`) llevan a Score.
- **Siguen calculándose por dentro:** los patrones (el semáforo usa el cruce bajista de la EMA200) y el RS semanal (la Vista por sectores lo usa). `signals.py` y `rrg.py` quedan para repetir estudios. `historial_semaforo.json` se sigue guardando.
- **Analistas e insiders** solo en la ficha. La ficha arranca por el Desk Score, el semáforo y los resultados.
- **Ranking:** #, Ticker (● = tiene CEDEAR), Score, Momentum, Luz, Entró, Dist EMA200 y Alertas.
- **Régimen de mercado:** pasa a ser una lectura de riesgo (tranquilo / normal / movido / turbulento). Anticipa la volatilidad del SPY (≈12 % anual con 75–100, ≈23 % por debajo de 50) pero no la dirección, así que ya no sugiere cuánto invertir.
- **Resumen del día:** compara el Top 10 que muestra la página (con CEDEAR) y no menciona patrones.

`SCORE_VERSION = 3` va en `datos.json` → `score_version`. Los Desk Score guardados en el historial del semáforo antes de este cambio son de v2.

Detalle completo también en `datos.json` → clave `formulas`.

## UI

- Español, estructura semántica + clases `dd-*` y `data-*` para que puedas restylear.
- Dark fintech (#FF6B35), responsive (KPIs 2-col en móvil, filtros wrap, tabla con scroll y columnas sticky).
- **Disclaimer:** no es recomendación de compra. El Desk Score, el Top 10 y el semáforo son un filtro de lectura y de riesgo, no una ventaja de compra.

### Semáforo de riesgo

Luz informativa. No entra en el Desk Score ni reordena el ranking.

- **Verde:** sin alertas de riesgo (precio sobre la EMA200 con pendiente en alza, sin cruce bajista reciente de la EMA200, y sin resultados en los próximos 7 días del calendario que ya baja Angus).
- **Ámbar:** resultados cerca.
- **Rojo:** la tendencia no acompaña o hay un cruce bajista reciente de la EMA200.
- No se usa estiramiento, Desk Score, patrón, sector ni penalizaciones. Esas reglas no se invierten: se sacan.

El filtro del ranking se llama **Sin alertas**. El verde no es una compra.

### Barrick Gold

En Alpaca el ticker `GOLD` pasó a ser Gold.com (ex A-Mark). Barrick cotiza como **`B`** desde 2025. El universo usa `B` y el nombre Barrick Gold.

### UI refresh vs datos

- Botón **Actualizar** + auto cada **5 min** solo recargan `datos.json` (pausa si la pestaña está oculta).
- Datos de mercado: `python3 build.py` (manual o cron).

### Régimen

Reglas (`datos.json` → `regime` / `formulas.regime`):

- `pct_above_ema200 >= 60` → **alcista**
- `40–60` → **mixto**
- `< 40` → **bajista**
- Soft override: SPY bajo EMA200 + label alcista → **mixto**

`regime_stub` es alias de `regime` (back-compat). El resumen diario sigue usando esta etiqueta.

### Régimen de mercado (puntaje 0–100)

Panel aparte (`datos.json` → `market_regime` / `formulas.market_regime`). No cambia el Desk Score, el semáforo, el ranking ni el historial.

- **125 pts crudos**, normalizados a 0–100 con los puntos que de verdad hay. Si falta el VIX: «calculado sobre X pts disponibles de 125».
- **Índices SPY/QQQ (80):** 8 pts por condición y por índice — cierre sobre EMA200, cierre sobre SMA50, pendiente de EMA200 al alza (5 sesiones), pendiente de SMA50 al alza, SMA50 sobre EMA200.
- **Amplitud (30):** 10 × % sobre EMA200, 10 × % sobre SMA50, y 10 según el balance de nuevos máximos y mínimos de 52 semanas del día (5 pts neutros si no hubo ninguno).
- **Sentimiento (15):** CSV público de CBOE (`VIX_History.csv`). 5 pts si el cierre es ≤ 20, 5 si está bajo la media de 20 ruedas y 5 si está bajo la de 50. Si CBOE falla, VIXY de Alpaca (no entra al universo ni al ranking): 8 y 7 pts contra esas medias, sin umbral de precio.
- **Exposición sugerida:** 0–25 mínima, 25–50 posiciones chicas, 50–75 normal, 75–100 plena. Es una guía automática, no un consejo de inversión.
- **Serie:** % de activos sobre la EMA200 en las últimas 42 ruedas, recalculada con las barras ya descargadas.


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

### Simulación Top 10 vs SPY (walk-forward)

Panel debajo de «Retorno Top 10». No es lo mismo: aquel toma el Top 10 **de hoy** y mide cómo les fue en las últimas 10 ruedas (sesgo de supervivencia y de look-ahead). Esta simulación arma el Top 10 **en cada fecha**, solo con lo que ya había pasado.

Reglas (`datos.json` → `top10_walkforward` / `formulas.top10_walkforward`):

- **Rebalanceo:** último cierre de cada semana ISO (el viernes, o el jueves si el viernes no hubo rueda). Misma idea de semana que el RS semanal. Se opera a ese mismo cierre: la señal y el precio de compra/venta son el cierre. No hay demora de un día ni comisiones.
- **Señal:** Desk Score de todo el universo truncando las barras en ese cierre (`rank_universe_asof`, la misma fórmula que el ranking). Un símbolo sin barra ese día no entra. El Top 10 del último cierre de la ventana **no** se usa para el retorno de esa semana: ese cierre solo marca el valor del libro armado la semana anterior.
- **Cartera:** los 10 nombres con el mismo peso, hasta el cierre semanal siguiente. Los que salen se venden y entran los nuevos. Si a un nombre le falta el cierre de salida, esa semana el peso se reparte entre los que sí tienen ambos cierres.
- **SPY:** comprar y mantener entre el primer y el último cierre de la ventana.
- **Historia:** el ranking publicado sigue usando ~400 días calendario (el Desk Score del día no cambia). Para la simulación se piden ~620 días, se descartan las primeras 253 ruedas (recién ahí existe el momentum 12-1) y se miden como máximo las **26** semanas más recientes. Si el historial no alcanza, el panel dice cuántas semanas hubo.
- **Métricas:** retorno total de la cartera y de SPY, exceso (resta simple), porcentaje de semanas en que la cartera le gana a SPY (un empate no cuenta), caída máxima de las dos curvas (base 100) y rotación media (nombres que salen del Top 10 en cada rebalanceo, sin contar la compra inicial).

Es una simulación, no una recomendación. Los resultados pasados no garantizan resultados futuros.

### Vista por sectores

Panel arriba del ranking (`datos.json` → `sectors`). Agrupa las **acciones** del universo y las ordena por Desk Score medio. Cada tarjeta muestra cantidad de nombres, Desk Score medio, RS Score medio, % sobre EMA200, cuántos están en el Top 10 de hoy, el mejor ticker (enlace a `#/t/TICKER`) y el cambio diario medio. La flecha compara el RS medio de ahora con el de hace 4 semanas (`rs_weekly`): sube, baja, o queda plana si el salto es menor a 1 punto. Con 1 o 2 nombres aparece **Muestra chica**.

**Qué queda afuera.** Los ETFs (`kind: etf`), aunque tengan sector: benchmarks (SPY, QQQ, IWM, DIA, sector Benchmark) y ETFs de sector (XLK, XLF, XLE, XLV, XLI, XLP, XLY). Son canastas, no acciones; meterlos inflaría el conteo y mezclaría el fondo con los nombres. También se excluye una fila sin sector. El detalle viaja en `sectors.excluded` y en `formulas.sectors`.

Tocar una tarjeta (o el chip de sector en el ranking) filtra el ranking a esas acciones, sin los ETFs de ese sector. Volver a tocarla saca el filtro.

Es una lectura del tablero, no una recomendación.

### Ficha del ticker

Al tocar una fila del ranking o del Top 10 se abre `#/t/TICKER` (el botón atrás y el retroceso del navegador vuelven al ranking). La ficha usa datos que `build.py` ya calcula:

- **Desk Score** en un gauge, con el Momentum 12-1 (sobre 100) que lo arma y, debajo, Tendencia, Fuerza RS y Contracción como referencia. Si el cierre está bajo la EMA200, una nota aclara que el score es la mitad del momentum.
- **Rango de 52 semanas**: mínimo, máximo y posición % del cierre sobre las últimas 252 sesiones (o las que haya).
- **Gate de tendencia**: precio frente a la EMA200 y si la EMA200 sube o baja contra su valor de ~5 sesiones atrás, con la distancia en %.
- **Alertas**: los mismos `flags`, solo como información (no restan puntos). Si no hay, «Sin alertas activas».
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

Kind (Todos / US / CEDEAR proxy / ETF), sector (Todos más un chip por sector de la vista), toggles Sobre EMA200 y RS > 70, búsqueda por ticker. El filtro de sector deja afuera los ETFs, igual que la vista. Contador "Mostrando X de Y" (cliente).

## Archivos

- `universe.json` — universo editable
- `build.py` — pipeline
- `fetch_logos.py` — logos standalone (Finnhub) + patch de `datos.json`
- `assets/logos/` — logos cacheados + `index.json`
- `datos.json` — salida (generada)
- `index.html` / `app.js` / `styles.css` — front
- `requirements.txt` — sin deps externas
- `manifest.webmanifest` / `sw.js` / `assets/icon-*.png` — PWA
- `.github/workflows/update-and-deploy.yml` — cierre de las 18:30 ART, intradía cada 30 min con el mercado abierto, y deploy a Pages

## Seguridad

No guardar ni imprimir API keys. No crear paywall ni login.
