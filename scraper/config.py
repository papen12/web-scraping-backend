"""
config.py — Configuración centralizada vía variables de entorno.

Usa pydantic-settings para cargar y validar env vars.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings

# Raíz del proyecto (donde está pyproject.toml)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configuración del scraper, leída desde variables de entorno."""

    groq_api_key: str = ""
    monolito_url: str = "http://localhost:8000"
    max_workers: int = 4
    paralelo: bool = True
    log_level: str = "INFO"
    reglas_path: str = "reglas/reglas.toml"
    sitios_path: str = "sitios.toml"
    fallback_dir: str = "output/pendientes"
    navegacion_timeout: int = 45_000  # ms

    model_config = {
        "env_prefix": "",
        "case_sensitive": False,
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def fallback_path(self) -> Path:
        return PROJECT_ROOT / self.fallback_dir

    @property
    def sitios_abs_path(self) -> Path:
        return PROJECT_ROOT / self.sitios_path


# Singleton para uso global
settings = Settings()
