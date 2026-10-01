#!/usr/bin/env python3
"""Corrida de Angus: intradía con el mercado abierto, o cierre.

El cron de las 18:30 ART (21:30 UTC, lun–vie) siempre es cierre.
Los otros cron cubren 9:30–16:00 ET cada 30 minutos, en horario de verano
(EDT, UTC-4 → 13:30–20:00 UTC) y de invierno (EST, UTC-5 → 14:30–21:00 UTC).
Argentina queda en UTC-3 todo el año.

Si esa ventana cae con el mercado cerrado (feriado, o el extremo que no
aplica en esta estación), Alpaca `/v2/clock` lo dice y la corrida se saltea.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

# Lun–vie 21:30 UTC = 18:30 ART. Después de las 16:00 ET en verano y en invierno.
CLOSE_CRON = "30 21 * * 1-5"

# Cada 30 min en la unión UTC de la rueda de Nueva York:
# 13:30 (apertura en verano) … 21:00 (cierre en invierno).
INTRADAY_CRONS = (
    "30 13 * * 1-5",
    "0,30 14-20 * * 1-5",
    "0 21 * * 1-5",
)

LIVE_BANNER = "En vivo · provisorio hasta el cierre · precios con ~15 min de demora"

# Horario regular. El reloj de Alpaca es el que conoce feriados.
NY_OPEN_MINUTES = 9 * 60 + 30
NY_CLOSE_MINUTES = 16 * 60


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def trading_hosts() -> list[str]:
    """Live primero. Si la clave es de paper, el 401 prueba el otro host."""
    custom = _env("ALPACA_TRADING_URL", "ALPACA_BASE_URL", "APCA_API_BASE_URL").rstrip("/")
    hosts: list[str] = []
    if custom:
        hosts.append(custom)
    for host in ("https://api.alpaca.markets", "https://paper-api.alpaca.markets"):
        if host not in hosts:
            hosts.append(host)
    return hosts


def alpaca_key_headers() -> dict[str, str] | None:
    key = _env("ALPACA_API_KEY", "APCA_API_KEY_ID")
    secret = _env("ALPACA_SECRET_KEY", "APCA_API_SECRET_KEY")
    if not key or not secret:
        return None
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }


def _http_get_json(url: str, headers: dict[str, str], timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_clock(
    get: Callable[..., Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict | None:
    """GET /v2/clock. None si no se pudo leer. No imprime las claves."""
    hdrs = alpaca_key_headers() if headers is None else headers
    if not hdrs:
        print("Reloj Alpaca: sin claves, no se consulta /v2/clock.")
        return None
    getter = get or _http_get_json
    last_code: int | None = None
    for host in trading_hosts():
        url = host.rstrip("/") + "/v2/clock"
        try:
            data = getter(url, hdrs, timeout=20)
        except urllib.error.HTTPError as e:
            last_code = e.code
            if e.code in (401, 403):
                continue
            print(f"Reloj Alpaca: HTTP {e.code}")
            continue
        except Exception as e:
            if isinstance(e, AssertionError):
                raise
            print(f"Reloj Alpaca: {type(e).__name__}")
            continue
        if isinstance(data, dict) and "is_open" in data:
            return data
    if last_code:
        print(f"Reloj Alpaca: no se pudo leer /v2/clock (HTTP {last_code}).")
    return None


def clock_is_open(payload: Any) -> bool | None:
    if not isinstance(payload, dict) or "is_open" not in payload:
        return None
    return bool(payload["is_open"])


def ny_zone():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/New_York")
    except Exception:
        return timezone(timedelta(hours=-4))


def open_session_date(session_date: str | None, now: datetime) -> str | None:
    """Fecha de la barra solo si es hoy en Nueva York: esa rueda sigue abierta."""
    text = str(session_date or "")[:10]
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if text == now.astimezone(ny_zone()).date().isoformat():
        return text
    return None


def ny_session_open(now: datetime) -> bool:
    """9:30 inclusive a 16:00 exclusive, lun–vie, hora de Nueva York.

    No conoce feriados: para eso está `/v2/clock`. Sirve solo si el reloj
    no respondió en un push o una corrida manual.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(ny_zone())
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    return NY_OPEN_MINUTES <= minutes < NY_CLOSE_MINUTES


def detect_mode(
    event_name: str,
    schedule: str | None,
    is_open: bool | None,
    now: datetime | None = None,
) -> str:
    """`intradia`, `cierre` o `skip`.

    El cron de las 18:30 ART no se saltea. El de cada 30 min se saltea si
    el reloj no dice que la rueda está abierta (feriado, estación que no
    aplica, o reloj caído).
    """
    event = (event_name or "").strip().lower()
    sched = (schedule or "").strip()
    if event == "schedule" and sched == CLOSE_CRON:
        return "cierre"
    if event == "schedule" and sched in INTRADAY_CRONS:
        return "intradia" if is_open is True else "skip"
    if event == "schedule":
        return "skip"
    if is_open is True:
        return "intradia"
    if is_open is False:
        return "cierre"
    moment = now or datetime.now(timezone.utc)
    return "intradia" if ny_session_open(moment) else "cierre"


def records_persistent_state(mode: str) -> bool:
    """Solo el cierre escribe historial, simulación nueva y Finnhub lento."""
    return mode == "cierre"


def cierre_banner(session_date: str | None) -> str:
    text = str(session_date or "")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return f"Cierre del {text[8:10]}/{text[5:7]}"
    return "Cierre"


def session_banner(mode: str, session_date: str | None = None) -> str:
    if mode == "intradia":
        return LIVE_BANNER
    return cierre_banner(session_date)


def cron_covers_utc(hour: int, minute: int) -> bool:
    """True si algún cron intradía dispara a esa hora UTC (lun–vie)."""
    if minute == 30 and hour == 13:
        return True
    if hour == 21 and minute == 0:
        return True
    return 14 <= hour <= 20 and minute in (0, 30)


def nyse_slot_utc(et_minutes: int, utc_offset_hours: int) -> tuple[int, int]:
    """Minutos desde medianoche ET → (hora, minuto) UTC.

    `utc_offset_hours` es 4 en verano (EDT) y 5 en invierno (EST).
    """
    total = et_minutes + utc_offset_hours * 60
    return (total // 60) % 24, total % 60


def nyse_half_hours() -> list[int]:
    """9:30, 10:00, …, 16:00 en minutos desde medianoche."""
    start = NY_OPEN_MINUTES
    end = NY_CLOSE_MINUTES
    return list(range(start, end + 1, 30))


def write_github_output(mode: str, is_open: bool | None) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    open_s = "unknown" if is_open is None else ("true" if is_open else "false")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"mode={mode}\n")
        fh.write(f"open={open_s}\n")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    event = _env("ANGUS_EVENT") or _env("GITHUB_EVENT_NAME") or "local"
    schedule = os.environ.get("ANGUS_SCHEDULE")
    if schedule is None:
        schedule = os.environ.get("GITHUB_EVENT_SCHEDULE")
    now = datetime.now(timezone.utc)
    is_open: bool | None = None
    if event == "schedule" and (schedule or "").strip() == CLOSE_CRON:
        mode = "cierre"
    else:
        is_open = clock_is_open(fetch_clock())
        mode = detect_mode(event, schedule, is_open, now=now)
    print(f"evento={event} cron={schedule or '-'} abierto={is_open} modo={mode}")
    if "--github-output" in args:
        write_github_output(mode, is_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
