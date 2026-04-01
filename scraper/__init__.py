"""
scraper — Web scraper adaptativo para inmobiliarias.

Expone el módulo Rust (`scraper_core`) con MotorReglas y Extractor,
y los componentes Python de orquestación.
"""

from scraper.config import Settings
from scraper.schema import Propiedad

__all__ = [
    "Settings",
    "Propiedad",
]
