from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from nutritionist.bootstrap import Container

router = APIRouter(prefix="/health", tags=["health"])


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, bool] = {}


@router.get("/live", response_model=HealthOut)
async def live() -> HealthOut:
    """The process is up. Never touches dependencies."""
    return HealthOut(status="ok")


@router.get("/ready", response_model=HealthOut)
async def ready(request: Request, response: Response) -> HealthOut:
    """Dependencies are reachable; safe to route traffic here."""
    container: Container = request.app.state.container
    checks = {"cache": await container.cache.ping()}
    if all(checks.values()):
        return HealthOut(status="ok", checks=checks)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(status="degraded", checks=checks)
