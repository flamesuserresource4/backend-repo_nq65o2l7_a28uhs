import os
import smtplib
from email.message import EmailMessage
from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from datetime import datetime
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Order

app = FastAPI(title="E-Learn Store API", version="1.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class VerifyPayload(BaseModel):
    order_id: str
    action: str  # verify | reject
    note: Optional[str] = None


# ----- Email helpers -----
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_FROM = os.getenv("SMTP_FROM") or (SMTP_USER or "noreply@example.com")


def send_email(to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
        # Email not configured; skip silently
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    if text_body:
        msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True
    except Exception:
        return False


def send_status_email(order: Dict[str, Any]):
    email = order.get("email")
    status = order.get("status", "")
    plan = order.get("plan", "produk")
    if not email:
        return False
    subject = "Status Pesanan Anda"
    if status == "verified":
        subject = "Pesanan Terverifikasi — Akses Anda Siap"
        html = f"""
        <h2>Pesanan Terverifikasi ✅</h2>
        <p>Terima kasih! Pembayaran untuk paket <b>{plan}</b> telah kami terima dan verifikasi.</p>
        <p>Tim kami akan mengirim akses e-book/kelas ke email ini. Jika belum menerima dalam 5 menit, periksa folder spam/promotions.</p>
        <p>Butuh bantuan? Balas email ini.</p>
        """
        text = (
            "Pesanan Terverifikasi. Terima kasih! Pembayaran Anda untuk paket "
            f"{plan} telah kami terima dan verifikasi. Cek email untuk akses."
        )
    elif status == "rejected":
        subject = "Verifikasi Gagal — Perlu Tindakan"
        html = f"""
        <h2>Verifikasi Gagal ❌</h2>
        <p>Maaf, kami belum bisa memverifikasi pembayaran Anda untuk paket <b>{plan}</b>.</p>
        <p>Silakan balas email ini dengan bukti pembayaran yang jelas atau hubungi CS.</p>
        """
        text = (
            "Verifikasi gagal. Kami belum bisa memverifikasi pembayaran Anda."
        )
    else:
        html = f"<p>Status pesanan Anda: <b>{status}</b> untuk paket {plan}.</p>"
        text = f"Status pesanan Anda: {status} untuk paket {plan}."
    return send_email(email, subject, html, text)


@app.get("/test")
async def test_connection():
    try:
        await db.command("ping")
        return {"ok": True, "message": "Database connection OK"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/orders")
async def create_order(order: Order):
    data = order.dict()
    # Determine initial status
    if data.get("proof_image"):
        data["status"] = data.get("status") or "submitted"
    else:
        data["status"] = data.get("status") or "pending"

    inserted = await create_document("order", data)
    return {"id": str(inserted.inserted_id), "status": data["status"]}


@app.get("/api/orders")
async def list_orders(email: Optional[str] = None, limit: int = 50):
    filter_q: Dict[str, Any] = {}
    if email:
        filter_q["email"] = email
    docs = await get_documents("order", filter_q, limit=limit)
    for d in docs:
        d["id"] = str(d.pop("_id"))
        # Redact proof image in listing for performance
        if d.get("proof_image"):
            d["has_proof"] = True
            d["proof_image"] = None
    return {"items": docs}


@app.post("/api/orders/verify")
async def verify_order(payload: VerifyPayload):
    # Update order status by id
    try:
        oid = ObjectId(payload.order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order_id")

    doc = await db["order"].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Order not found")

    new_status = "verified" if payload.action == "verify" else "rejected"
    update: Dict[str, Any] = {"$set": {"status": new_status, "updated_at": datetime.utcnow()}}
    if payload.note:
        update["$set"]["note"] = payload.note

    await db["order"].update_one({"_id": oid}, update)

    # Fetch updated doc to email
    updated = await db["order"].find_one({"_id": oid})
    try:
        send_status_email(updated)
    except Exception:
        pass

    return {"id": payload.order_id, "status": new_status}


# Webhook endpoint to receive payment notifications (e.g., Midtrans/Xendit)
# Configure this URL in the payment gateway dashboard
@app.post("/api/webhook/payment")
async def payment_webhook(request: Request):
    payload = await request.json()
    # In production, verify signatures:
    # - Midtrans: use X-Callback-Signature / server key
    # - Xendit: use x-callback-token or x-callback-signature

    order_id = payload.get("order_id")
    paid = payload.get("paid") or payload.get("status") in {"PAID", "SETTLED", "CAPTURED", "SUCCESS"}

    if not order_id:
        raise HTTPException(status_code=400, detail="order_id missing")

    try:
        oid = ObjectId(order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order_id")

    new_status = "verified" if paid else "rejected"
    await db["order"].update_one({"_id": oid}, {"$set": {"status": new_status, "updated_at": datetime.utcnow()}})

    updated = await db["order"].find_one({"_id": oid})
    try:
        send_status_email(updated)
    except Exception:
        pass

    return {"ok": True, "id": order_id, "status": new_status}
