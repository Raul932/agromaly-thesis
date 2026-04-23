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

from app.presentation.api.v1.endpoints.users import router as users_router
from app.presentation.api.v1.endpoints.parcels import router as parcels_router

api_router = APIRouter()

api_router.include_router(users_router)
api_router.include_router(parcels_router)
