import logging

from .app import create_app
from .config import Settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
settings = Settings.from_env()
app = create_app(settings)
