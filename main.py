import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
from pydantic import BaseModel
from database import create_document, get_documents
from schemas import Order

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}

@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    
    try:
        # Try to import database module
        from database import db
        
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            
            # Try to list collections to verify connectivity
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]  # Show first 10 collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
            
    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    
    # Check environment variables
    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    
    return response

# Create order (supports optional proof image as base64 via JSON or multipart)
class OrderCreate(BaseModel):
    email: str
    plan: str
    payment_method: str
    proof_image: Optional[str] = None

@app.post("/api/orders")
def create_order(order: OrderCreate):
    # Validate with Pydantic Order model
    try:
        order_doc = Order(
            email=order.email,
            plan=order.plan,  # validated by Literal in schema
            payment_method=order.payment_method,  # validated by Literal in schema
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
    # Convert ObjectId to string
    for d in docs:
        _id = d.get('_id')
        if _id is not None:
            d['_id'] = str(_id)
    return {"items": docs}

@app.post("/api/orders/verify")
def verify_order(email: str):
    # Simple stub for now: just returns that verification is queued
    # Real verification would check payment gateway callback or admin review
    return {"email": email, "status": "queued"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
