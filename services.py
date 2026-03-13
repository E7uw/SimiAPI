import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Order, Transaction, Config
from app.smsbower import smsbower_client
from app.config import settings

logger = logging.getLogger(__name__)


async def get_commission_rate(session: AsyncSession) -> float:
    result = await session.execute(select(Config).where(Config.key == "commission_rate"))
    cfg = result.scalar_one_or_none()
    return float(cfg.value) if cfg else settings.COMMISSION_RATE


async def set_commission_rate(session: AsyncSession, rate: float):
    result = await session.execute(select(Config).where(Config.key == "commission_rate"))
    cfg = result.scalar_one_or_none()
    if cfg:
        cfg.value = str(rate)
    else:
        session.add(Config(key="commission_rate", value=str(rate)))
    await session.commit()


def apply_markup(price: float, commission: float) -> float:
    return round(price * (1 + commission), 2)


async def authenticate_user(session: AsyncSession, api_key: str) -> Optional[User]:
    result = await session.execute(
        select(User).where(User.api_key == api_key, User.is_active == True)
    )
    return result.scalar_one_or_none()


async def create_user(session: AsyncSession, username: str) -> User:
    user = User(username=username)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_all_users(session: AsyncSession, offset: int = 0, limit: int = 50):
    result = await session.execute(
        select(User).order_by(User.id.desc()).offset(offset).limit(limit)
    )
    return result.scalars().all()


async def add_balance(session: AsyncSession, user: User, amount: float, note: str = "") -> User:
    user.balance = round(user.balance + amount, 2)
    session.add(Transaction(user_id=user.id, type="topup", amount=amount, note=note))
    await session.commit()
    await session.refresh(user)
    return user


async def set_balance(session: AsyncSession, user: User, amount: float, note: str = "") -> User:
    old = user.balance
    user.balance = round(amount, 2)
    session.add(Transaction(
        user_id=user.id, type="set_balance", amount=amount,
        note=note or f"Balance set from {old} to {amount}"
    ))
    await session.commit()
    await session.refresh(user)
    return user


async def deduct_balance(session: AsyncSession, user: User, amount: float, note: str = "") -> User:
    user.balance = round(user.balance - amount, 2)
    session.add(Transaction(user_id=user.id, type="deduction", amount=amount, note=note))
    await session.commit()
    await session.refresh(user)
    return user


async def refund_balance(session: AsyncSession, user: User, amount: float, note: str = "") -> User:
    user.balance = round(user.balance + amount, 2)
    session.add(Transaction(user_id=user.id, type="refund", amount=amount, note=note))
    await session.commit()
    await session.refresh(user)
    return user


async def get_transactions(session: AsyncSession, user_id: int, limit: int = 20):
    result = await session.execute(
        select(Transaction).where(Transaction.user_id == user_id)
        .order_by(Transaction.id.desc()).limit(limit)
    )
    return result.scalars().all()


async def get_stats(session: AsyncSession) -> dict:
    total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
    active_users = (await session.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )).scalar() or 0
    total_orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    revenue = (await session.execute(
        select(func.coalesce(func.sum(Order.sell_price), 0))
    )).scalar() or 0
    cost = (await session.execute(
        select(func.coalesce(func.sum(Order.cost_price), 0))
    )).scalar() or 0
    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_orders": total_orders,
        "total_revenue": round(revenue, 2),
        "total_cost": round(cost, 2),
        "net_profit": round(revenue - cost, 2),
    }


async def handle_get_balance(session: AsyncSession, user: User) -> str:
    return f"ACCESS_BALANCE:{user.balance:.2f}"


async def handle_get_services(session: AsyncSession, user: User, country: Optional[str] = None) -> str:
    commission = await get_commission_rate(session)
    raw = await smsbower_client.get_services(country)
    if isinstance(raw, dict):
        marked_up = {}
        for svc_key, svc_data in raw.items():
            if isinstance(svc_data, dict):
                new_svc = {}
                for country_key, country_data in svc_data.items():
                    if isinstance(country_data, dict) and "cost" in country_data:
                        new_country = dict(country_data)
                        new_country["cost"] = apply_markup(float(country_data["cost"]), commission)
                        new_svc[country_key] = new_country
                    else:
                        new_svc[country_key] = country_data
                marked_up[svc_key] = new_svc
            else:
                marked_up[svc_key] = svc_data
        return json.dumps(marked_up)
    return raw


async def handle_get_number(session: AsyncSession, user: User, service: str, country: str = "0") -> str:
    commission = await get_commission_rate(session)
    raw = await smsbower_client.get_services(country)
    cost_price = 0.0
    if isinstance(raw, dict) and service in raw:
        svc_data = raw[service]
        if isinstance(svc_data, dict):
            if country in svc_data and isinstance(svc_data[country], dict):
                cost_price = float(svc_data[country].get("cost", 0))
            else:
                for k, v in svc_data.items():
                    if isinstance(v, dict) and "cost" in v:
                        cost_price = float(v["cost"])
                        break
    sell_price = apply_markup(cost_price, commission)
    if user.balance < sell_price:
        return "NO_BALANCE"
    result = await smsbower_client.get_number(service, country)
    if result.startswith("ACCESS_NUMBER"):
        parts = result.split(":")
        if len(parts) >= 3:
            activation_id, phone = parts[1], parts[2]
            await deduct_balance(session, user, sell_price, f"Number {phone} for {service}")
            order = Order(
                user_id=user.id, smsbower_activation_id=activation_id,
                service=service, country=country, phone_number=phone,
                cost_price=cost_price, sell_price=sell_price, status="waiting"
            )
            session.add(order)
            await session.commit()
    return result


async def handle_get_status(session: AsyncSession, user: User, activation_id: str) -> str:
    result = await session.execute(
        select(Order).where(Order.smsbower_activation_id == activation_id, Order.user_id == user.id)
    )
    order = result.scalar_one_or_none()
    if not order:
        return "BAD_KEY"
    result_str = await smsbower_client.get_status(activation_id)
    if result_str.startswith("STATUS_OK"):
        code = result_str.split(":")[1] if ":" in result_str else ""
        order.status = "completed"
        order.sms_code = code
    elif result_str.startswith("STATUS_CANCEL"):
        order.status = "cancelled"
        await refund_balance(session, user, order.sell_price, f"Refund order #{order.id}")
    order.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return result_str


async def handle_set_status(session: AsyncSession, user: User, activation_id: str, status: str) -> str:
    result = await session.execute(
        select(Order).where(Order.smsbower_activation_id == activation_id, Order.user_id == user.id)
    )
    order = result.scalar_one_or_none()
    if not order:
        return "BAD_KEY"
    result_str = await smsbower_client.set_status(activation_id, status)
    if status == "8" and "ACCESS_CANCEL" in result_str:
        order.status = "cancelled"
        await refund_balance(session, user, order.sell_price, f"Cancelled {activation_id}")
    elif status == "6":
        order.status = "completed"
    await session.commit()
    return result_str


async def handle_get_active_orders(session: AsyncSession, user: User) -> str:
    result = await session.execute(
        select(Order).where(
            Order.user_id == user.id,
            Order.status.in_(["waiting", "retry", "pending"])
        ).order_by(Order.id.desc())
    )
    active = result.scalars().all()
    if not active:
        return "NO_ACTIVATIONS"
    return json.dumps({
        str(o.smsbower_activation_id): {
            "service": o.service, "phone": o.phone_number,
            "status": o.status, "cost": o.sell_price
        } for o in active
    })
