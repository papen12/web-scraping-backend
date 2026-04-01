"""
cliente.py — POST httpx async al monolito con degradación controlada.

Si el monolito no responde:
  1. Guarda la propiedad como JSON en output/pendientes/
  2. Marca el monolito como "caído" (circuit breaker)
  3. Siguientes propiedades van directo a disco sin intentar POST
  4. Al final del batch reporta cuántas se guardaron localmente

Reintentos con backoff exponencial en 5xx o timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from scraper.config import settings
from scraper.schema import Propiedad

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_BACKOFF = 1.0
CIRCUIT_OPEN_SECONDS = 60  # No reintentar monolito por 60s tras fallo


class ClienteMonolito:
    """
    Cliente HTTP con circuit breaker para el monolito.

    Estados:
      CLOSED  = monolito disponible, enviar normalmente
      OPEN    = monolito caído, guardar en disco
      HALF    = probar un request, si falla volver a OPEN
    """

    def __init__(self) -> None:
        self._estado = "CLOSED"
        self._ultimo_fallo: float = 0
        self._enviadas: int = 0
        self._fallback: int = 0
        self._errores: int = 0

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "estado_circuito": self._estado,
            "enviadas_monolito": self._enviadas,
            "guardadas_disco": self._fallback,
            "errores_totales": self._errores,
        }

    def _abrir_circuito(self) -> None:
        self._estado = "OPEN"
        self._ultimo_fallo = time.monotonic()
        logger.warning(
            "🔴 Circuit breaker ABIERTO — monolito inaccesible. "
            "Propiedades irán a disco por %ds.",
            CIRCUIT_OPEN_SECONDS,
        )

    def _check_half_open(self) -> bool:
        """Si pasó tiempo suficiente, probar un request (half-open)."""
        if self._estado != "OPEN":
            return False
        elapsed = time.monotonic() - self._ultimo_fallo
        if elapsed >= CIRCUIT_OPEN_SECONDS:
            self._estado = "HALF"
            logger.info(
                "🟡 Circuit breaker HALF-OPEN — probando monolito (%.0fs desde último fallo)...",
                elapsed,
            )
            return True
        return False

    async def health_check(self) -> bool:
        """Verifica si el monolito está accesible antes de iniciar el batch."""
        url = settings.monolito_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code < 500:
                    logger.info("✅ Monolito accesible en %s (HTTP %d)", url, resp.status_code)
                    self._estado = "CLOSED"
                    return True
                logger.warning(
                    "⚠️ Monolito respondió %d en %s", resp.status_code, url
                )
                self._abrir_circuito()
                return False
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as e:
            logger.warning(
                "⚠️ Monolito NO accesible en %s: %s — se usará almacenamiento local",
                url,
                type(e).__name__,
            )
            self._abrir_circuito()
            return False

    async def enviar(self, propiedad: Propiedad) -> bool:
        """
        Envía propiedad al monolito. Si el circuito está abierto, guarda en disco.
        """
        # Check si debemos probar de nuevo
        self._check_half_open()

        if self._estado == "OPEN":
            self._guardar_fallback(propiedad)
            return False

        # Intentar enviar
        exito = await self._post_monolito(propiedad)

        if exito:
            if self._estado == "HALF":
                self._estado = "CLOSED"
                logger.info("🟢 Circuit breaker CERRADO — monolito respondiendo OK")
            self._enviadas += 1
            return True
        else:
            self._errores += 1
            if self._estado == "HALF":
                self._abrir_circuito()
            elif self._errores >= MAX_RETRIES:
                self._abrir_circuito()
            self._guardar_fallback(propiedad)
            return False

    async def _post_monolito(self, propiedad: Propiedad) -> bool:
        """POST con reintentos y backoff."""
        url = f"{settings.monolito_url.rstrip('/')}/propiedades"
        payload = propiedad.model_dump(mode="json")

        async with httpx.AsyncClient(timeout=30.0) as client:
            for intento in range(MAX_RETRIES):
                try:
                    logger.info(
                        "POST %s — fuente=%s url=%s (intento %d/%d)",
                        url,
                        propiedad.fuente,
                        propiedad.url_origen,
                        intento + 1,
                        MAX_RETRIES,
                    )
                    response = await client.post(url, json=payload)

                    if response.status_code < 500:
                        if response.is_success:
                            logger.info(
                                "✓ Enviada — fuente=%s url=%s",
                                propiedad.fuente,
                                propiedad.url_origen,
                            )
                        else:
                            logger.warning(
                                "HTTP %d — fuente=%s url=%s",
                                response.status_code,
                                propiedad.fuente,
                                propiedad.url_origen,
                            )
                        return response.is_success

                    backoff = BASE_BACKOFF * (2**intento)
                    logger.warning(
                        "Server %d, retry en %.1fs...", response.status_code, backoff
                    )
                    await asyncio.sleep(backoff)

                except (httpx.ConnectError, httpx.TimeoutException):
                    backoff = BASE_BACKOFF * (2**intento)
                    logger.warning(
                        "Conexión fallida a %s, retry en %.1fs...", url, backoff
                    )
                    await asyncio.sleep(backoff)

                except httpx.HTTPError as e:
                    logger.error("Error HTTP irrecuperable: %s", e)
                    return False

        logger.error(
            "Falló envío tras %d intentos: %s", MAX_RETRIES, propiedad.url_origen
        )
        return False

    def _guardar_fallback(self, propiedad: Propiedad) -> None:
        """Guarda la propiedad como JSON en disco."""
        fallback_dir = settings.fallback_path
        fallback_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{propiedad.fuente}_{propiedad.id}.json"
        filepath = fallback_dir / filename

        data = propiedad.model_dump(mode="json")
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._fallback += 1
        logger.info(
            "💾 Guardada en disco: %s (%s)", filename, propiedad.url_origen
        )

    async def reintentar_pendientes(self) -> dict[str, int]:
        """
        Reintenta enviar las propiedades guardadas en disco.
        Retorna stats de éxito/fallo.
        """
        fallback_dir = settings.fallback_path
        if not fallback_dir.exists():
            return {"encontradas": 0, "enviadas": 0, "fallidas": 0}

        archivos = list(fallback_dir.glob("*.json"))
        if not archivos:
            return {"encontradas": 0, "enviadas": 0, "fallidas": 0}

        logger.info("📤 Reintentando %d propiedades pendientes...", len(archivos))
        enviadas = 0
        fallidas = 0

        for archivo in archivos:
            try:
                data = json.loads(archivo.read_text(encoding="utf-8"))
                propiedad = Propiedad.model_validate(data)
                ok = await self._post_monolito(propiedad)
                if ok:
                    archivo.unlink()
                    enviadas += 1
                else:
                    fallidas += 1
            except Exception as e:
                logger.error("Error reintentando %s: %s", archivo.name, e)
                fallidas += 1

        logger.info(
            "📤 Reintento completado: %d enviadas, %d fallidas", enviadas, fallidas
        )
        return {"encontradas": len(archivos), "enviadas": enviadas, "fallidas": fallidas}


# Singleton
cliente = ClienteMonolito()
