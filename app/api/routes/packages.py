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


@router.post("/apply-to-group/{asset_id}", dependencies=[Depends(require_admin)])
def apply_packages_to_group(asset_id: int, db: Session = Depends(get_db)):
    """Copy this asset's packages to every other asset in the same model_group.
    One source of truth for identical units (e.g. 6x Yamaha VX): set prices once,
    apply to all. Matches packages by name; updates price/duration, adds missing,
    leaves the source untouched."""
    src = db.get(Asset, asset_id)
    if not src:
        raise HTTPException(404, "asset_not_found")
    group = (src.model_group or "").strip().lower()
    if not group:
        return {"error": "no_group",
                "message": "Postavi grupu modela na ovaj resurs da bi primijenio na grupu."}

    src_pkgs = db.query(RentalPackage).filter(
        RentalPackage.asset_id == src.id).all()
    targets = [a for a in db.query(Asset).filter(
        Asset.asset_type == src.asset_type).all()
        if (a.model_group or "").strip().lower() == group and a.id != src.id]

    updated = 0
    for t in targets:
        existing = {p.name: p for p in db.query(RentalPackage).filter(
            RentalPackage.asset_id == t.id).all()}
        for sp in src_pkgs:
            ep = existing.get(sp.name)
            if ep:
                ep.duration_minutes = sp.duration_minutes
                ep.price = sp.price
                ep.guided = sp.guided
                ep.description = sp.description
                ep.active = sp.active
            else:
                db.add(RentalPackage(
                    asset_id=t.id, name=sp.name,
                    duration_minutes=sp.duration_minutes, price=sp.price,
                    guided=sp.guided, description=sp.description, active=sp.active))
        updated += 1
    db.commit()
    return {"ok": True, "applied_to": updated, "group": group,
            "packages": len(src_pkgs)}
