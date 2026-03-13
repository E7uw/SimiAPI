import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key = Column(String(64), unique=True, nullable=False, index=True,
                     default=lambda: uuid.uuid4().hex)
    username = Column(String(100), unique=True, nullable=False, index=True)
    balance = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    orders = relationship("Order", back_populates="user", lazy="selectin")
    transactions = relationship("Transaction", back_populates="user", lazy="selectin")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    smsbower_activation_id = Column(String(100), nullable=True, index=True)
    service = Column(String(50), nullable=False)
    country = Column(String(10), nullable=True)
    phone_number = Column(String(30), nullable=True)
    cost_price = Column(Float, nullable=False, default=0.0)
    sell_price = Column(Float, nullable=False, default=0.0)
    status = Column(String(30), nullable=False, default="pending")
    sms_code = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    user = relationship("User", back_populates="orders")


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(20), nullable=False)
    amount = Column(Float, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user = relationship("User", back_populates="transactions")


class Config(Base):
    __tablename__ = "config"
    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
