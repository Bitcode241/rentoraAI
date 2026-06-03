from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.customer import Customer
from app.schemas import CustomerCreate, CustomerUpdate, CustomerOut

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("", response_model=List[CustomerOut])
def list_customers(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Customer).order_by(Customer.created_at.desc()).all()


@router.post("", response_model=CustomerOut)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db),
                    _=Depends(get_current_user)):
    cust = Customer(**payload.model_dump())
    db.add(cust)
    db.commit()
    db.refresh(cust)
    return cust


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    cust = db.get(Customer, customer_id)
    if not cust:
        raise HTTPException(404, "Customer not found")
    return cust


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, payload: CustomerUpdate,
                    db: Session = Depends(get_db), _=Depends(get_current_user)):
    cust = db.get(Customer, customer_id)
    if not cust:
        raise HTTPException(404, "Customer not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(cust, k, v)
    db.commit()
    db.refresh(cust)
    return cust
