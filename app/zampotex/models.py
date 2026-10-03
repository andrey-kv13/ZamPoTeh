from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_name: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(120))
    interval_profile: Mapped[str] = mapped_column(String(16), default="normal")
    consent_offer_version: Mapped[str | None] = mapped_column(String(16))
    consent_privacy_version: Mapped[str | None] = mapped_column(String(16))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    active_car_id: Mapped[int | None] = mapped_column(Integer)
    mileage_nag_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cars: Mapped[list["Car"]] = relationship(back_populates="user")


class Car(Base):
    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    vin: Mapped[str] = mapped_column(String(17), index=True)
    brand: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(80))
    year: Mapped[int] = mapped_column(Integer)
    engine_code: Mapped[str | None] = mapped_column(String(32))
    power_hp: Mapped[int | None] = mapped_column(Integer)
    gearbox: Mapped[str | None] = mapped_column(String(32))
    gearbox_code: Mapped[str | None] = mapped_column(String(32))
    city: Mapped[str | None] = mapped_column(String(120))
    mileage_km: Mapped[int | None] = mapped_column(Integer)
    mileage_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pr_codes: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    ownership: Mapped[str] = mapped_column(String(16), default="current")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="cars")


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    car_id: Mapped[int | None] = mapped_column(ForeignKey("cars.id"), nullable=True)
    vin: Mapped[str] = mapped_column(String(17), index=True)
    text: Mapped[str] = mapped_column(Text)
    side: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    binding_level: Mapped[str] = mapped_column(String(32), default="unverified")
    summary: Mapped[str] = mapped_column(Text)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    counted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShelfItem(Base):
    __tablename__ = "shelf_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id"))
    search_id: Mapped[int | None] = mapped_column(ForeignKey("searches.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    oem: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="in_stock")
    qty: Mapped[int] = mapped_column(Integer, default=1)
    buy_price: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id"))
    work_code: Mapped[str] = mapped_column(String(32))
    basis: Mapped[str] = mapped_column(String(32), default="user_stated")
    next_mileage: Mapped[int | None] = mapped_column(Integer)
    next_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interval_km: Mapped[int | None] = mapped_column(Integer)
    warn_km: Mapped[int] = mapped_column(Integer, default=1000)
    warn_days: Mapped[int] = mapped_column(Integer, default=14)
    last_sent_key: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LinkCode(Base):
    __tablename__ = "link_codes"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TransferCode(Base):
    __tablename__ = "transfer_codes"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class CarPhoto(Base):
    __tablename__ = "car_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    car_id: Mapped[int | None] = mapped_column(ForeignKey("cars.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
