"""Frozen v1 proposal defaults. Money is always integer cents."""
import json
from typing import Literal
from importlib.resources import files
from pydantic import BaseModel, ConfigDict, Field, model_validator

DURATIONS = dict(observe=5, search_products=25, make_offer=75, get_inventory=5,
                 get_balance=5, get_machine=5, set_price=25, stock_items=75,
                 unstock_items=75, collect_cash=5, wait=300, end_day=0)

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

class Product(StrictModel):
    id: str
    name: str
    reference_price_cents: int = Field(gt=0)
    base_demand: float = Field(gt=0, allow_inf_nan=False)
    elasticity: float = Field(gt=0, allow_inf_nan=False)


def products():
    data = json.loads(files("vending").joinpath("fixtures/products.json").read_text())
    result = [Product.model_validate(p) for p in data]
    return result

class Supplier(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["patient", "impatient", "pushy-patient"]

class PairQuote(StrictModel):
    supplier_id: str
    product_id: str
    category: Literal["winner", "loser", "balanced"]
    minimum_cents: int = Field(gt=0)
    listed_cents: int = Field(gt=0)

    @model_validator(mode="after")
    def check(self):
        if self.minimum_cents > self.listed_cents:
            raise ValueError("minimum must not exceed listed price")
        return self

def default_suppliers():
    kinds = ["patient"] * 4 + ["impatient"] * 3 + ["pushy-patient"] * 3
    return tuple(Supplier(id=f"s{i:02}", kind=k) for i, k in enumerate(kinds, 1))

class Scenario(StrictModel):
    scenario_id: Literal["benchmark-v1", "smoke-v1"] = "benchmark-v1"
    version: str = "1.0-proposal"
    runtime_seconds: int = Field(default=7200, gt=0)
    max_days: int | None = Field(default=None, gt=0)
    starting_cash_cents: int = Field(default=50000, ge=0)
    daily_fee_cents: int = Field(default=200, ge=0)
    failure_limit: int = Field(default=10, gt=0)
    machine_rows: int = Field(default=4, gt=0)
    slots_per_row: int = Field(default=3, gt=0)
    slot_capacity: int = Field(default=10, gt=0)
    quantity_cap: int = Field(default=1000, gt=0)
    retention_seconds: int = Field(default=3600, gt=0)
    tick_minutes: int = Field(default=5, gt=0, le=1440)
    day_multipliers: tuple[float, ...] = (1., 1., 1., 1., 1.1, 1.2, .8)
    durations: dict[str, int] = Field(default_factory=lambda: DURATIONS.copy())
    min_price_percent: int = Field(default=25, gt=0)
    max_price_percent: int = Field(default=500, gt=0)
    products: tuple[Product, ...] = Field(default_factory=lambda: tuple(products()), min_length=1)
    suppliers: tuple[Supplier, ...] = Field(default_factory=default_suppliers, min_length=1)
    category_weights: dict[str, int] = Field(default_factory=lambda: dict(winner=20, loser=20, balanced=60))
    category_cost_percent: dict[str, int] = Field(default_factory=lambda: dict(winner=80, loser=120, balanced=95))
    cost_variation_min_ppm: int = Field(default=980000, gt=0)
    cost_variation_max_ppm: int = Field(default=1020000, gt=0)
    listed_price_percent: int = Field(default=125, ge=100)
    supplier_reshuffle_days: int = Field(default=30, gt=0)
    supplier_quotes: tuple[PairQuote, ...] = ()

    @model_validator(mode="after")
    def check(self):
        if self.max_days is not None and self.scenario_id != "smoke-v1":
            raise ValueError("day caps are only allowed in smoke scenarios")
        if not self.day_multipliers or any(not 0 <= x < float('inf') for x in self.day_multipliers):
            raise ValueError("finite nonnegative day multipliers required")
        if 1440 % self.tick_minutes:
            raise ValueError("tick_minutes must divide a 1440-minute day")
        if set(self.durations) != set(DURATIONS) or any(type(x) is not int or x < 0 or x % self.tick_minutes for x in self.durations.values()):
            raise ValueError("durations must be nonnegative tick multiples")
        if self.durations['end_day'] != 0 or any(self.durations[k] == 0 for k in DURATIONS if k != "end_day"):
            raise ValueError("end_day uses 0 (next midnight); other durations must be positive")
        if self.min_price_percent > self.max_price_percent:
            raise ValueError("invalid selling price bounds")
        if self.cost_variation_min_ppm > self.cost_variation_max_ppm:
            raise ValueError("invalid cost variation bounds")
        for mapping, minimum in ((self.category_weights, 0), (self.category_cost_percent, 1)):
            if set(mapping) != {'winner', 'loser', 'balanced'} or any(type(x) is not int or x < minimum for x in mapping.values()):
                raise ValueError("three nonnegative category weights and positive cost percentages required")
        if not sum(self.category_weights.values()):
            raise ValueError("at least one category weight must be positive")
        for catalog in (self.products, self.suppliers):
            if len({item.id for item in catalog}) != len(catalog):
                raise ValueError("duplicate catalog ID")
        for product in self.products:
            if (product.reference_price_cents * self.min_price_percent + 99) // 100 > product.reference_price_cents * self.max_price_percent // 100:
                raise ValueError("selling price bounds contain no integer cents")
        pairs = {(s.id, p.id) for s in self.suppliers for p in self.products}
        seen = set()
        for quote in self.supplier_quotes:
            key = quote.supplier_id, quote.product_id
            if key not in pairs or key in seen:
                raise ValueError("unknown or duplicate supplier quote pair")
            seen.add(key)
        return self
