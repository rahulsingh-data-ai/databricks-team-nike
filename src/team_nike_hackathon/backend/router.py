from databricks.sdk.service.iam import User as UserOut

from .core import Dependencies, create_router
from .models import VersionOut
from .routes.admin import router as admin_router
from .routes.capabilities import router as capabilities_router
from .routes.citations import router as citations_router
from .routes.compare import router as compare_router
from .routes.coverage import router as coverage_router
from .routes.desert import router as desert_router
from .routes.facility import router as facility_router
from .routes.health import router as health_router
from .routes.search import router as search_router
from .routes.shortlist import router as shortlist_router
from .routes.stream import router as stream_router

router = create_router()

router.include_router(search_router)
router.include_router(facility_router)
router.include_router(capabilities_router)
router.include_router(citations_router)
router.include_router(desert_router)
router.include_router(shortlist_router)
router.include_router(health_router)
router.include_router(coverage_router)
router.include_router(compare_router)
router.include_router(stream_router)
router.include_router(admin_router)


@router.get("/version", response_model=VersionOut, operation_id="version")
async def version():
    return VersionOut.from_metadata()


@router.get("/current-user", response_model=UserOut, operation_id="currentUser")
def me(user_ws: Dependencies.UserClient):
    return user_ws.current_user.me()
