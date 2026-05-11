"""Aggregate router registration."""

from routers.health import router as health_router
from routers.taxonomy import router as taxonomy_router
from routers.files import router as files_router
from routers.models import router as models_router
from routers.providers import router as providers_router
from routers.newsletter import router as newsletter_router


def register_routers(app) -> None:
    app.include_router(health_router)
    app.include_router(taxonomy_router)
    app.include_router(files_router)
    app.include_router(models_router)
    app.include_router(providers_router)
    app.include_router(newsletter_router)


__all__ = [
    "register_routers",
    "health_router",
    "taxonomy_router",
    "files_router",
    "models_router",
    "providers_router",
    "newsletter_router",
]
