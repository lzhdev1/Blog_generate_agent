from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from config.settings import settings
from src.blog_agent.api.deps import get_db, get_optional_user
from src.blog_agent.db.models import User
from src.blog_agent.service.media_access import can_view_media

router = APIRouter(tags=["配图"])


@router.get("/images/{filename}", response_class=FileResponse)
def read_image(filename: str, db: Session = Depends(get_db), viewer: User | None = Depends(get_optional_user)):
    if not can_view_media(db, viewer.id if viewer else None, filename):
        raise HTTPException(404, detail="配图不存在")
    directory = Path(settings.image_save_dir).resolve()
    asset = (directory / filename).resolve()
    if asset.parent != directory or not asset.is_file():
        raise HTTPException(404, detail="配图不存在")
    return FileResponse(asset, headers={"Cache-Control": "private, no-store", "Vary": "Authorization",
                                        "X-Content-Type-Options": "nosniff",
                                        "Content-Security-Policy": "default-src 'none'; sandbox"})
