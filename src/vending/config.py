"""Frozen v1 proposal defaults. Money is always integer cents."""
import json
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

class Scenario(StrictModel):
    scenario_id: str = "benchmark-v1"
    version: str = "1.0-proposal"
    runtime_seconds: int = Field(default=7200, gt=0)
    max_days: int | None = Field(default=None, gt=0)
    starting_cash_cents: int = Field(default=50000, ge=0)
    daily_fee_cents: int = Field(default=200, gt=0)
    failure_limit: int = Field(default=10, gt=0)
    slot_capacity: int = Field(default=10, gt=0)
    quantity_cap: int = Field(default=1000, gt=0)
    retention_seconds: int = Field(default=3600, gt=0)
    day_multipliers: tuple[float, ...] = (1., 1., 1., 1., 1.1, 1.2, .8)
    durations: dict[str, int] = Field(default_factory=lambda: DURATIONS.copy())

    @model_validator(mode="after")
    def check(self):
        if self.scenario_id not in {"benchmark-v1", "smoke-v1"}:
            raise ValueError("unknown scenario")
        if self.max_days is not None and self.scenario_id != "smoke-v1":
            raise ValueError("day caps are only allowed in smoke scenarios")
        if len(self.day_multipliers) != 7 or any(not 0 < x < 10 for x in self.day_multipliers):
            raise ValueError("seven finite positive day multipliers required")
        if set(self.durations) != set(DURATIONS) or any(type(x) is not int or x < 0 or x % 5 for x in self.durations.values()):
            raise ValueError("durations must be nonnegative five-minute multiples")
        if any(self.durations[k] == 0 for k in DURATIONS if k != "end_day"):
            raise ValueError("actions must consume time")
        return self

def products():
    data = json.loads(files("vending").joinpath("fixtures/products.json").read_text())
    result = [Product.model_validate(p) for p in data]
    if len(result) != 10 or len({p.id for p in result}) != 10:
        raise ValueError("fixture requires ten unique products")
    return result
