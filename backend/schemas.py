from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class User(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    avatar: Optional[str] = None


class Product(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    price: float
    active: bool = True


class Order(BaseModel):
    email: EmailStr
    plan: str = Field(..., description="ebook | kelas | template")
    payment_method: str = Field(..., description="DANA | OVO | GOPAY | BRI | dll")
    proof_image: Optional[str] = Field(None, description="Base64 data URL of the payment proof image")
    status: Optional[str] = Field(None, description="pending | submitted | queued | verified | rejected")
    note: Optional[str] = None
