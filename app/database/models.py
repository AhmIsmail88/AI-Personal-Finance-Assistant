from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    # Bug #6 fix: use timezone-aware DateTime
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    expenses       = relationship("Expense", back_populates="user")
    income         = relationship("Income", back_populates="user")
    fixed_payments = relationship("FixedPayment", back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    expenses = relationship("Expense", back_populates="category")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    item = Column(Text, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String, default="EGP")
    # Bug #6 fix: use timezone-aware DateTime
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="expenses")
    category = relationship("Category", back_populates="expenses")


class Income(Base):
    __tablename__ = "income"

    id          = Column(Integer, primary_key=True)
    user_id     = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    source_type = Column(String(20), nullable=False)   # salary | freelance | part_time | other
    description = Column(Text, nullable=True)
    amount      = Column(Numeric(12, 2), nullable=False)
    currency    = Column(String, default="EGP")
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="income")


class FixedPayment(Base):
    __tablename__ = "fixed_payments"

    id                 = Column(Integer, primary_key=True)
    user_id            = Column(BigInteger, ForeignKey("users.telegram_id"), nullable=False)
    name               = Column(Text, nullable=False)
    amount             = Column(Numeric(12, 2), nullable=False)
    currency           = Column(String, default="EGP")
    category           = Column(String(20), nullable=False)  # rent|loan|utility|subscription|other
    due_day            = Column(Integer, nullable=False)      # 1-31
    remind_days_before = Column(Integer, default=3)
    is_active          = Column(Integer, default=1)           # 1=True, 0=False (SQLite-safe)
    created_at         = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="fixed_payments")
