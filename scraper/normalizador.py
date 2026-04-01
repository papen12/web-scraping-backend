"""
normalizador.py — Normaliza datos crudos usando el motor de reglas Rust.

Detecta campos sin resolver y delega al LLM si es necesario.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from scraper.config import settings
from scraper.schema import (
    GeoConfianza,
    Operacion,
    Propiedad,
    TipoPropiedad,
)

logger = logging.getLogger(__name__)

# Campos que el motor de reglas puede resolver
CAMPOS_RESOLVIBLES = {
    "precio_usd",
    "precio_local",
    "moneda_local",
    "precio_consultable",
    "lat",
    "lng",
    "geo_confianza",
}


def _cargar_motor():
    """Carga el motor de reglas Rust (lazy)."""
    try:
        import scraper._scraper_core as scraper_core

        return scraper_core.MotorReglas(settings.reglas_path)
    except ImportError:
        logger.warning(
            "scraper_core no disponible. Ejecutar: maturin develop --release"
        )
        return None


def _cargar_extractor():
    """Carga el extractor Rust (lazy)."""
    try:
        import scraper._scraper_core as scraper_core

        return scraper_core.Extractor()
    except ImportError:
        return None


def normalizar(
    raw_payload: dict[str, Any],
    fuente: str,
    url_origen: str,
    pais: str = "AR",
) -> Propiedad:
    """
    Normaliza un payload crudo a una Propiedad del esquema canónico.

    1. Extraer campos básicos del payload.
    2. Usar Extractor Rust para coords y precios.
    3. Aplicar reglas Scheme via MotorReglas.
    4. Detectar campos sin resolver.
    5. Si hay campos sin resolver, delegar al LLM.

    Regla de oro: precio_raw NUNCA se descarta.
    """
    campos: dict[str, Any] = {}
    reglas_aplicadas: list[str] = []
    campos_sin_resolver: list[str] = []
    llm_usado = False

    # ── Extraer precio_raw ────────────────────────────────────────────────
    precio_raw = raw_payload.get("precio_raw", "")
    if not precio_raw:
        precio_raw = ""
        campos_sin_resolver.append("precio_raw")

    # ── Usar Extractor Rust si está disponible ────────────────────────────
    extractor = _cargar_extractor()
    if extractor:
        # Normalizar precio
        if precio_raw:
            try:
                precio_info = extractor.normalizar_precio(precio_raw)
                campos["precio_usd"] = precio_info.get("precio_usd")
                campos["precio_local"] = precio_info.get("precio_local")
                campos["moneda_local"] = precio_info.get("moneda_local")
                campos["precio_consultable"] = precio_info.get(
                    "precio_consultable", False
                )
                reglas_aplicadas.append("extractor:precio")
            except Exception as e:
                logger.warning("Error normalizando precio: %s", e)
                campos_sin_resolver.append("precio")

        # Extraer coords de Google Maps
        iframe_src = raw_payload.get("iframe_src")
        if iframe_src:
            try:
                lat, lng = extractor.extraer_gmaps(iframe_src)
                campos["lat"] = lat
                campos["lng"] = lng
                campos["geo_confianza"] = GeoConfianza.iframe.value
                reglas_aplicadas.append("extractor:gmaps")
            except Exception as e:
                logger.debug("No se extrajeron coords de gmaps: %s", e)

        # Extraer coords de Leaflet
        js_center = raw_payload.get("js_leaflet_center")
        if js_center:
            try:
                lat, lng = extractor.extraer_leaflet(js_center)
                campos["lat"] = lat
                campos["lng"] = lng
                campos["geo_confianza"] = GeoConfianza.leaflet.value
                reglas_aplicadas.append("extractor:leaflet")
            except Exception as e:
                logger.debug("No se extrajeron coords de leaflet: %s", e)

    # ── Aplicar reglas Scheme via MotorReglas ─────────────────────────────
    motor = _cargar_motor()
    if motor:
        try:
            campos_para_reglas = {**raw_payload, **campos}
            resultado = motor.aplicar(campos_para_reglas, fuente)
            # Merge resultado
            for k, v in resultado.items():
                if k != "reglas_aplicadas" and v is not None:
                    campos[k] = v
            if "reglas_aplicadas" in resultado:
                reglas_aplicadas.extend(resultado["reglas_aplicadas"])
        except Exception as e:
            logger.warning("Error aplicando reglas Scheme: %s", e)

    # ── Detectar campos sin resolver ──────────────────────────────────────
    for campo in CAMPOS_RESOLVIBLES:
        if campo not in campos or campos.get(campo) is None:
            if campo not in campos_sin_resolver:
                campos_sin_resolver.append(campo)

    # ── LLM para campos sin resolver ─────────────────────────────────────
    if campos_sin_resolver and settings.groq_api_key:
        try:
            from scraper.llm import inferir_reglas

            nuevas_reglas = inferir_reglas(
                campos_sin_resolver={
                    c: raw_payload.get(c) for c in campos_sin_resolver
                },
                fuente=fuente,
                reglas_existentes=reglas_aplicadas,
            )
            if nuevas_reglas and motor:
                for regla_code in nuevas_reglas:
                    nombre = f"llm_{fuente}_{len(reglas_aplicadas)}"
                    try:
                        motor.agregar_regla(nombre, regla_code, fuente, 0.3)
                        reglas_aplicadas.append(nombre)
                    except Exception as e:
                        logger.warning("Error agregando regla LLM: %s", e)
                llm_usado = True
        except Exception as e:
            logger.warning("Error con LLM: %s", e)

    # ── Construir Propiedad ───────────────────────────────────────────────
    geo_conf_str = campos.get("geo_confianza", "ausente")
    try:
        geo_confianza = GeoConfianza(geo_conf_str)
    except ValueError:
        geo_confianza = GeoConfianza.ausente

    return Propiedad(
        fuente=fuente,
        url_origen=url_origen,
        tipo=TipoPropiedad(raw_payload.get("tipo", "otro")),
        operacion=Operacion(raw_payload.get("operacion", "venta")),
        scraped_at=datetime.now(timezone.utc),
        precio_raw=precio_raw,
        pais=pais,
        precio_usd=campos.get("precio_usd"),
        precio_local=campos.get("precio_local"),
        moneda_local=campos.get("moneda_local"),
        precio_consultable=campos.get("precio_consultable", False),
        lat=campos.get("lat"),
        lng=campos.get("lng"),
        geo_confianza=geo_confianza,
        direccion_raw=raw_payload.get("direccion_raw"),
        ciudad=raw_payload.get("ciudad"),
        m2_total=raw_payload.get("m2_total"),
        m2_cubierto=raw_payload.get("m2_cubierto"),
        m2_terreno=raw_payload.get("m2_terreno"),
        ambientes=raw_payload.get("ambientes"),
        dormitorios=raw_payload.get("dormitorios"),
        banos=raw_payload.get("banos"),
        cocheras=raw_payload.get("cocheras"),
        antiguedad=raw_payload.get("antiguedad"),
        estado=raw_payload.get("estado"),
        amenities=raw_payload.get("amenities", []),
        reglas_aplicadas=reglas_aplicadas,
        campos_sin_resolver=campos_sin_resolver,
        llm_usado=llm_usado,
        raw_payload=raw_payload,
    )
