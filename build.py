#!/usr/bin/env python3
"""
Desk Dashboard / CEO X Dashboard — pipeline de datos técnicos.
Genera datos.json a partir de Alpaca (barras) + Finnhub (earnings + logos).
Sin paywall, sin login. Uso interno.
"""
from __future__ import annotations

import json
import math
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
UNIVERSE_PATH = ROOT / "universe.json"
OUT_PATH = ROOT / "datos.json"

def _env_first(*names: str, default: str = "") -> str:
    """Primer valor no vacío entre varias variables de entorno."""
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return default


# Credenciales: primero las variables usadas en GitHub Actions (ALPACA_API_KEY /
# ALPACA_SECRET_KEY), luego los nombres oficiales del SDK de Alpaca (APCA_*).
# Nunca se imprimen.
ALPACA_DATA = _env_first(
    "ALPACA_DATA_URL", "ALPACA_DATA_BASE_URL", default="https://data.alpaca.markets"
).rstrip("/")
ALPACA_FEED = _env_first("ALPACA_FEED", default="iex")  # iex (gratis) | sip (pago)
APCA_KEY = _env_first("ALPACA_API_KEY", "APCA_API_KEY_ID")
APCA_SECRET = _env_first("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY")

# Barras diarias ~250 días de trading ≈ 380 días calendario
LOOKBACK_CALENDAR_DAYS = 400
BATCH_SIZE = 8
MAX_RETRIES = 5
SLEEP_BETWEEN_BATCHES = 0.35


def load_finnhub_key() -> str:
    # 1) variable de entorno (GitHub Actions / shell)
    env_key = _env_first("FINNHUB_API_KEY", "FINNHUB_TOKEN")
    if env_key:
        return env_key
    # 2) fallbacks locales (.finnhub_env, box secrets)
    for env_file in (ROOT / ".finnhub_env", Path("/home/box/.finnhub_env")):
        if not env_file.is_file():
            continue
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            if "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k in ("FINNHUB_API_KEY", "FINNHUB_TOKEN") and v:
                    return v
    secrets = Path("/home/box/agent-data/box-secrets.json")
    if secrets.is_file():
        try:
            data = json.loads(secrets.read_text())
            card = data.get("card") or data
            key = card.get("FINNHUB_API_KEY") or card.get("finnhub_api_key")
            if key:
                return str(key)
        except Exception:
            pass
    return os.environ.get("FINNHUB_API_KEY", "")


def http_get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> Any:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    ctx = ssl.create_default_context()
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                wait = min(2 ** attempt * 1.5, 30)
                time.sleep(wait)
                continue
            if e.code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    if last_err:
        raise last_err
    raise RuntimeError("http_get_json failed")


# ---------------------------------------------------------------------------
# Logos (Finnhub /stock/profile2 → assets/logos/<TICKER>.<ext>)
# ---------------------------------------------------------------------------
LOGO_DIR = ROOT / "assets" / "logos"
LOGO_INDEX = LOGO_DIR / "index.json"
LOGO_SLEEP = 1.1  # Finnhub free tier ≈ 60 calls/min
LOGO_CT_EXT = {
    "image/png": "png",
    "image/svg+xml": "svg",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


def logo_symbol(u: dict) -> str:
    """Ticker a consultar en Finnhub. CEDEARs ya vienen como subyacente US;
    si en el futuro se agrega un campo explícito (underlying/us_symbol) se usa ése."""
    return str(u.get("underlying") or u.get("us_symbol") or u.get("symbol") or "").upper()


def _sniff_image_ext(data: bytes, content_type: str, url: str) -> str | None:
    head = data[:512].lstrip()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] == b"GIF8":
        return "gif"
    if head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in data[:2048]:
        return "svg"
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in LOGO_CT_EXT:
        return LOGO_CT_EXT[ct]
    ext = Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    return ext if ext in ("png", "svg", "jpg", "webp", "gif") else None


def _download_bytes(url: str, timeout: int = 30) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "desk-dashboard/1.0"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def load_logo_index() -> dict[str, str | None]:
    try:
        data = json.loads(LOGO_INDEX.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def logo_rel_path(fname: str | None) -> str | None:
    return f"assets/logos/{fname}" if fname else None


def fetch_logos(
    symbols: list[str],
    finnhub_key: str,
    force: bool = False,
    sleep_s: float = LOGO_SLEEP,
    verbose: bool = True,
) -> tuple[dict[str, str | None], list[str]]:
    """Baja logos faltantes. Devuelve (ticker → ruta relativa o None, notas).
    Cache: archivo existente o null en index.json → no se vuelve a pedir (salvo force).
    Errores de red NO se cachean como null (se reintentan en la próxima corrida).
    Nunca lanza excepción: fallas son soft."""
    notes: list[str] = []
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    index = load_logo_index()
    existing = {p.stem.upper(): p.name for p in LOGO_DIR.iterdir() if p.is_file() and p.name != "index.json"}
    fetched = cached = errors = 0

    def save_index() -> None:
        LOGO_INDEX.write_text(json.dumps(dict(sorted(index.items())), indent=2) + "\n")

    for sym in symbols:
        sym = sym.upper()
        if not force:
            if sym in existing:
                index[sym] = existing[sym]
                cached += 1
                continue
            if sym in index and index[sym] is None:
                cached += 1
                continue
        if not finnhub_key:
            continue
        url = "https://finnhub.io/api/v1/stock/profile2?" + urllib.parse.urlencode(
            {"symbol": sym, "token": finnhub_key}
        )
        try:
            prof = http_get_json(url, timeout=30) or {}
            time.sleep(sleep_s)
        except Exception as e:  # no loguear la URL (lleva el token)
            errors += 1
            if verbose:
                print(f"  logo FAIL {sym}: profile2 {type(e).__name__}")
            time.sleep(sleep_s)
            continue
        logo_url = str(prof.get("logo") or "").strip() if isinstance(prof, dict) else ""
        if not logo_url:
            index[sym] = None
            if verbose:
                print(f"  logo --   {sym}: sin logo en Finnhub")
            save_index()
            continue
        try:
            data, ctype = _download_bytes(logo_url)
            ext = _sniff_image_ext(data, ctype, logo_url)
            if not data or not ext:
                index[sym] = None
                if verbose:
                    print(f"  logo --   {sym}: formato no reconocido ({ctype})")
            else:
                for old in LOGO_DIR.glob(f"{sym}.*"):
                    if old.name != "index.json":
                        old.unlink()
                fname = f"{sym}.{ext}"
                (LOGO_DIR / fname).write_bytes(data)
                index[sym] = fname
                existing[sym] = fname
                fetched += 1
                if verbose:
                    print(f"  logo OK   {sym}: {fname} ({len(data)} B)")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                index[sym] = None
            else:
                errors += 1
            if verbose:
                print(f"  logo FAIL {sym}: imagen HTTP {e.code}")
        except Exception as e:
            errors += 1
            if verbose:
                print(f"  logo FAIL {sym}: imagen {type(e).__name__}")
        save_index()

    try:
        save_index()
    except Exception:
        pass
    if not finnhub_key:
        notes.append("Logos: sin Finnhub API key — sólo cache local")
    out = {s.upper(): logo_rel_path(index.get(s.upper())) for s in symbols}
    have = sum(1 for v in out.values() if v)
    notes.append(
        f"Logos: {have}/{len(symbols)} con logo (nuevos {fetched}, cache {cached}, errores {errors})"
    )
    return out, notes


def logo_map_from_cache(symbols: list[str]) -> dict[str, str | None]:
    index = load_logo_index()
    out: dict[str, str | None] = {}
    for s in symbols:
        fname = index.get(s.upper())
        out[s.upper()] = logo_rel_path(fname) if fname and (LOGO_DIR / fname).is_file() else None
    return out


def attach_logos(payload: dict, logo_map: dict[str, str | None]) -> None:
    """Agrega `logos` (mapa top-level) y campo `logo` en ranking / top10 / earnings."""
    payload["logos"] = dict(sorted(logo_map.items()))

    def _set(rows: Any) -> None:
        for r in rows or []:
            if isinstance(r, dict) and r.get("symbol"):
                r["logo"] = logo_map.get(str(r["symbol"]).upper())

    _set(payload.get("ranking"))
    _set((payload.get("top10_return") or {}).get("rows"))
    _set(payload.get("earnings"))


def alpaca_headers() -> dict[str, str]:
    if not APCA_KEY or not APCA_SECRET:
        raise SystemExit(
            "ERROR: faltan credenciales de Alpaca. Definí ALPACA_API_KEY y "
            "ALPACA_SECRET_KEY (o APCA_API_KEY_ID / APCA_API_SECRET_KEY) en el entorno."
        )
    return {
        "APCA-API-KEY-ID": APCA_KEY,
        "APCA-API-SECRET-KEY": APCA_SECRET,
        "Accept": "application/json",
    }


def fetch_bars_batch(symbols: list[str], start: str, end: str) -> dict[str, list[dict]]:
    """Fetch daily bars for a batch of symbols. Returns symbol -> list of bars."""
    params = urllib.parse.urlencode(
        {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start,
            "end": end,
            "adjustment": "split",
            "feed": ALPACA_FEED,
            "limit": 10000,
            "sort": "asc",
        }
    )
    url = f"{ALPACA_DATA}/v2/stocks/bars?{params}"
    headers = alpaca_headers()
    all_bars: dict[str, list[dict]] = {s: [] for s in symbols}
    page_token: str | None = None
    while True:
        u = url if not page_token else f"{url}&page_token={urllib.parse.quote(page_token)}"
        data = http_get_json(u, headers=headers)
        bars_map = data.get("bars") or {}
        for sym, bars in bars_map.items():
            if bars:
                all_bars.setdefault(sym, []).extend(bars)
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.15)
    return all_bars


# --- Indicators -------------------------------------------------------------

def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period or period < 1:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    s = sum(values[:period])
    out[period - 1] = s / period
    for i in range(period, len(values)):
        s += values[i] - values[i - period]
        out[i] = s / period
    return out


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    gains = []
    losses = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    def _rsi(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))
    out[period] = _rsi(avg_gain, avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = _rsi(avg_gain, avg_loss)
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) < 2:
        return out
    trs: list[float] = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return out
    s = sum(trs[:period])
    out[period - 1] = s / period
    prev = out[period - 1]
    for i in range(period, len(trs)):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def realized_vol(closes: list[float], window: int = 20) -> float | None:
    if len(closes) < window + 1:
        return None
    rets = []
    for i in range(len(closes) - window, len(closes)):
        if closes[i - 1] > 0:
            rets.append(math.log(closes[i] / closes[i - 1]))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100.0  # anualizada %


def pct_change(closes: list[float], lookback: int) -> float | None:
    if len(closes) <= lookback or closes[-1 - lookback] == 0:
        return None
    return (closes[-1] / closes[-1 - lookback] - 1.0) * 100.0


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# Pesos del Desk Score. En la ficha se muestran como puntos sobre el máximo
# (pilar 0–100 × peso): Tendencia 25, Fuerza RS 30, Contracción 30, Setup 15.
PILLAR_WEIGHTS = {
    "tendencia": 0.25,
    "fuerza_rs": 0.30,
    "contraccion": 0.30,
    "setup": 0.15,
}
PILLAR_MAX_POINTS = {k: int(round(w * 100)) for k, w in PILLAR_WEIGHTS.items()}

# Rango de 52 semanas ≈ 252 sesiones. La serie de Alpaca trae ~250–280 barras.
RANGE_52W_SESSIONS = 252

# RS Score al último cierre de cada semana ISO (incluye la semana en curso).
RS_WEEKLY_WEEKS = 16
RS_LOOKBACK_6M = 126
RS_LOOKBACK_3M = 63
RS_LOOKBACK_1M = 21
RS_WEEKLY_DEFINITION = (
    "RS Score semanal: percentil 0–100 de (retorno del ticker − retorno de SPY) "
    "en ~126 sesiones (6 meses; si no alcanza, 63 sesiones / 3 meses), "
    "recalculado al último cierre de cada una de las últimas 16 semanas ISO "
    "(la semana en curso entra con su último cierre). "
    "El percentil se toma entre los símbolos del universo que tienen barra ese día "
    "y retorno relativo válido. No incluye el bonus de aceleración del pilar Fuerza RS. "
    "El último punto es el RS Score publicado en el ranking, para que el gráfico "
    "cierre en el mismo número que la columna RS."
)


def safe_round(x: float | None, n: int = 2) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), n)


# --- Scoring ----------------------------------------------------------------

def score_tendencia(
    close: float,
    sma50: float | None,
    ema200: float | None,
    sma50_prev: float | None,
    ema200_prev: float | None,
) -> float:
    """~25 pts pillar. Above MA + slopes."""
    score = 0.0
    if sma50 is not None:
        if close > sma50:
            score += 40
        else:
            score += max(0, 20 + (close / sma50 - 1) * 100)  # soft if close
        if sma50_prev and sma50 > sma50_prev:
            score += 15
    if ema200 is not None:
        if close > ema200:
            score += 30
        else:
            score += max(0, 10 + (close / ema200 - 1) * 80)
        if ema200_prev and ema200 > ema200_prev:
            score += 15
    if sma50 is not None and ema200 is not None and sma50 > ema200:
        score += 10  # structure bullish
    return clamp(score)


def score_fuerza_rs(rs_score: float, rs_accel: float | None) -> float:
    """~30 pts. RS level + acceleration."""
    base = rs_score  # already 0-100
    bonus = 0.0
    if rs_accel is not None:
        # accel in percentage points of relative perf over ~1m
        bonus = clamp(50 + rs_accel * 5, 0, 100) * 0.25  # up to +25
    return clamp(base * 0.75 + bonus)


def score_contraccion(
    rsi_val: float | None,
    atr_ratio: float | None,
    vol_ratio: float | None,
    rv20: float | None,
    rv60: float | None,
) -> float:
    """~30 pts. Lower vol / ATR compression / RSI not extreme — VCP proxy."""
    score = 50.0
    if atr_ratio is not None:
        # atr_ratio = ATR14 / ATR14_60d_avg; <1 = compression
        if atr_ratio < 0.7:
            score += 25
        elif atr_ratio < 0.85:
            score += 15
        elif atr_ratio < 1.0:
            score += 5
        elif atr_ratio > 1.4:
            score -= 20
        elif atr_ratio > 1.2:
            score -= 10
    if rv20 is not None and rv60 is not None and rv60 > 0:
        ratio = rv20 / rv60
        if ratio < 0.75:
            score += 15
        elif ratio > 1.3:
            score -= 15
    if rsi_val is not None:
        if 40 <= rsi_val <= 65:
            score += 15
        elif rsi_val > 75 or rsi_val < 25:
            score -= 20
        elif rsi_val > 70 or rsi_val < 30:
            score -= 10
    if vol_ratio is not None and vol_ratio < 0.7:
        score += 5  # volume dry-up
    return clamp(score)


def score_setup(
    dist_ema200: float | None,
    dist_sma50: float | None,
    vol_ratio: float | None,
    rsi_val: float | None,
) -> float:
    """~15 pts. Near pullback / dry-up conditions."""
    score = 30.0
    # Ideal: near EMA200 from above (pullback), or near SMA50
    if dist_ema200 is not None:
        d = abs(dist_ema200)
        if 0 <= dist_ema200 <= 5:
            score += 35  # just above / at EMA200
        elif -3 <= dist_ema200 < 0:
            score += 25  # slight undercut
        elif d <= 8:
            score += 15
        elif dist_ema200 > 20:
            score -= 20  # extended
    if dist_sma50 is not None:
        if -2 <= dist_sma50 <= 4:
            score += 20
        elif dist_sma50 > 12:
            score -= 10
    if vol_ratio is not None:
        if vol_ratio < 0.8:
            score += 15
        elif vol_ratio > 1.8:
            score -= 10
    if rsi_val is not None and 45 <= rsi_val <= 60:
        score += 10
    return clamp(score)


def desk_score(tend: float, fuerza: float, contr: float, setup: float) -> float:
    """Weights: Tendencia 25, Fuerza RS 30, Contracción 30, Setup 15."""
    return clamp(
        tend * PILLAR_WEIGHTS["tendencia"]
        + fuerza * PILLAR_WEIGHTS["fuerza_rs"]
        + contr * PILLAR_WEIGHTS["contraccion"]
        + setup * PILLAR_WEIGHTS["setup"]
    )


def pillar_points_block(tend: float, fuerza: float, contr: float, setup: float) -> dict[str, dict]:
    """Puntos de cada pilar (0–máximo) a partir del score 0–100, antes de penalizaciones."""
    raw = {
        "tendencia": tend,
        "fuerza_rs": fuerza,
        "contraccion": contr,
        "setup": setup,
    }
    out: dict[str, dict] = {}
    for key, value in raw.items():
        weight = PILLAR_WEIGHTS[key]
        out[key] = {
            "points": safe_round(value * weight, 1),
            "max": PILLAR_MAX_POINTS[key],
        }
    return out


def trend_gate_label(relation: str | None, slope_up: bool | None) -> str:
    """Texto del gate de tendencia. `relation`: above | below | equal | None."""
    if relation == "above":
        price = "Precio > EMA200"
    elif relation == "below":
        price = "Precio < EMA200"
    elif relation == "equal":
        price = "Precio = EMA200"
    else:
        return "Sin EMA200"
    if slope_up is None:
        return price
    return price + (" con pendiente +" if slope_up else " con pendiente -")


def range_52w(highs: list[float], lows: list[float], close: float) -> dict[str, Any]:
    """Mínimo, máximo y posición % del cierre en las últimas 252 sesiones (o las que haya)."""
    n = min(RANGE_52W_SESSIONS, len(highs), len(lows))
    if n <= 0:
        return {"low": None, "high": None, "position_pct": None, "sessions": 0}
    window_h = highs[-n:]
    window_l = lows[-n:]
    lo = min(window_l)
    hi = max(window_h)
    if hi > lo:
        pos = clamp((close - lo) / (hi - lo) * 100.0, 0.0, 100.0)
    else:
        pos = 100.0
    return {
        "low": safe_round(lo, 2),
        "high": safe_round(hi, 2),
        "position_pct": safe_round(pos, 1),
        "sessions": n,
    }


def relative_performance(
    closes: list[float], spy_closes: list[float]
) -> tuple[float | None, str | None, float | None]:
    """(rel_perf en pp, horizonte '6m'|'3m'|None, rs_accel).

    rel_perf = retorno del ticker − retorno de SPY en 126 sesiones (fallback 63).
    rs_accel = relativo de 21 sesiones − (rel_perf / meses del horizonte).
    """
    perf_6m = pct_change(closes, RS_LOOKBACK_6M)
    spy_6m = pct_change(spy_closes, RS_LOOKBACK_6M) if len(spy_closes) > RS_LOOKBACK_6M else None
    perf_3m = pct_change(closes, RS_LOOKBACK_3M)
    spy_3m = pct_change(spy_closes, RS_LOOKBACK_3M) if len(spy_closes) > RS_LOOKBACK_3M else None
    perf_1m = pct_change(closes, RS_LOOKBACK_1M)
    spy_1m = pct_change(spy_closes, RS_LOOKBACK_1M) if len(spy_closes) > RS_LOOKBACK_1M else None

    if perf_6m is not None and spy_6m is not None:
        rel_perf: float | None = perf_6m - spy_6m
        horizon: str | None = "6m"
    elif perf_3m is not None and spy_3m is not None:
        rel_perf = perf_3m - spy_3m
        horizon = "3m"
    else:
        rel_perf = None
        horizon = None

    rs_accel = None
    if perf_1m is not None and spy_1m is not None and rel_perf is not None:
        rel_1m = perf_1m - spy_1m
        months = 6 if horizon == "6m" else 3
        rs_accel = rel_1m - rel_perf / months
    return rel_perf, horizon, rs_accel


def penalty_flags(
    dist_ema200: float | None,
    atr_pct: float | None,
    vol_ratio: float | None,
    rsi_val: float | None,
    close: float,
    sma50: float | None,
) -> list[str]:
    flags: list[str] = []
    if dist_ema200 is not None and dist_ema200 > 25:
        flags.append("extendido_vs_ema200")
    if atr_pct is not None and atr_pct > 5:
        flags.append("atr_elevado")
    if vol_ratio is not None and vol_ratio > 1.5 and sma50 is not None and close < sma50:
        flags.append("posible_distribucion")
    if rsi_val is not None and rsi_val > 78:
        flags.append("rsi_sobrecompra")
    if rsi_val is not None and rsi_val < 22:
        flags.append("rsi_sobreventa")
    return flags


# --- Main pipeline ----------------------------------------------------------

def week_range(today: date | None = None) -> tuple[str, str]:
    d = today or date.today()
    # Lunes de la semana actual → domingo
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def fetch_earnings(symbols: set[str], finnhub_key: str) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    if not finnhub_key:
        notes.append("Finnhub: sin API key — earnings omitidos")
        return [], notes
    frm, to = week_range()
    url = (
        "https://finnhub.io/api/v1/calendar/earnings?"
        + urllib.parse.urlencode({"from": frm, "to": to, "token": finnhub_key})
    )
    try:
        data = http_get_json(url, timeout=45)
    except Exception as e:
        notes.append(f"Finnhub earnings falló (soft): {type(e).__name__}")
        return [], notes
    raw = (data or {}).get("earningsCalendar") or (data or {}).get("earnings") or []
    out = []
    for row in raw:
        sym = (row.get("symbol") or "").upper()
        if sym not in symbols:
            continue
        hour = row.get("hour") or row.get("time") or ""
        # Finnhub: bmo / amc / dmh
        timing = str(hour).lower()
        if timing in ("bmo", "amc", "dmh"):
            label = timing.upper()
        else:
            label = timing or None
        out.append(
            {
                "symbol": sym,
                "date": row.get("date"),
                "hour": label,
                "epsEstimate": row.get("epsEstimate"),
                "epsActual": row.get("epsActual"),
                "revenueEstimate": row.get("revenueEstimate"),
                "revenueActual": row.get("revenueActual"),
            }
        )
    out.sort(key=lambda x: (x.get("date") or "", x.get("symbol") or ""))
    notes.append(f"Finnhub: {len(out)} earnings en universo ({frm} → {to})")
    return out, notes


def compute_symbol(
    meta: dict,
    bars: list[dict],
    spy_closes: list[float],
    rs_raw_map: dict[str, float],
) -> dict | None:
    if len(bars) < 60:
        return None
    closes = [float(b["c"]) for b in bars]
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    vols = [float(b.get("v") or 0) for b in bars]
    dates = [b.get("t") for b in bars]

    ema200_s = ema(closes, 200)
    sma50_s = sma(closes, 50)
    sma10_s = sma(closes, 10)
    rsi_s = rsi(closes, 14)
    atr_s = atr(highs, lows, closes, 14)

    close = closes[-1]
    ema200_v = ema200_s[-1]
    sma50_v = sma50_s[-1]
    sma10_v = sma10_s[-1]
    rsi_v = rsi_s[-1]
    atr_v = atr_s[-1]

    ema200_prev = ema200_s[-6] if len(ema200_s) >= 6 else None
    sma50_prev = sma50_s[-6] if len(sma50_s) >= 6 else None

    dist_ema200 = ((close / ema200_v) - 1) * 100 if ema200_v else None
    dist_sma50 = ((close / sma50_v) - 1) * 100 if sma50_v else None

    vol20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else None
    vol_rel = (vols[-1] / vol20) if vol20 and vol20 > 0 else None

    # ATR ratio vs ~60d avg of ATR
    atr_vals = [x for x in atr_s[-60:] if x is not None]
    atr_avg = sum(atr_vals) / len(atr_vals) if atr_vals else None
    atr_ratio = (atr_v / atr_avg) if atr_v and atr_avg else None
    atr_pct = (atr_v / close * 100) if atr_v and close else None

    rv20 = realized_vol(closes, 20)
    rv60 = realized_vol(closes, 60)

    # Relative strength vs SPY: 126d (~6m) performance vs SPY, percentile later.
    rel_perf, horizon, rs_accel = relative_performance(closes, spy_closes)

    change_pct = None
    if len(closes) >= 2 and closes[-2]:
        change_pct = (close / closes[-2] - 1.0) * 100.0

    if ema200_v is None:
        relation = None
    elif close > ema200_v:
        relation = "above"
    elif close < ema200_v:
        relation = "below"
    else:
        relation = "equal"
    slope_up = None
    slope_pct = None
    if ema200_v and ema200_prev:
        slope_up = ema200_v > ema200_prev
        slope_pct = (ema200_v / ema200_prev - 1.0) * 100.0

    tend = score_tendencia(close, sma50_v, ema200_v, sma50_prev, ema200_prev)
    # fuerza uses placeholder RS; filled after percentile
    contr = score_contraccion(rsi_v, atr_ratio, vol_rel, rv20, rv60)
    setup = score_setup(dist_ema200, dist_sma50, vol_rel, rsi_v)
    flags = penalty_flags(dist_ema200, atr_pct, vol_rel, rsi_v, close, sma50_v)

    return {
        "symbol": meta["symbol"],
        "name": meta.get("name"),
        "kind": meta.get("kind"),
        "sector": meta.get("sector"),
        "close": safe_round(close, 2),
        "change_pct": safe_round(change_pct, 2),
        "asof": dates[-1],
        "bars": len(bars),
        "ema200": safe_round(ema200_v, 2),
        "ema200_slope_up": slope_up,
        "ema200_slope_pct": safe_round(slope_pct, 2),
        "trend_gate": trend_gate_label(relation, slope_up),
        "range_52w": range_52w(highs, lows, close),
        "sma50": safe_round(sma50_v, 2),
        "sma10": safe_round(sma10_v, 2),
        "rsi14": safe_round(rsi_v, 1),
        "dist_ema200_pct": safe_round(dist_ema200, 2),
        "dist_sma50_pct": safe_round(dist_sma50, 2),
        "vol_rel_20d": safe_round(vol_rel, 2),
        "atr14_pct": safe_round(atr_pct, 2),
        "atr_ratio": safe_round(atr_ratio, 2),
        "rv20": safe_round(rv20, 1),
        "rel_perf": safe_round(rel_perf, 2),
        "rel_horizon": horizon,
        "rs_accel": safe_round(rs_accel, 2),
        "rs_score": None,  # filled later
        "pillars": {
            "tendencia": safe_round(tend, 1),
            "fuerza_rs": None,
            "contraccion": safe_round(contr, 1),
            "setup": safe_round(setup, 1),
        },
        "desk_score": None,
        "above_ema200": bool(ema200_v is not None and close > ema200_v),
        "above_sma50": bool(sma50_v is not None and close > sma50_v),
        "flags": flags,
        "_rel_perf_raw": rel_perf,
        "_tend": tend,
        "_contr": contr,
        "_setup": setup,
        "_rs_accel": rs_accel,
    }


def percentile_rank(values: list[float], x: float) -> float:
    """Percentile rank 0-100 of x among values (inclusive average rank)."""
    if not values:
        return 50.0
    below = sum(1 for v in values if v < x)
    equal = sum(1 for v in values if v == x)
    return (below + 0.5 * equal) / len(values) * 100.0


def apply_cross_section_scores(rows: list[dict]) -> list[dict]:
    """Percentil de RS, pilar Fuerza, penalizaciones suaves, Desk Score, orden y rank.

    Misma fórmula que el ranking publicado. Mutates each row (drops keys `_`).
    """
    rels = [r["_rel_perf_raw"] for r in rows if r["_rel_perf_raw"] is not None]
    for r in rows:
        if r["_rel_perf_raw"] is None:
            rs = 50.0
        else:
            rs = percentile_rank(rels, r["_rel_perf_raw"])
        r["rs_score"] = safe_round(rs, 1)
        fuerza = score_fuerza_rs(rs, r["_rs_accel"])
        r["pillars"]["fuerza_rs"] = safe_round(fuerza, 1)
        r["pillar_points"] = pillar_points_block(r["_tend"], fuerza, r["_contr"], r["_setup"])
        ds = desk_score(r["_tend"], fuerza, r["_contr"], r["_setup"])
        # Soft penalty for flags
        if "extendido_vs_ema200" in r["flags"]:
            ds = clamp(ds - 5)
        if "posible_distribucion" in r["flags"]:
            ds = clamp(ds - 4)
        if "atr_elevado" in r["flags"]:
            ds = clamp(ds - 3)
        r["desk_score"] = safe_round(ds, 1)
        for k in list(r.keys()):
            if k.startswith("_"):
                del r[k]
    rows.sort(key=lambda x: (-(x["desk_score"] or 0), x["symbol"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


WINDOW_SESSIONS = 10
# Sesiones hacia atrás para fechar la racha actual en el Top 10 (sin estado persistido).
ENTRY_LOOKBACK_SESSIONS = 30
TOP10_ENTRY_NOTE = (
    "Racha actual en el Top 10: Desk Score recomputado al cierre de cada una de las "
    f"últimas {ENTRY_LOOKBACK_SESSIONS} sesiones, truncando las barras de Alpaca ya descargadas "
    "(sin llamadas extra a la API). Earnings, logos y el resto de Finnhub no entran en el score, "
    "así que no hace falta aproximarlos ni dejarlos fijos. "
    "Si la racha cubre toda la ventana: «antes del DD/MM · >N ruedas»."
)


def has_exact_session(bars: list[dict], session: str) -> bool:
    """True si alguna barra cae exactamente en la sesión YYYY-MM-DD. Serie ascendente."""
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        d = bar_session_date(bars[mid])
        if d < session:
            lo = mid + 1
        elif d > session:
            hi = mid
        else:
            return True
    return False


def weekly_close_dates(dates: list[str], weeks: int = RS_WEEKLY_WEEKS) -> list[str]:
    """Última sesión de cada semana ISO, las `weeks` más recientes (incluye la semana en curso)."""
    if weeks < 1:
        return []
    last_of: dict[tuple[int, int], str] = {}
    order: list[tuple[int, int]] = []
    for d in dates:
        if len(d) < 10:
            continue
        try:
            y, m, day = int(d[0:4]), int(d[5:7]), int(d[8:10])
            iso = date(y, m, day).isocalendar()
        except ValueError:
            continue
        key = (int(iso[0]), int(iso[1]))
        if key not in last_of:
            order.append(key)
        last_of[key] = d
    return [last_of[k] for k in order[-weeks:]]


def compute_rs_weekly(
    all_bars: dict[str, list[dict]], weeks: int = RS_WEEKLY_WEEKS
) -> dict[str, Any]:
    """RS Score (percentil de rel_perf vs SPY) en cada cierre semanal.

    `by_symbol[sym]` alinea con `dates` (None si ese día no hay barra o no hay rel_perf).
    El último punto publicado lo pisa `attach_rs_weekly` con el RS Score del ranking.
    """
    spy = all_bars.get("SPY") or []
    dates = weekly_close_dates(session_dates_from_bars(spy), weeks)
    by: dict[str, list[float | None]] = {sym: [None] * len(dates) for sym in all_bars}
    for i, d in enumerate(dates):
        if not has_exact_session(spy, d):
            continue
        spy_closes = [float(b["c"]) for b in bars_through(spy, d) if b.get("c") is not None]
        rels: dict[str, float] = {}
        for sym, bars in all_bars.items():
            if not has_exact_session(bars, d):
                continue
            closes = [float(b["c"]) for b in bars_through(bars, d) if b.get("c") is not None]
            rel, _horizon, _accel = relative_performance(closes, spy_closes)
            if rel is not None:
                rels[sym] = rel
        universe = list(rels.values())
        for sym, rel in rels.items():
            by[sym][i] = safe_round(percentile_rank(universe, rel), 1)
    return {
        "weeks": len(dates),
        "dates": dates,
        "definition": RS_WEEKLY_DEFINITION,
        "by_symbol": by,
    }


def attach_rs_weekly(rows: list[dict], block: dict) -> None:
    """Copia la serie semanal a cada fila. El último punto es el RS Score publicado."""
    dates = block.get("dates") or []
    by = block.get("by_symbol") or {}
    n = len(dates)
    for r in rows or []:
        seq = list(by.get(r.get("symbol")) or [None] * n)
        if len(seq) < n:
            seq.extend([None] * (n - len(seq)))
        seq = seq[:n]
        if seq and r.get("rs_score") is not None:
            seq[-1] = r["rs_score"]
        r["rs_weekly"] = seq


def rs_weekly_public(block: dict | None) -> dict[str, Any]:
    """Bloque de datos.json: fechas compartidas + definición. Las series van en cada fila."""
    block = block or {}
    return {
        "weeks": block.get("weeks") or 0,
        "dates": list(block.get("dates") or []),
        "definition": block.get("definition") or RS_WEEKLY_DEFINITION,
    }


def session_return_pct(closes: list[float], sessions: int = WINDOW_SESSIONS) -> float | None:
    """Return over last `sessions` trading days: (close[-1]/close[-(sessions+1)] - 1)*100."""
    need = sessions + 1
    if len(closes) < need:
        return None
    base = closes[-need]
    last = closes[-1]
    if base is None or last is None or base == 0:
        return None
    return (last / base - 1.0) * 100.0


def spark_closes(closes: list[float], sessions: int = WINDOW_SESSIONS) -> list[float]:
    """Oldest→newest closes spanning the return window (sessions+1 points)."""
    need = sessions + 1
    chunk = closes[-need:] if len(closes) >= need else list(closes)
    return [safe_round(float(c), 4) or 0.0 for c in chunk]


def compute_top10_return(
    ranking: list[dict],
    bars_by_symbol: dict[str, list[dict]],
    window: int = WINDOW_SESSIONS,
) -> dict[str, Any]:
    """Build top10_return block from ranking + daily bars (symbol -> Alpaca bars)."""
    top = sorted(
        [r for r in ranking if r.get("symbol")],
        key=lambda r: (-(r.get("desk_score") or 0), r.get("symbol") or ""),
    )[:10]

    asof = None
    rows_out: list[dict] = []
    returns_for_avg: list[float] = []

    for i, r in enumerate(top, 1):
        sym = r["symbol"]
        bars = bars_by_symbol.get(sym) or []
        closes = [float(b["c"]) for b in bars if b.get("c") is not None]
        ret = session_return_pct(closes, window)
        if ret is None:
            continue
        if bars:
            t = bars[-1].get("t")
            if t and (asof is None or str(t) > str(asof)):
                asof = t
        ret_r = safe_round(ret, 2)
        returns_for_avg.append(float(ret_r) if ret_r is not None else ret)
        rows_out.append(
            {
                "rank": i,
                "symbol": sym,
                "desk_score": r.get("desk_score"),
                "return_pct": ret_r,
                "spark": spark_closes(closes, window),
            }
        )

    # Re-rank display ranks 1..n among included rows (keep desk_score order via enumerate above)
    for i, row in enumerate(rows_out, 1):
        row["rank"] = i

    spy_bars = bars_by_symbol.get("SPY") or []
    spy_closes = [float(b["c"]) for b in spy_bars if b.get("c") is not None]
    spy_ret = session_return_pct(spy_closes, window)
    if spy_bars and asof is None:
        asof = spy_bars[-1].get("t")

    avg = None
    if returns_for_avg:
        avg = safe_round(sum(returns_for_avg) / len(returns_for_avg), 2)

    return {
        "window_sessions": window,
        "asof": asof,
        "avg_return_pct": avg,
        "spy_return_pct": safe_round(spy_ret, 2) if spy_ret is not None else None,
        "rows": rows_out,
    }


def bar_session_date(bar: dict) -> str:
    """Fecha de sesión YYYY-MM-DD a partir del timestamp de Alpaca (`t`)."""
    return str(bar.get("t") or "")[:10]


def session_dates_from_bars(bars: list[dict]) -> list[str]:
    dates: list[str] = []
    seen: set[str] = set()
    for b in bars:
        d = bar_session_date(b)
        if len(d) == 10 and d[4] == "-" and d not in seen:
            seen.add(d)
            dates.append(d)
    return dates


def bars_through(bars: list[dict], session: str) -> list[dict]:
    """Barras con fecha de sesión <= `session`. La serie viene ordenada ascendente."""
    if not bars or not session:
        return []
    last = bar_session_date(bars[-1])
    if len(last) == 10 and last <= session:
        return bars
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if bar_session_date(bars[mid]) <= session:
            lo = mid + 1
        else:
            hi = mid
    return bars[:lo]


def _ddmm(iso_date: str) -> str:
    if len(iso_date) >= 10 and iso_date[4] == "-" and iso_date[7] == "-":
        return f"{iso_date[8:10]}/{iso_date[5:7]}"
    return iso_date


def format_entro(
    entry_date: str | None,
    sessions: int,
    censored: bool,
    bound_date: str,
    lookback: int,
) -> dict[str, Any]:
    """«DD/MM · N ruedas», o «antes del DD/MM · >N ruedas» si la racha tapa toda la ventana."""
    if censored:
        n = lookback if lookback > 0 else sessions
        label = f"antes del {_ddmm(bound_date)} · >{n} ruedas"
        return {
            "date": None,
            "earliest_seen": bound_date,
            "sessions": sessions,
            "lookback_sessions": n,
            "censored": True,
            "label": label,
        }
    ruedas = "rueda" if sessions == 1 else "ruedas"
    label = f"{_ddmm(entry_date or '')} · {sessions} {ruedas}"
    return {
        "date": entry_date,
        "earliest_seen": entry_date,
        "sessions": sessions,
        "lookback_sessions": lookback,
        "censored": False,
        "label": label,
    }


def streaks_from_membership(
    membership_oldest_first: list[tuple[str, list[str]]],
) -> dict[str, dict]:
    """Racha ininterrumpida hasta hoy de cada símbolo del Top 10 de la última sesión.

    `membership_oldest_first`: [(YYYY-MM-DD, símbolos del Top 10 en orden de rank), ...]
    de la sesión más antigua a la más reciente. Si el símbolo está en todas las sesiones,
    no se observó la salida y la entrada queda censurada.
    """
    if not membership_oldest_first:
        return {}
    window_len = len(membership_oldest_first)
    oldest = membership_oldest_first[0][0]
    by_date = {d: set(syms) for d, syms in membership_oldest_first}
    out: dict[str, dict] = {}
    for sym in membership_oldest_first[-1][1]:
        if not sym or sym in out:
            continue
        sessions = 0
        entry = membership_oldest_first[-1][0]
        for d, _syms in reversed(membership_oldest_first):
            if sym in by_date[d]:
                sessions += 1
                entry = d
            else:
                break
        censored = sessions == window_len
        out[sym] = format_entro(
            None if censored else entry,
            sessions,
            censored,
            oldest if censored else entry,
            window_len,
        )
    return out


def rank_universe_asof(
    meta_by: dict[str, dict],
    all_bars: dict[str, list[dict]],
    session: str,
) -> list[dict]:
    """Ranking Desk Score con cada serie truncada en `session` (inclusive)."""
    spy_bars = bars_through(all_bars.get("SPY") or [], session)
    if len(spy_bars) < 60:
        return []
    spy_closes = [float(b["c"]) for b in spy_bars]
    rows: list[dict] = []
    for sym, bars in all_bars.items():
        meta = meta_by.get(sym) or {"symbol": sym}
        row = compute_symbol(meta, bars_through(bars, session), spy_closes, {})
        if row:
            rows.append(row)
    return apply_cross_section_scores(rows)


def compute_top10_entry(
    meta_by: dict[str, dict],
    all_bars: dict[str, list[dict]],
    lookback: int = ENTRY_LOOKBACK_SESSIONS,
    today_rows: list[dict] | None = None,
) -> dict[str, Any]:
    """Fecha en que cada miembro del Top 10 actual entró en su racha ininterrumpida.

    Recomputa el ranking al cierre de cada una de las últimas `lookback` sesiones de SPY
    con las barras ya en memoria. `today_rows` (ranking publicado) fija la membresía de
    la última sesión para que la racha coincida con el Top 10 que ve la UI.
    """
    empty = {
        "lookback_sessions": lookback,
        "sessions_evaluated": 0,
        "window_start": None,
        "window_end": None,
        "by_symbol": {},
        "note": TOP10_ENTRY_NOTE,
    }
    spy_bars = all_bars.get("SPY") or []
    dates = session_dates_from_bars(spy_bars)
    if not dates or lookback < 1:
        return empty
    valid = [d for d in dates[-lookback:] if len(bars_through(spy_bars, d)) >= 60]
    if not valid:
        return empty
    last = valid[-1]
    membership: list[tuple[str, list[str]]] = []
    for d in valid:
        if today_rows is not None and d == last:
            top = [r["symbol"] for r in today_rows[:10] if r.get("symbol")]
        else:
            ranked = rank_universe_asof(meta_by, all_bars, d)
            top = [r["symbol"] for r in ranked[:10]]
        membership.append((d, top))
    return {
        "lookback_sessions": lookback,
        "sessions_evaluated": len(valid),
        "window_start": valid[0],
        "window_end": last,
        "by_symbol": streaks_from_membership(membership),
        "note": TOP10_ENTRY_NOTE,
    }


def attach_entro(ranking: list[dict], top10: dict | None, streaks: dict[str, dict]) -> None:
    """Copia `entro` al ranking (null fuera del Top 10 actual) y a las filas del panel."""
    for r in ranking or []:
        sym = r.get("symbol")
        r["entro"] = streaks.get(sym) if sym in streaks else None
    if not top10:
        return
    for row in top10.get("rows") or []:
        sym = row.get("symbol")
        row["entro"] = streaks.get(sym) if sym in streaks else None


def copy_entro_from_ranking(ranking: list[dict], top10: dict | None) -> None:
    """Reaplica `entro` ya calculado (p. ej. patch de retornos, sin rehacer el universo)."""
    by = {r.get("symbol"): r.get("entro") for r in ranking or [] if r.get("symbol")}
    if not top10:
        return
    for row in top10.get("rows") or []:
        row["entro"] = by.get(row.get("symbol"))


def main() -> None:
    alpaca_headers()  # falla temprano y claro si faltan keys (sin imprimirlas)
    if not load_finnhub_key():
        print("AVISO: no hay FINNHUB_API_KEY — earnings omitidos, logos sólo desde cache")
    notes: list[str] = []
    failures: list[str] = []

    universe = json.loads(UNIVERSE_PATH.read_text())
    symbols = [u["symbol"] for u in universe]
    meta_by = {u["symbol"]: u for u in universe}

    end_dt = datetime.now(timezone.utc).date()
    start_dt = end_dt - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    start_s = start_dt.isoformat() + "T00:00:00Z"
    end_s = end_dt.isoformat() + "T23:59:59Z"

    print(f"Desk Dashboard build — {len(symbols)} símbolos, {start_s[:10]} → {end_s[:10]}")

    all_bars: dict[str, list[dict]] = {}
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i : i + BATCH_SIZE]
        try:
            got = fetch_bars_batch(batch, start_s, end_s)
            for s in batch:
                bars = got.get(s) or []
                if len(bars) < 60:
                    failures.append(f"{s}: insuficientes barras ({len(bars)})")
                    print(f"  SKIP {s}: {len(bars)} bars")
                else:
                    all_bars[s] = bars
                    print(f"  OK   {s}: {len(bars)} bars")
        except Exception as e:
            for s in batch:
                failures.append(f"{s}: fetch error {type(e).__name__}: {e}")
                print(f"  FAIL batch {batch}: {e}")
            # retry one-by-one
            for s in batch:
                if s in all_bars:
                    continue
                try:
                    time.sleep(0.4)
                    got = fetch_bars_batch([s], start_s, end_s)
                    bars = got.get(s) or []
                    if len(bars) >= 60:
                        all_bars[s] = bars
                        failures = [f for f in failures if not f.startswith(f"{s}:")]
                        print(f"  OK   {s} (retry): {len(bars)} bars")
                    else:
                        print(f"  SKIP {s} (retry): {len(bars)} bars")
                except Exception as e2:
                    print(f"  FAIL {s}: {e2}")
        time.sleep(SLEEP_BETWEEN_BATCHES)

    if "SPY" not in all_bars:
        raise SystemExit("SPY es obligatorio como benchmark y no se pudo obtener")

    spy_closes = [float(b["c"]) for b in all_bars["SPY"]]

    rows: list[dict] = []
    for sym, bars in all_bars.items():
        row = compute_symbol(meta_by[sym], bars, spy_closes, {})
        if row:
            rows.append(row)
        else:
            failures.append(f"{sym}: compute falló")

    # RS Score (percentil en el universo) + Desk Score + rank
    apply_cross_section_scores(rows)
    rs_weekly = compute_rs_weekly(all_bars, RS_WEEKLY_WEEKS)
    attach_rs_weekly(rows, rs_weekly)
    rs_dates = rs_weekly.get("dates") or []
    if rs_dates:
        notes.append(
            f"RS semanal: {len(rs_dates)} cierres ({rs_dates[0]} → {rs_dates[-1]})."
        )

    # KPIs (universe excl. pure benchmarks optional — include all scored)
    n = len(rows)
    above_ema = sum(1 for r in rows if r["above_ema200"])
    above_sma = sum(1 for r in rows if r["above_sma50"])
    rs70 = sum(1 for r in rows if (r["rs_score"] or 0) > 70)
    unusual = sum(1 for r in rows if (r["vol_rel_20d"] or 0) > 1.5)

    # Régimen real: % del universo sobre EMA200 (+ soft override SPY)
    pct_ema = (above_ema / n * 100) if n else 0.0
    pct_ema_r = safe_round(pct_ema, 1)
    rule = "alcista if pct_above_ema200>=60; mixto if 40–60; bajista if <40; soft override: SPY under EMA200 + alcista → mixto"
    if pct_ema >= 60:
        label_raw = "alcista"
    elif pct_ema >= 40:
        label_raw = "mixto"
    else:
        label_raw = "bajista"

    spy_row = next((r for r in rows if r["symbol"] == "SPY"), None)
    spy_above = spy_row["above_ema200"] if spy_row else None
    spy_dist = spy_row["dist_ema200_pct"] if spy_row else None
    asof_regime = (spy_row or (rows[0] if rows else {})).get("asof")

    label = label_raw
    override_note = None
    if spy_above is False and label_raw == "alcista":
        label = "mixto"
        override_note = "soft_override: SPY bajo EMA200 → alcista rebajado a mixto"

    regime_obj = {
        "label": label,
        "pct_above_ema200": pct_ema_r,
        "spy_above_ema200": spy_above,
        "spy_dist_ema200_pct": spy_dist,
        "rule": rule,
        "asof": asof_regime,
        "label_raw": label_raw,
    }
    if override_note:
        regime_obj["override"] = override_note

    finnhub_key = load_finnhub_key()
    earnings, e_notes = fetch_earnings(set(all_bars.keys()), finnhub_key)
    notes.extend(e_notes)
    if failures:
        notes.append(f"Símbolos omitidos/fallidos: {len(failures)}")
    notes.append(
        f"Régimen: {label} ({pct_ema_r}% sobre EMA200"
        + (f"; SPY dist EMA200 {spy_dist}%" if spy_dist is not None else "")
        + ")"
    )
    if override_note:
        notes.append(override_note)
    notes.append(
        "UI: Actualizar / auto cada 5 min solo recarga datos.json; los datos se refrescan con python3 build.py (o cron)."
    )

    generated_at = datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=-3))
    ).isoformat(timespec="seconds")

    top10_return = compute_top10_return(rows, all_bars, WINDOW_SESSIONS)
    notes.append(
        f"Retorno Top 10 ({WINDOW_SESSIONS} ruedas): medio {top10_return.get('avg_return_pct')}% · SPY {top10_return.get('spy_return_pct')}%"
    )
    top10_entry = compute_top10_entry(
        meta_by, all_bars, ENTRY_LOOKBACK_SESSIONS, today_rows=rows
    )
    attach_entro(rows, top10_return, top10_entry.get("by_symbol") or {})
    if top10_entry.get("by_symbol"):
        bits = [
            f"{sym} {info.get('label')}"
            for sym, info in top10_entry["by_symbol"].items()
        ]
        notes.append(
            f"Entró Top 10 (ventana {top10_entry.get('sessions_evaluated')} sesiones, "
            f"{top10_entry.get('window_start')} → {top10_entry.get('window_end')}): "
            + " · ".join(bits)
        )

    payload = {
        "generated_at": generated_at,
        "timezone": "America/Buenos_Aires",
        "brand": "Desk Dashboard",
        "kpis": {
            "activos": n,
            "above_ema200": above_ema,
            "above_ema200_pct": pct_ema_r,
            "above_sma50": above_sma,
            "above_sma50_pct": safe_round(above_sma / n * 100 if n else 0, 1),
            "rs_gt_70": rs70,
            "rs_gt_70_pct": safe_round(rs70 / n * 100 if n else 0, 1),
            "volumen_inusual": unusual,
            "volumen_inusual_pct": safe_round(unusual / n * 100 if n else 0, 1),
        },
        "regime": regime_obj,
        "regime_stub": regime_obj,  # alias back-compat
        "top10_return": top10_return,
        "top10_entry": top10_entry,
        "rs_weekly": rs_weekly_public(rs_weekly),
        "ranking": rows,
        "earnings": earnings,
        "failures": failures,
        "notes": notes,
        "formulas": {
            "desk_score": "0.25*Tendencia + 0.30*Fuerza_RS + 0.30*Contracción + 0.15*Setup (cada pilar 0–100)",
            "rs_score": "Percentil 0–100 de (retorno_stock − retorno_SPY) en ~126 sesiones (6m; fallback 63d/3m)",
            "tendencia": "Precio vs SMA50/EMA200 + pendientes (~5d) + SMA50>EMA200",
            "fuerza_rs": "0.75*RS_score + bonus por aceleración relativa 1m",
            "contraccion": "Proxy VCP: ratio ATR actual/ATR~60d, vol realizada 20/60, RSI no extremo, dry-up volumen",
            "setup": "Cercanía a EMA200/SMA50 + dry-up volumen + RSI neutro",
            "vol_rel_20d": "Volumen último día / media 20 sesiones",
            "dist_ema200_pct": "(close/EMA200 − 1) * 100",
            "regime": rule,
            "top10_return": f"(close[-1]/close[-{WINDOW_SESSIONS + 1}] - 1)*100 sobre últimas {WINDOW_SESSIONS} ruedas; avg = media de los Top 10 con retorno válido; SPY misma ventana",
            "top10_entry": TOP10_ENTRY_NOTE,
            "pillar_points": "Puntos del pilar = score 0–100 × peso (Tendencia 0.25, Fuerza RS 0.30, Contracción 0.30, Setup 0.15), antes de las penalizaciones suaves del Desk Score",
            "range_52w": f"Mínimo y máximo de high/low en las últimas {RANGE_52W_SESSIONS} sesiones (o las disponibles). position_pct = (close − mín) / (máx − mín) × 100",
            "change_pct": "(close / close anterior − 1) × 100",
            "trend_gate": "Precio frente a EMA200 y pendiente de la EMA200 contra su valor de ~5 sesiones atrás",
            "rs_weekly": RS_WEEKLY_DEFINITION,
        },
        "disclaimer": "No es recomendación de compra ni de inversión. Uso interno / educativo.",
    }

    # Logos (soft: nunca rompe el build)
    logo_syms = [logo_symbol(u) for u in universe]
    try:
        logo_map, l_notes = fetch_logos(logo_syms, finnhub_key)
        payload["notes"].extend(l_notes)
    except Exception as e:
        print(f"  logos falló (soft): {type(e).__name__}")
        logo_map = logo_map_from_cache(logo_syms)
    attach_logos(payload, logo_map)

    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"\nEscrito {OUT_PATH} — {n} tickers scored, régimen={label}")
    print("Top 5:")
    for r in rows[:5]:
        print(f"  #{r['rank']} {r['symbol']:6} desk={r['desk_score']} RS={r['rs_score']}")
    t10 = payload.get("top10_return") or {}
    print(
        f"Retorno Top 10 ({t10.get('window_sessions')} ruedas): "
        f"avg={t10.get('avg_return_pct')}% SPY={t10.get('spy_return_pct')}% "
        f"n={len(t10.get('rows') or [])}"
    )
    print(
        f"Entró Top 10 ({top10_entry.get('sessions_evaluated')} sesiones, "
        f"{top10_entry.get('window_start')} → {top10_entry.get('window_end')}):"
    )
    for sym, info in (top10_entry.get("by_symbol") or {}).items():
        print(f"  {sym:6} {info.get('label')}")
    if failures:
        print(f"Fallos/omitidos ({len(failures)}):")
        for f in failures[:20]:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
