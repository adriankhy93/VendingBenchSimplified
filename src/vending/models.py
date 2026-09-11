from dataclasses import dataclass, field
from pydantic import Field
from .config import StrictModel

class Empty(StrictModel):
    pass
class Search(StrictModel):
    product_id: str | None = None
class Price(StrictModel):
    product_id: str
    unit_price_cents: int = Field(gt=0)
class Offer(Price):
    supplier_id: str
    quantity: int = Field(gt=0)
class Stock(StrictModel):
    slot_id: str
    product_id: str
    quantity: int = Field(gt=0)
class Unstock(StrictModel):
    slot_id: str
    quantity: int = Field(gt=0)

ACTIONS = {name: Empty for name in ("observe", "get_inventory", "get_balance", "get_machine", "collect_cash", "wait", "end_day")}
ACTIONS.update(search_products=Search, make_offer=Offer, set_price=Price, stock_items=Stock, unstock_items=Unstock)

class DomainValidation(ValueError):
    pass

@dataclass
class Lot:
    purchase_id: str
    quantity: int
    unit_cost_cents: int
    order: int

@dataclass
class Slot:
    id: str
    product_id: str | None = None
    lots: list[Lot] = field(default_factory=list)
    @property
    def quantity(self):
        return sum(l.quantity for l in self.lots)

def transfer(source: list[Lot], target: list[Lot], quantity: int) -> int:
    """Move oldest acquisition lots, preserving cost and original FIFO order."""
    cost = 0
    source.sort(key=lambda lot: lot.order)
    while quantity:
        lot = source[0]
        count = min(quantity, lot.quantity)
        target.append(Lot(lot.purchase_id, count, lot.unit_cost_cents, lot.order))
        cost += count * lot.unit_cost_cents
        lot.quantity -= count
        quantity -= count
        if not lot.quantity:
            source.pop(0)
    target.sort(key=lambda lot: lot.order)
    return cost

# Response models also serve the generated REST documentation.
from typing import Any, Literal

class Created(StrictModel):
    env_id: str

class Status(StrictModel):
    state: Literal['running', 'ended', 'unavailable']

class SimTime(StrictModel):
    day: int = Field(ge=1)
    minute_of_day: int = Field(ge=0, lt=1440)

class Score(StrictModel):
    cash_cents: int
    machine_cash_cents: int
    inventory_value_cents: int
    gross_assets_cents: int
    fee_debt_cents: int
    score_cents: int
    net_profit_cents: int

class ActionResponse(Status):
    action_id: str
    sim_time: SimTime
    elapsed_minutes: int
    result: dict[str, Any]
    events: list[dict[str, Any]]
    metrics: dict[str, int]
    termination_reason: str | None
    score: Score | None = None
