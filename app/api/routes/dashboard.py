from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["dashboard"])


@router.get("/admin", include_in_schema=False)
def admin():
    return FileResponse("app/static/admin.html", media_type="text/html")
