
"""BYS360 Anasayfa hava durumu ve saha öneri servisi.

Bu servis canlı arayüzün açılışını asla dış API'ye bağımlı hale getirmez.
Open-Meteo yanıt vermezse güvenli fallback bağlamı döner ve anasayfa çalışmaya
devam eder.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_LOCATION_NAME = "Gelibolu Tarihi Alan"
DEFAULT_LATITUDE = 40.247
DEFAULT_LONGITUDE = 26.280
DEFAULT_CACHE_MINUTES = 180
DEFAULT_TIMEOUT_SECONDS = 1  # BYS360_RUNTIME_SLOW_PAGES_V2_WEATHER_TIMEOUT

_CACHE: dict[str, tuple[datetime, dict[str, Any]]] = {}


@dataclass(frozen=True)
class WeatherSettings:
    provider: str
    enabled: bool
    location_name: str
    latitude: float
    longitude: float
    cache_minutes: int
    timeout_seconds: int


def _read_config_value(name: str, default: Any) -> Any:
    try:
        value = current_app.config.get(name, None)
    except RuntimeError:
        value = None
    if value is None or value == "":
        value = os.environ.get(name, default)
    return value


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "kapali", "hayir"}


def _as_float(value: Any, default: float) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int, minimum: int = 1, maximum: int = 360) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def get_weather_settings() -> WeatherSettings:
    provider = str(_read_config_value("WEATHER_PROVIDER", "open_meteo") or "open_meteo").strip().lower()
    return WeatherSettings(
        provider=provider,
        enabled=_as_bool(_read_config_value("WEATHER_ENABLED", "true"), default=True),
        location_name=str(_read_config_value("WEATHER_LOCATION_NAME", DEFAULT_LOCATION_NAME) or DEFAULT_LOCATION_NAME),
        latitude=_as_float(_read_config_value("WEATHER_LAT", DEFAULT_LATITUDE), DEFAULT_LATITUDE),
        longitude=_as_float(_read_config_value("WEATHER_LON", DEFAULT_LONGITUDE), DEFAULT_LONGITUDE),
        cache_minutes=_as_int(_read_config_value("WEATHER_CACHE_MINUTES", DEFAULT_CACHE_MINUTES), DEFAULT_CACHE_MINUTES, 5, 360),
        timeout_seconds=_as_int(_read_config_value("WEATHER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS), DEFAULT_TIMEOUT_SECONDS, 1, 15),
    )


def _weather_code_label(code: Any) -> str:
    labels = {
        0: "Açık",
        1: "Az bulutlu",
        2: "Parçalı bulutlu",
        3: "Kapalı",
        45: "Sis",
        48: "Kırağılı sis",
        51: "Hafif çisenti",
        53: "Çisenti",
        55: "Yoğun çisenti",
        61: "Hafif yağmur",
        63: "Yağmur",
        65: "Kuvvetli yağmur",
        71: "Hafif kar",
        73: "Kar",
        75: "Kuvvetli kar",
        80: "Kısa süreli yağmur",
        81: "Sağanak",
        82: "Kuvvetli sağanak",
        95: "Gök gürültülü fırtına",
        96: "Dolu riski",
        99: "Kuvvetli dolu riski",
    }
    try:
        return labels.get(int(code), "Tahmin alındı")
    except (TypeError, ValueError):
        return "Tahmin alındı"


def _first(sequence: Any, default: Any = None) -> Any:
    if isinstance(sequence, list) and sequence:
        return sequence[0]
    return default


def _build_open_meteo_url(settings: WeatherSettings) -> str:
    params = {
        "latitude": f"{settings.latitude:.6f}",
        "longitude": f"{settings.longitude:.6f}",
        "current": ",".join([
            "temperature_2m",
            "apparent_temperature",
            "relative_humidity_2m",
            "precipitation",
            "rain",
            "weather_code",
            "wind_speed_10m",
            "wind_gusts_10m",
        ]),
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "wind_speed_10m_max",
        ]),
        "timezone": "auto",
        "forecast_days": "1",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    return f"{OPEN_METEO_FORECAST_URL}?{urlencode(params)}"


def _fetch_open_meteo(settings: WeatherSettings) -> dict[str, Any]:
    request = Request(
        _build_open_meteo_url(settings),
        headers={"User-Agent": "BYS360-HomeWeather/1.0"},
    )
    with urlopen(request, timeout=settings.timeout_seconds) as response:  # noqa: S310 - sabit ve kontrollu endpoint
        raw = response.read(32_768)
    payload = json.loads(raw.decode("utf-8"))
    current = payload.get("current") if isinstance(payload, dict) else {}
    daily = payload.get("daily") if isinstance(payload, dict) else {}
    current = current if isinstance(current, dict) else {}
    daily = daily if isinstance(daily, dict) else {}
    code = current.get("weather_code", _first(daily.get("weather_code")))
    return {
        "status": "live",
        "provider": "open_meteo",
        "source_label": "Open-Meteo",
        "location_name": settings.location_name,
        "latitude": settings.latitude,
        "longitude": settings.longitude,
        "temperature": current.get("temperature_2m"),
        "apparent_temperature": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "precipitation": current.get("precipitation"),
        "rain": current.get("rain"),
        "weather_code": code,
        "weather_label": _weather_code_label(code),
        "wind_speed": current.get("wind_speed_10m"),
        "wind_gusts": current.get("wind_gusts_10m"),
        "daily_max": _first(daily.get("temperature_2m_max")),
        "daily_min": _first(daily.get("temperature_2m_min")),
        "rain_probability": _first(daily.get("precipitation_probability_max")),
        "daily_wind_max": _first(daily.get("wind_speed_10m_max")),
        "updated_at": datetime.now(UTC).isoformat(timespec="minutes"),
    }


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_weather_recommendations(weather: dict[str, Any]) -> list[dict[str, str]]:
    """Hava durumuna göre Tarihi Alan için karar destek önerileri üretir."""
    recs: list[dict[str, str]] = []
    status = str(weather.get("status") or "fallback")
    if status == "disabled":
        return [{
            "level": "muted",
            "icon": "fa-circle-info",
            "title": "Hava durumu kapalı",
            "text": "Hava durumu bilgisi bu ortamda kapalı; saha önerileri genel bilgi düzeyinde gösterilir.",
        }]

    wind_speed = max(_number(weather.get("wind_speed")), _number(weather.get("daily_wind_max")))
    gusts = _number(weather.get("wind_gusts"))
    rain_probability = _number(weather.get("rain_probability"))
    precipitation = max(_number(weather.get("precipitation")), _number(weather.get("rain")))
    temperature = _number(weather.get("temperature"), _number(weather.get("daily_max")))
    apparent = _number(weather.get("apparent_temperature"), temperature)
    code = int(_number(weather.get("weather_code"), -1))

    if code in {95, 96, 99} or gusts >= 55:
        recs.append({
            "level": "danger",
            "icon": "fa-cloud-bolt",
            "title": "Açık alan etkinliklerini kontrol edin",
            "text": "Fırtına veya ani sert rüzgâr ihtimali için tören, pano, bayrak ve ziyaretçi yönlendirme ekipmanları yeniden kontrol edilmeli.",
        })
    elif wind_speed >= 38 or gusts >= 45:
        recs.append({
            "level": "warning",
            "icon": "fa-wind",
            "title": "Rüzgâr hassasiyeti var",
            "text": "Açık alandaki yönlendirme panoları, geçici stantlar, bayraklar ve saha ekipmanları için sabitleme kontrolü önerilir.",
        })

    if rain_probability >= 60 or precipitation >= 1 or code in {51, 53, 55, 61, 63, 65, 80, 81, 82}:
        recs.append({
            "level": "warning",
            "icon": "fa-cloud-rain",
            "title": "Yağış planı hazırlayın",
            "text": "Açık alan ziyaretçi akışı, kaygan zemin, kapalı alan alternatifi ve personel ekipman planı gözden geçirilmeli.",
        })

    if apparent >= 32 or temperature >= 32:
        recs.append({
            "level": "warning",
            "icon": "fa-temperature-high",
            "title": "Sıcak hava tedbiri",
            "text": "Saha personeli için su, gölge ve mola planı; ziyaretçi yoğunluğu olan noktalarda sağlık tedbiri hatırlatılmalı.",
        })
    elif temperature <= 3:
        recs.append({
            "level": "warning",
            "icon": "fa-temperature-low",
            "title": "Soğuk ve kaygan zemin kontrolü",
            "text": "Rampa, basamak, yürüyüş yolu ve saha geçişlerinde kayganlık kontrolü yapılması önerilir.",
        })

    if code in {45, 48}:
        recs.append({
            "level": "info",
            "icon": "fa-smog",
            "title": "Görüş mesafesi takibi",
            "text": "Sisli koşullarda araç yönlendirmeleri, ziyaretçi bilgilendirmeleri ve saha iletişimi daha görünür hale getirilmeli.",
        })

    if not recs:
        recs.append({
            "level": "success",
            "icon": "fa-circle-check",
            "title": "Saha akışı normal görünüyor",
            "text": "Hava koşulları için olağan günlük kontrol yeterli. Açık alan programları yine saha sorumlusu onayıyla yürütülmelidir.",
        })

    recs.append({
        "level": "muted",
        "icon": "fa-shield-halved",
        "title": "Karar destek notu",
        "text": "Bu öneriler bilgilendirme amaçlıdır; nihai saha kararı yetkili sorumlular tarafından verilir.",
    })
    return recs[:4]


def _fallback_weather(settings: WeatherSettings, message: str, status: str = "fallback") -> dict[str, Any]:
    return {
        "status": status,
        "provider": settings.provider,
        "source_label": "Yerel güvenli mod",
        "location_name": settings.location_name,
        "latitude": settings.latitude,
        "longitude": settings.longitude,
        "temperature": None,
        "apparent_temperature": None,
        "humidity": None,
        "precipitation": None,
        "rain": None,
        "weather_code": None,
        "weather_label": "Tahmin alınamadı" if status != "disabled" else "Hava durumu kapalı",
        "wind_speed": None,
        "wind_gusts": None,
        "daily_max": None,
        "daily_min": None,
        "rain_probability": None,
        "daily_wind_max": None,
        "updated_at": datetime.now(UTC).isoformat(timespec="minutes"),
        "message": message,
    }


def get_home_weather_context(force_refresh: bool = False) -> dict[str, Any]:
    settings = get_weather_settings()
    cache_key = f"{settings.provider}:{settings.latitude:.4f}:{settings.longitude:.4f}"
    now = datetime.now(UTC)

    if not settings.enabled:
        weather = _fallback_weather(settings, "Hava durumu entegrasyonu kapalı.", status="disabled")
        weather["recommendations"] = build_weather_recommendations(weather)
        return weather

    cached = _CACHE.get(cache_key)
    if cached and not force_refresh:
        created_at, payload = cached
        if now - created_at <= timedelta(minutes=settings.cache_minutes):
            return dict(payload)

    try:
        if settings.provider != "open_meteo":
            raise ValueError(f"Desteklenmeyen hava durumu sağlayıcısı: {settings.provider}")
        weather = _fetch_open_meteo(settings)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        logger.exception("BYS360 hava durumu servisi yanıt vermedi | exc=%s", exc)
        weather = _fallback_weather(settings, "Hava durumu servisi şu an yanıt vermedi.")

    weather["recommendations"] = build_weather_recommendations(weather)
    _CACHE[cache_key] = (now, dict(weather))
    return weather


__all__ = [
    "OPEN_METEO_FORECAST_URL",
    "WeatherSettings",
    "build_weather_recommendations",
    "get_home_weather_context",
    "get_weather_settings",
]
