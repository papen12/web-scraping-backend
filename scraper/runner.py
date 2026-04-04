"""
runner.py — Entry point único del scraper.

run(sitios, paralelo, workers) orquesta la captura, normalización,
resolución LLM y envío al monolito.

Modo continuo: main() carga sitios.toml y los scrapea en loop infinito,
esperando un intervalo configurable entre ciclos.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import signal
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from scraper.config import settings
from scraper.pool import BrowserPool
from scraper.normalizador import normalizar
from scraper.cliente import enviar_propiedad
from scraper.schema import Propiedad

logger = logging.getLogger(__name__)

# Intervalo entre ciclos de scraping (segundos). Default 30 min.
INTERVALO_SCRAPING = int(__import__("os").environ.get("SCRAPING_INTERVALO", 1800))


@dataclass
class SitioConfig:
    """Configuración mínima de un sitio a scrapear."""

    nombre: str
    url: str
    pais: str = "BO"


async def _scrape_sitio(pool: BrowserPool, sitio: SitioConfig) -> list[Propiedad]:
    """Scrapea un sitio individual usando un contexto del pool."""
    propiedades: list[Propiedad] = []

    async with pool.context() as ctx:
        page = await ctx.new_page()
        try:
            logger.info("Accediendo a %s  [%s]", sitio.nombre, sitio.url)
            await page.goto(sitio.url, wait_until="domcontentloaded", timeout=30_000)
            # Esperar un poco para que JS dinámico cargue
            await page.wait_for_timeout(3_000)
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
            logger.exception("Fallo al procesar %s (%s)", sitio.nombre, sitio.url)
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
                    logger.error("Sitio no procesado: %s", resultado)
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
            logger.exception("No se pudo enviar propiedad de %s", prop.url_origen)

    logger.info("Ronda completada — %d propiedades procesadas", len(todas))
    return todas


def _configurar_logging() -> Path:
    """Configura logging dual: consola (conciso) + archivo .txt (detallado).

    Returns:
        Path al archivo de log actual.
    """
    log_dir = settings.log_abs_path
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"scraper_{datetime.now():%Y-%m-%d}.txt"

    nivel = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(nivel)

    # ── Consola: conciso ──────────────────────────────────────────────────
    consola = logging.StreamHandler()
    consola.setLevel(nivel)
    consola.setFormatter(logging.Formatter(
        "%(asctime)s │ %(levelname)-7s │ %(message)s",
        datefmt="%H:%M:%S",
    ))

    # ── Archivo: detallado con rotación ───────────────────────────────────
    archivo = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    archivo.setLevel(logging.DEBUG)
    archivo.setFormatter(logging.Formatter(
        "%(asctime)s  [%(levelname)-7s]  %(name)s  —  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root.addHandler(consola)
    root.addHandler(archivo)
    return log_file


def main() -> None:
    """CLI entry point — scraping continuo desde sitios.toml."""
    log_file = _configurar_logging()

    sitios = _cargar_sitios()
    if not sitios:
        logger.error("No hay sitios activos en %s", settings.sitios_abs_path)
        return

    logger.info(
        "Scraper iniciado — %d sitios, ciclo cada %ds, %d workers  |  logs → %s",
        len(sitios),
        INTERVALO_SCRAPING,
        settings.max_workers,
        log_file,
    )

    asyncio.run(_loop_continuo(sitios))


def _cargar_sitios() -> list[SitioConfig]:
    """Carga sitios activos desde sitios.toml."""
    path = settings.sitios_abs_path
    if not path.exists():
        logger.error("No se encontró %s", path)
        return []

    with open(path, "rb") as f:
        data = tomllib.load(f)

    sitios: list[SitioConfig] = []
    for entry in data.get("sitio", []):
        if not entry.get("activo", True):
            continue
        sitios.append(
            SitioConfig(
                nombre=entry["nombre"],
                url=entry["url"],
                pais=entry.get("pais", "BO"),
            )
        )
    return sitios


async def _loop_continuo(sitios: list[SitioConfig]) -> None:
    """Loop infinito de scraping con graceful shutdown via SIGINT/SIGTERM."""
    detener = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, detener.set)

    ciclo = 0
    while not detener.is_set():
        ciclo += 1
        logger.info("── Ciclo %d: procesando %d sitios ──", ciclo, len(sitios))

        try:
            resultado = await run(sitios)
            logger.info(
                "Ciclo %d finalizado — %d propiedades obtenidas",
                ciclo,
                len(resultado),
            )
        except Exception:
            logger.exception("Ciclo %d interrumpido por error", ciclo)

        if detener.is_set():
            break

        logger.info("Próximo ciclo en %d segundos", INTERVALO_SCRAPING)
        try:
            await asyncio.wait_for(detener.wait(), timeout=INTERVALO_SCRAPING)
        except asyncio.TimeoutError:
            pass  # Timeout normal → siguiente ciclo

    logger.info("Scraper detenido — cierre limpio")


if __name__ == "__main__":
    main()
