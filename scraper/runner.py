"""
runner.py — Entry point único del scraper.

run(sitios, paralelo, workers) orquesta la captura, normalización,
resolución LLM y envío al monolito.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from scraper.config import settings
from scraper.pool import BrowserPool
from scraper.normalizador import normalizar
from scraper.cliente import enviar_propiedad
from scraper.schema import Propiedad

logger = logging.getLogger(__name__)


@dataclass
class SitioConfig:
    """Configuración mínima de un sitio a scrapear."""

    nombre: str
    url: str
    pais: str = "AR"


async def _scrape_sitio(pool: BrowserPool, sitio: SitioConfig) -> list[Propiedad]:
    """Scrapea un sitio individual usando un contexto del pool."""
    propiedades: list[Propiedad] = []

    async with pool.context() as ctx:
        page = await ctx.new_page()
        try:
            logger.info("Navegando a %s (%s)", sitio.url, sitio.nombre)
            await page.goto(sitio.url, wait_until="networkidle", timeout=30_000)
            html = await page.content()

            # Extraer datos crudos de la página
            raw_payload = await _extraer_payload(page, html)

            # Normalizar via motor Rust + reglas Scheme
            propiedad = normalizar(
                raw_payload=raw_payload,
                fuente=sitio.nombre,
                url_origen=sitio.url,
                pais=sitio.pais,
            )
            propiedades.append(propiedad)

        except Exception:
            logger.exception("Error scrapeando %s", sitio.url)
        finally:
            await page.close()

    return propiedades


async def _extraer_payload(page: Any, html: str) -> dict:
    """
    Extrae datos crudos de la página.

    Intenta obtener:
    - iframe_src de Google Maps
    - js_leaflet_center si hay mapa Leaflet
    - precio_raw del contenedor de precio
    - Otros datos según selectores comunes
    """
    payload: dict[str, Any] = {"html": html}

    # Intentar extraer iframe de Google Maps
    try:
        iframe = await page.query_selector('iframe[src*="google.com/maps"]')
        if iframe:
            src = await iframe.get_attribute("src")
            if src:
                payload["iframe_src"] = src
    except Exception:
        pass

    # Intentar extraer estado de Leaflet
    try:
        leaflet_center = await page.evaluate("""() => {
            if (typeof L !== 'undefined') {
                const maps = Object.values(L.Map._instances || {});
                if (maps.length > 0) {
                    const c = maps[0].getCenter();
                    return c.lat + ',' + c.lng;
                }
            }
            return null;
        }""")
        if leaflet_center:
            payload["js_leaflet_center"] = leaflet_center
    except Exception:
        pass

    return payload


async def run(
    sitios: list[SitioConfig],
    paralelo: bool | None = None,
    workers: int | None = None,
) -> list[Propiedad]:
    """
    Entry point principal del scraper.

    Args:
        sitios: Lista de sitios a scrapear.
        paralelo: True=asyncio.gather, False=secuencial. Default: settings.
        workers: Número máximo de contextos concurrentes. Default: settings.

    Returns:
        Lista de propiedades extraídas y normalizadas.
    """
    if paralelo is None:
        paralelo = settings.paralelo
    if workers is None:
        workers = settings.max_workers

    todas: list[Propiedad] = []

    async with BrowserPool(workers=workers) as pool:
        if paralelo:
            # Ejecución en paralelo con asyncio.gather
            tareas = [_scrape_sitio(pool, sitio) for sitio in sitios]
            resultados = await asyncio.gather(*tareas, return_exceptions=True)
            for resultado in resultados:
                if isinstance(resultado, list):
                    todas.extend(resultado)
                elif isinstance(resultado, Exception):
                    logger.error("Tarea fallida: %s", resultado)
        else:
            # Ejecución secuencial
            for sitio in sitios:
                props = await _scrape_sitio(pool, sitio)
                todas.extend(props)

    # Enviar al monolito
    for prop in todas:
        try:
            await enviar_propiedad(prop)
        except Exception:
            logger.exception("Error enviando propiedad %s", prop.url_origen)

    logger.info("Scraping completado: %d propiedades", len(todas))
    return todas


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Ejemplo: se configura con sitios desde un archivo o argumentos
    logger.info("Scraper iniciado. Configurar sitios para comenzar.")
