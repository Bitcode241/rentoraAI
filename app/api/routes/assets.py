from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.asset import Asset
from app.schemas import AssetCreate, AssetUpdate, AssetOut

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("", response_model=List[AssetOut])
def list_assets(asset_type: Optional[str] = None, active: Optional[bool] = None,
                db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = db.query(Asset)
    if asset_type:
        q = q.filter(Asset.asset_type == asset_type)
    if active is not None:
        q = q.filter(Asset.active.is_(active))
    return q.order_by(Asset.name).all()


@router.post("", response_model=AssetOut, dependencies=[Depends(require_admin)])
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)):
    asset = Asset(**payload.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return asset


@router.patch("/{asset_id}", response_model=AssetOut, dependencies=[Depends(require_admin)])
def update_asset(asset_id: int, payload: AssetUpdate, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(asset, k, v)
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{asset_id}", dependencies=[Depends(require_admin)])
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    asset.active = False
    db.commit()
    return {"deactivated": asset_id}
