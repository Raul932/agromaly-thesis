"""
API v1 Router Aggregator
=========================
Combines all v1 endpoint routers into a single ``api_router`` that is
mounted on the FastAPI app with the ``/api/v1`` prefix in ``main.py``.

Adding new routers:
    1. Create ``app/presentation/api/v1/endpoints/my_feature.py``.
    2. Import its ``router`` here and add it to the list below.
"""

from fastapi import APIRouter

from app.presentation.api.v1.endpoints.alerts import router as alerts_router
from app.presentation.api.v1.endpoints.analysis import router as analysis_router
from app.presentation.api.v1.endpoints.chat import router as chat_router
from app.presentation.api.v1.endpoints.gpx_upload import router as gpx_upload_router
from app.presentation.api.v1.endpoints.users import router as users_router
from app.presentation.api.v1.endpoints.parcels import router as parcels_router

api_router = APIRouter()

api_router.include_router(users_router)
api_router.include_router(parcels_router)
api_router.include_router(analysis_router)
api_router.include_router(gpx_upload_router)
api_router.include_router(chat_router)
api_router.include_router(alerts_router)

