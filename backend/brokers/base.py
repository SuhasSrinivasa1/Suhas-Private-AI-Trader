from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Literal

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]


@dataclass(frozen=True)
class BrokerCapabilities:
    read_account: bool
    read_positions: bool
    read_orders: bool
    place_orders: bool
    cancel_orders: bool
    withdrawals: bool
    paper: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BrokerOrderRequest:
    symbol: str
    market: str
    side: OrderSide
    quantity: float
    order_type: OrderType = "market"
    price: float | None = None


@dataclass(frozen=True)
class BrokerOrderResult:
    broker: str
    order_id: str
    status: str
    mode: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


class BrokerAdapter(ABC):
    name: str
    capabilities: BrokerCapabilities

    @abstractmethod
    def connect(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_account(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_orders(self) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def place_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> BrokerOrderResult:
        raise NotImplementedError
