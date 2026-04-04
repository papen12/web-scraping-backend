"""
pool.py — BrowserPool: un browser Chromium headless, N contextos via Semaphore.

Implementado como async context manager.
NO lanza múltiples browsers.
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import AsyncIterator

from contextlib import asynccontextmanager
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Playwright,
)

logger = logging.getLogger(__name__)

# Flags de Chromium headless
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
]


class BrowserPool:
    """
    Pool de contextos de navegador sobre un único browser Chromium.

    Uso:
        async with BrowserPool(workers=4) as pool:
            async with pool.context() as ctx:
                page = await ctx.new_page()
                await page.goto(url)
                html = await page.content()
    """

    def __init__(self, workers: int = 4) -> None:
        self._workers = workers
        self._semaphore = asyncio.Semaphore(workers)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> BrowserPool:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=CHROMIUM_ARGS,
            handle_sigint=False,
            handle_sigterm=False,
        )
        logger.info(
            "Navegador listo — capacidad máxima: %d páginas simultáneas",
            self._workers,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Navegador cerrado correctamente")

    @asynccontextmanager
    async def context(self) -> AsyncIterator[BrowserContext]:
        """
        Obtiene un contexto de navegador, limitado por el Semaphore.
        El contexto se cierra automáticamente al salir del bloque.
        """
        assert self._browser is not None, "BrowserPool no iniciado (usar async with)"
        async with self._semaphore:
            ctx = await self._browser.new_context()
            try:
                yield ctx
            finally:
                await ctx.close()
