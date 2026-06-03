from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.asset import Asset
from app.models.package import RentalPackage
from app.schemas import PackageCreate, PackageBase, PackageOut

router = APIRouter(prefix="/api/packages", tags=["packages"])


@router.get("/by-asset/{asset_id}", response_model=List[PackageOut])
def list_for_asset(asset_id: int, db: Session = Depends(get_db),
                   _=Depends(get_current_user)):
    return db.query(RentalPackage).filter(
        RentalPackage.asset_id == asset_id).order_by(
        RentalPackage.duration_minutes).all()


@router.post("", response_model=PackageOut, dependencies=[Depends(require_admin)])
def create_package(payload: PackageCreate, db: Session = Depends(get_db)):
    if not db.get(Asset, payload.asset_id):
        raise HTTPException(404, "Asset not found")
    pkg = RentalPackage(**payload.model_dump())
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return pkg


@router.patch("/{package_id}", response_model=PackageOut,
              dependencies=[Depends(require_admin)])
def update_package(package_id: int, payload: PackageBase,
                   db: Session = Depends(get_db)):
    pkg = db.get(RentalPackage, package_id)
    if not pkg:
        raise HTTPException(404, "Package not found")
    for k, v in payload.model_dump().items():
        setattr(pkg, k, v)
    db.commit()
    db.refresh(pkg)
    return pkg


@router.delete("/{package_id}", dependencies=[Depends(require_admin)])
def delete_package(package_id: int, db: Session = Depends(get_db)):
    pkg = db.get(RentalPackage, package_id)
    if not pkg:
        raise HTTPException(404, "Package not found")
    db.delete(pkg)
    db.commit()
    return {"deleted": package_id}
