from fastapi import APIRouter

from app.api.routes.documents import router as documents_router
from app.api.routes.evidence import router as evidence_router
from app.api.routes.health import router as health_router
from app.api.routes.normalization import router as normalization_router
from app.api.routes.project_context import router as project_context_router
from app.api.routes.projects import router as projects_router

api_router = APIRouter()
api_router.include_router(projects_router)
api_router.include_router(documents_router)
api_router.include_router(evidence_router)
api_router.include_router(normalization_router)
api_router.include_router(project_context_router)
api_router.include_router(health_router, tags=["system"])
