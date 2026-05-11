"""Industry taxonomy endpoint — feeds the cascading pickers in the UI."""

from fastapi import APIRouter

from models.newsletter_schemas import TaxonomyResponse
from services import taxonomy_service

router = APIRouter(prefix="/api/newsletter", tags=["Newsletter / Taxonomy"])


@router.get("/taxonomy", response_model=TaxonomyResponse)
async def get_taxonomy() -> TaxonomyResponse:
    return TaxonomyResponse(
        industries=taxonomy_service.all_industries(),
        authentic_domain_hints=taxonomy_service.authentic_domain_hints(),
        neutral_authority_domains=taxonomy_service.neutral_authority_domains(),
        version=taxonomy_service.version(),
    )
