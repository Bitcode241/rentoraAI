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
    data = payload.model_dump()
    _validate_provider(data)
    asset = Asset(**data)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _validate_provider(data: dict):
    """Block saving a partner tour without the mandatory provider data."""
    if (data.get("provider_type") or "own").lower() == "partner":
        missing = []
        if not (data.get("provider_name") or "").strip():
            missing.append("naziv izvođača")
        if not (data.get("provider_oib") or "").strip():
            missing.append("OIB izvođača")
        if float(data.get("partner_total_price") or 0) <= 0:
            missing.append("ukupna cijena")
        if float(data.get("my_commission") or 0) <= 0:
            missing.append("provizija")
        if float(data.get("my_commission") or 0) > float(data.get("partner_total_price") or 0):
            raise HTTPException(400, "Provizija ne može biti veća od ukupne cijene.")
        if missing:
            raise HTTPException(400, "Partner izlet zahtijeva: " + ", ".join(missing))


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
    updates = payload.model_dump(exclude_none=True)
    # validate the resulting provider state (merge current + updates)
    merged = {
        "provider_type": updates.get("provider_type", asset.provider_type),
        "provider_name": updates.get("provider_name", asset.provider_name),
        "provider_oib": updates.get("provider_oib", asset.provider_oib),
        "partner_total_price": updates.get("partner_total_price", asset.partner_total_price),
        "my_commission": updates.get("my_commission", asset.my_commission),
    }
    _validate_provider(merged)
    for k, v in updates.items():
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
