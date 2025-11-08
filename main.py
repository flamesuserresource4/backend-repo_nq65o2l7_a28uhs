import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal

import jwt
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr

from database import create_document, get_documents, db
from schemas import Order

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Auth setup (JWT) ===
JWT_SECRET = os.getenv("JWT_SECRET", "dev_secret_change_me")
JWT_ALG = "HS256"
security = HTTPBearer(auto_error=False)

ADMIN_NAME = os.getenv("ADMIN_NAME", "Admin, M.Sadri")
ADMIN_PIN = os.getenv("ADMIN_PIN", "200112")

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class AdminLogin(BaseModel):
    name: str
    pin: str

class VerifyAction(BaseModel):
    order_id: str
    action: Literal["verify", "reject"]
    note: Optional[str] = None

class OrderCreate(BaseModel):
    email: EmailStr
    plan: Literal['ebook', 'kelas', 'template']
    payment_method: Literal['DANA', 'OVO', 'GOPAY', 'BRI']
    proof_image: Optional[str] = None


def create_jwt(sub: str, role: str = "admin", ttl_minutes: int = 120) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def require_admin(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if creds is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = creds.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        if payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Forbidden")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


@app.post("/api/auth/login", response_model=TokenResponse)
def admin_login(payload: AdminLogin):
    if payload.name.strip() != ADMIN_NAME or payload.pin.strip() != ADMIN_PIN:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_jwt(sub=payload.name, role="admin")
    return TokenResponse(access_token=token)


@app.post("/api/orders")
def create_order(order: OrderCreate):
    try:
        order_doc = Order(
            email=order.email,
            plan=order.plan,
            payment_method=order.payment_method,
            proof_image=order.proof_image,
            status='submitted' if order.proof_image else 'pending'
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    inserted_id = create_document('order', order_doc)
    return {"id": inserted_id, "status": order_doc.status}


@app.get("/api/orders")
def list_orders(email: Optional[str] = None, limit: int = 50):
    filter_dict = {"email": email} if email else {}
    docs = get_documents('order', filter_dict, limit)
    for d in docs:
        _id = d.get('_id')
        if _id is not None:
            d['id'] = str(_id)
            del d['_id']
        if 'proof_image' in d:
            d['proof_image'] = None
    return {"items": docs}


@app.post("/api/orders/verify")
def verify_order(action: VerifyAction, user=Depends(require_admin)):
    from bson import ObjectId
    if not action.order_id:
        raise HTTPException(status_code=400, detail="order_id required")
    if action.action not in ("verify", "reject"):
        raise HTTPException(status_code=400, detail="Invalid action")
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")

    coll = db['order']
    oid = None
    try:
        oid = ObjectId(action.order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order_id")

    new_status = 'verified' if action.action == 'verify' else 'rejected'
    update_doc = {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc)}}
    if action.note:
        update_doc["$set"]["note"] = action.note

    res = coll.update_one({"_id": oid}, update_doc)
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")

    return {"id": action.order_id, "status": new_status}


# Webhook placeholder to be extended later (kept to avoid breaking frontend)
@app.post("/api/webhook/payment")
async def payment_webhook(request: Request):
    payload = await request.json()
    # No-op processing for now
    return {"received": True, "payload_keys": list(payload.keys()) if isinstance(payload, dict) else []}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
