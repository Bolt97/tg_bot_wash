# app/models/transactions.py
from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Literal

from pydantic import BaseModel, Field, validator


# --- Базовые вложенные модели из ответа ---

class Fiscal(BaseModel):
    address: Optional[str] = None
    place: Optional[str] = None
    qr: Optional[str] = None
    vm_id: Optional[str] = None


class Product(BaseModel):
    gtin: Optional[str] = None
    id: int
    name: str
    price: Optional[int] = None  # цена в копейках (судя по примерам)
    tag1212: Optional[int] = None
    vat: Optional[int] = None


class CashBody(BaseModel):
    # в примерах:
    # { "amount": "300.00", "type": "CASH" }
    amount: Optional[str] = None
    type: Optional[str] = None


class CashlessBody(BaseModel):
    # в примерах полей много, нам критичны amount и issuer
    amount: Optional[str] = None
    type: Optional[str] = None  # "CASHLESS"
    issuer: Optional[str] = None  # "VISA" | "MIR" | "Yandex.Wash" | ...
    # Остальные поля оставляем опционально, чтоб не падать при расширении API
    aid: Optional[str] = None
    amount2: Optional[str] = None
    application_label: Optional[str] = None
    auth_id: Optional[str] = None
    batch: Optional[str] = None
    cda_result: Optional[str] = None
    cvm: Optional[str] = None
    ern: Optional[str] = None
    host_localtime_at: Optional[str] = None
    invoice: Optional[str] = None
    journal_id: Optional[int] = None
    kvr: Optional[str] = None
    manual_reversal_supported: Optional[bool] = None
    merchant: Optional[str] = None
    pan: Optional[str] = None
    pos_entry_mode: Optional[str] = None
    response_code: Optional[str] = None
    rrn: Optional[str] = None
    seller_id: Optional[str] = None
    tc: Optional[str] = None
    transaction_duration_s: Optional[int] = None
    tvr: Optional[str] = None
    visual_host_response: Optional[str] = None


class Payment(BaseModel):
    approved: bool
    name: Optional[str] = None  # "SALE"
    pos_localtime_at: Optional[str] = None  # "2025-09-08T00:07:59"
    pos_localtime_offset_s: Optional[int] = None

    cash_amount: Optional[str] = None
    cash_body: Optional[CashBody] = None

    cashless_amount: Optional[str] = None
    cashless_body: Optional[CashlessBody] = None

    @staticmethod
    def _to_decimal(s: Optional[str]) -> Decimal:
        if s is None or s == "":
            return Decimal("0")
        # Защита от запятых, на всякий случай
        return Decimal(s.replace(",", "."))

    def amount_and_channel(self) -> tuple[Decimal, "RevenueChannel | None"]:
        """
        Возвращает (сумма, канал) по правилам:
        - если approved == False → (0, None)
        - если есть cash_body → сумма = cash_amount, канал=CASH
        - иначе если есть cashless_body → сумма=cashless_amount,
              канал = YANDEX_WASH если issuer == "Yandex.Wash", иначе CARD
        - иначе (0, None)
        """
        if not self.approved:
            return Decimal("0"), None

        if self.cash_body is not None:
            return self._to_decimal(self.cash_amount), RevenueChannel.CASH

        if self.cashless_body is not None:
            issuer = (self.cashless_body.issuer or "").strip()
            amt = self._to_decimal(self.cashless_amount)
            if issuer.lower() == "yandex.wash":
                return amt, RevenueChannel.YANDEX_WASH
            return amt, RevenueChannel.CARD

        return Decimal("0"), None


class RevenueChannel(str, Enum):
    CASH = "cash"
    CARD = "card"
    YANDEX_WASH = "yandex_wash"


class TransactionItem(BaseModel):
    cancelled: bool
    change_id: Optional[int] = None
    completed: Optional[bool] = None
    currency: Optional[str] = None  # "RUB"
    expect_fiscalization: Optional[bool] = None
    fiscal: Optional[Fiscal] = None

    id: int
    location: Optional[str] = None
    organization: Optional[str] = None
    organization_name: Optional[str] = None

    payment: Payment

    pos_localtime_at: Optional[str] = None  # дубль того же времени
    product_id: Optional[int] = None
    product_name: Optional[str] = None

    products: Optional[List[Product]] = None

    terminal_id: Optional[str] = None
    trace_id: Optional[str] = None
    unit_id: Optional[int] = None

    def revenue_amount_and_channel(self) -> tuple[Decimal, Optional[RevenueChannel]]:
        """
        Удобный прокси к payment.amount_and_channel(), дополнительно проверяем cancelled.
        Если транзакция отменена — не учитываем.
        """
        if self.cancelled:
            return Decimal("0"), None
        return self.payment.amount_and_channel()


class TransactionsResponse(BaseModel):
    items: List[TransactionItem] = Field(default_factory=list)
    next_id: Optional[str] = None  # иногда может быть int/str/null — оставим str|None

    @validator("items", pre=True)
    def _items_default(cls, v):
        return v or []