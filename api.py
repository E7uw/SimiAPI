"""
SMS Reseller API
- User endpoints: /api/?action=...&api_key=USER_KEY
- Admin endpoints: /admin/?action=...&api_key=MASTER_KEY
"""
import json
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Query, Depends
from fastapi.responses import PlainTextResponse, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db, init_db
from app.services import (
    authenticate_user,
    handle_get_balance,
    handle_get_services,
    handle_get_number,
    handle_get_status,
    handle_set_status,
    handle_get_active_orders,
    create_user,
    get_user_by_username,
    get_all_users,
    add_balance,
    set_balance,
    set_commission_rate,
    get_commission_rate,
    get_transactions,
    get_stats,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def get_api_key_from_request(request: Request) -> str:
    return request.query_params.get("api_key", get_remote_address(request))


limiter = Limiter(key_func=get_api_key_from_request)

app = FastAPI(
    title="SMS Reseller API",
    description="OTP/SMS reseller middleware",
    version="1.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return PlainTextResponse("RATE_LIMIT_EXCEEDED", status_code=429)


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "service": "SMS Reseller API", "version": "1.0.0"}


@app.get("/health")
async def health():
    from app.smsbower import smsbower_client
    return await smsbower_client.health_check()


# ── User API ──────────────────────────────────────────────────────────────────

@app.get("/api/")
@limiter.limit(f"{settings.RATE_LIMIT_PER_MINUTE}/minute")
async def api_handler(
    request: Request,
    action: str = Query(...),
    api_key: str = Query(...),
    service: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate_user(db, api_key)
    if not user:
        return PlainTextResponse("BAD_KEY")

    try:
        if action == "getBalance":
            return PlainTextResponse(await handle_get_balance(db, user))

        elif action == "getServices":
            result = await handle_get_services(db, user, country)
            try:
                return JSONResponse(json.loads(result))
            except Exception:
                return PlainTextResponse(result)

        elif action == "getNumber":
            if not service:
                return PlainTextResponse("BAD_ACTION")
            return PlainTextResponse(await handle_get_number(db, user, service, country or "0"))

        elif action == "getStatus":
            if not id:
                return PlainTextResponse("BAD_ACTION")
            return PlainTextResponse(await handle_get_status(db, user, id))

        elif action == "setStatus":
            if not id or not status:
                return PlainTextResponse("BAD_ACTION")
            return PlainTextResponse(await handle_set_status(db, user, id, status))

        elif action == "getActiveOrders":
            result = await handle_get_active_orders(db, user)
            try:
                return JSONResponse(json.loads(result))
            except Exception:
                return PlainTextResponse(result)

        else:
            return PlainTextResponse("BAD_ACTION")

    except Exception as e:
        logger.exception(f"API error action={action}: {e}")
        return PlainTextResponse("ERROR_SQL")


# ── Admin API ─────────────────────────────────────────────────────────────────

def is_admin(api_key: str) -> bool:
    return api_key == settings.ADMIN_MASTER_KEY


@app.get("/admin/")
async def admin_handler(
    request: Request,
    action: str = Query(...),
    api_key: str = Query(...),
    username: Optional[str] = Query(None),
    amount: Optional[float] = Query(None),
    rate: Optional[float] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin actions (require ADMIN_MASTER_KEY):

    createUser   - ?action=createUser&username=john
    listUsers    - ?action=listUsers
    topup        - ?action=topup&username=john&amount=10
    setBalance   - ?action=setBalance&username=john&amount=50
    banUser      - ?action=banUser&username=john
    unbanUser    - ?action=unbanUser&username=john
    userInfo     - ?action=userInfo&username=john
    transactions - ?action=transactions&username=john
    setCommission- ?action=setCommission&rate=0.15
    getCommission- ?action=getCommission
    stats        - ?action=stats
    sourceBalance- ?action=sourceBalance
    """
    if not is_admin(api_key):
        return JSONResponse({"error": "UNAUTHORIZED"}, status_code=401)

    try:
        # ── Create user ──
        if action == "createUser":
            if not username:
                return JSONResponse({"error": "username required"})
            existing = await get_user_by_username(db, username)
            if existing:
                return JSONResponse({"error": "username already exists"})
            user = await create_user(db, username)
            return JSONResponse({
                "success": True,
                "username": user.username,
                "api_key": user.api_key,
                "balance": user.balance,
            })

        # ── List users ──
        elif action == "listUsers":
            users = await get_all_users(db)
            return JSONResponse([{
                "id": u.id,
                "username": u.username,
                "api_key": u.api_key,
                "balance": u.balance,
                "is_active": u.is_active,
                "created_at": str(u.created_at),
            } for u in users])

        # ── Top up balance ──
        elif action == "topup":
            if not username or amount is None:
                return JSONResponse({"error": "username and amount required"})
            user = await get_user_by_username(db, username)
            if not user:
                return JSONResponse({"error": "user not found"})
            user = await add_balance(db, user, amount, "Admin topup")
            return JSONResponse({"success": True, "username": username, "new_balance": user.balance})

        # ── Set balance ──
        elif action == "setBalance":
            if not username or amount is None:
                return JSONResponse({"error": "username and amount required"})
            user = await get_user_by_username(db, username)
            if not user:
                return JSONResponse({"error": "user not found"})
            user = await set_balance(db, user, amount, "Admin set balance")
            return JSONResponse({"success": True, "username": username, "new_balance": user.balance})

        # ── Ban user ──
        elif action == "banUser":
            if not username:
                return JSONResponse({"error": "username required"})
            user = await get_user_by_username(db, username)
            if not user:
                return JSONResponse({"error": "user not found"})
            user.is_active = False
            await db.commit()
            return JSONResponse({"success": True, "username": username, "is_active": False})

        # ── Unban user ──
        elif action == "unbanUser":
            if not username:
                return JSONResponse({"error": "username required"})
            user = await get_user_by_username(db, username)
            if not user:
                return JSONResponse({"error": "user not found"})
            user.is_active = True
            await db.commit()
            return JSONResponse({"success": True, "username": username, "is_active": True})

        # ── User info ──
        elif action == "userInfo":
            if not username:
                return JSONResponse({"error": "username required"})
            user = await get_user_by_username(db, username)
            if not user:
                return JSONResponse({"error": "user not found"})
            return JSONResponse({
                "id": user.id,
                "username": user.username,
                "api_key": user.api_key,
                "balance": user.balance,
                "is_active": user.is_active,
                "created_at": str(user.created_at),
            })

        # ── Transactions ──
        elif action == "transactions":
            if not username:
                return JSONResponse({"error": "username required"})
            user = await get_user_by_username(db, username)
            if not user:
                return JSONResponse({"error": "user not found"})
            txns = await get_transactions(db, user.id)
            return JSONResponse([{
                "id": t.id,
                "type": t.type,
                "amount": t.amount,
                "note": t.note,
                "created_at": str(t.created_at),
            } for t in txns])

        # ── Set commission ──
        elif action == "setCommission":
            if rate is None:
                return JSONResponse({"error": "rate required (e.g. 0.15 for 15%)"})
            await set_commission_rate(db, rate)
            return JSONResponse({"success": True, "commission_rate": rate})

        # ── Get commission ──
        elif action == "getCommission":
            current = await get_commission_rate(db)
            return JSONResponse({"commission_rate": current, "percent": f"{current*100:.1f}%"})

        # ── Platform stats ──
        elif action == "stats":
            return JSONResponse(await get_stats(db))

        # ── Source balance ──
        elif action == "sourceBalance":
            from app.smsbower import smsbower_client
            balance = await smsbower_client.get_balance()
            return JSONResponse({"source_balance": balance})

        else:
            return JSONResponse({"error": "BAD_ACTION"})

    except Exception as e:
        logger.exception(f"Admin error action={action}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
