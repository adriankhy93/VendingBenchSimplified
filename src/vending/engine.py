"""Pure, staged business simulation. Lifecycle deadlines belong to the registry."""
from collections import Counter
from dataclasses import asdict
from .config import Scenario
from .models import ACTIONS, DomainValidation, Lot, Slot, transfer
from .suppliers import build_quotes, negotiate
from . import demand
from .scoring import score

class Engine:
    def __init__(self, config: Scenario, seed: int):
        self.config, self.seed = config, seed
        self.products = {p.id: p for p in config.products}
        self.quotes = build_quotes(list(self.products.values()), seed, config)
        self.slots = {f"r{r}s{s}": Slot(f"r{r}s{s}") for r in range(1, config.machine_rows + 1) for s in range(1, config.slots_per_row + 1)}
        self.storage = {p: [] for p in self.products}
        self.prices = {}
        self.cash, self.machine_cash, self.debt = config.starting_cash_cents, 0, 0
        self.minute = self.failures = self.purchase_count = self.action_count = 0
        self.state, self.reason = "running", None
        self.counts, self.sold, self.today = Counter(), Counter(), Counter()
        self.revenue = self.cogs = self.fees_assessed = self.fees_paid = self.discounts = self.invalid_calls = 0
        self.stockouts = Counter()
        self.private_events = []
        self.purchase_history = []
        self.deadline_utc = None

    def validate(self, action, payload):
        model = ACTIONS[action].model_validate(payload)
        args = model.model_dump(exclude_none=True)
        for field, catalog in (("product_id", self.products), ("supplier_id", {s for s, _ in self.quotes}), ("slot_id", self.slots)):
            if field in args and args[field] not in catalog:
                raise DomainValidation(f"unknown {field}")
        if args.get("quantity", 0) > self.config.quantity_cap:
            raise DomainValidation("quantity exceeds request cap")
        if action == "set_price":
            low, high = self.bounds(args["product_id"])
            if not low <= args["unit_price_cents"] <= high:
                raise DomainValidation(f"price must be between {low} and {high} cents")
        return args

    def bounds(self, pid):
        ref = self.products[pid].reference_price_cents
        return (ref * self.config.min_price_percent + 99) // 100, ref * self.config.max_price_percent // 100

    def balance(self):
        return dict(cash_cents=self.cash, machine_cash_cents=self.machine_cash, fee_debt_cents=self.debt)

    def inventory(self):
        return {p: {"quantity": sum(l.quantity for l in lots),
                    "acquisition_cost_cents": sum(l.quantity * l.unit_cost_cents for l in lots),
                    "lots": [asdict(l) for l in lots]} for p, lots in self.storage.items()}

    def machine(self):
        return dict(slots=[dict(slot_id=s.id, product_id=s.product_id, quantity=s.quantity,
                                capacity=self.config.slot_capacity) for s in self.slots.values()],
                    prices=self.prices.copy(), units_sold=dict(self.sold), current_day_sales=dict(self.today))

    def catalog(self, product_id=None):
        return dict(products=[dict(product_id=p.id, name=p.name, reference_price_cents=p.reference_price_cents,
                                   min_price_cents=self.bounds(p.id)[0], max_price_cents=self.bounds(p.id)[1])
                              for p in self.products.values() if product_id in (None, p.id)],
                    suppliers=[s.id for s in self.config.suppliers],
                    quotes=[q.public() for q in self.quotes.values() if product_id in (None, q.product_id)])

    def observe(self):
        return dict(scenario_version=self.config.version, **self.catalog(), **self.balance(), **self.machine(), storage=self.inventory(),
                    purchases=list(self.purchase_history),
                    rules=dict(durations=self.config.durations, slot_capacity=self.config.slot_capacity,
                               machine_rows=self.config.machine_rows, slots_per_row=self.config.slots_per_row,
                               tick_minutes=self.config.tick_minutes, quantity_cap=self.config.quantity_cap, daily_fee_cents=self.config.daily_fee_cents,
                               failure_limit=self.config.failure_limit, max_days=self.config.max_days,
                               runtime_seconds=self.config.runtime_seconds, deadline_utc=self.deadline_utc,
                               scoring="cash + machine cash + inventory at acquisition cost - fee debt",
                               fees="Spendable cash pays arrears first, then current fee; partial payments allowed."))

    def apply(self, action, args):
        result = {}
        reject = lambda reason: dict(outcome="rejected", reason=reason)
        if action == "make_offer":
            pid, sid, qty, price = (args[k] for k in ("product_id", "supplier_id", "quantity", "unit_price_cents"))
            q = self.quotes[sid, pid]
            result = negotiate(q, price)
            if result["outcome"] == "accepted":
                total = qty * price
                if total > self.cash:
                    result = dict(outcome="insufficient_funds")
                else:
                    self.cash -= total
                    self.purchase_count += 1
                    buy = f"buy_{self.purchase_count:04}"
                    self.storage[pid].append(Lot(buy, qty, price, self.purchase_count))
                    self.discounts += (q.listed - price) * qty
                    result.update(purchase_id=buy, total_cents=total)
                    self.purchase_history.append(dict(purchase_id=buy, **args))
            elif result["outcome"] == "counteroffer":
                result.update(supplier_id=sid, product_id=pid, quantity=qty)
            if q.kind == "pushy-patient" and len(self.products) > 1:
                other = next(p for p in self.products if p != pid)
                result["upsell"] = self.quotes[sid, other].public()
        elif action == "set_price":
            self.prices[args["product_id"]] = args["unit_price_cents"]
            result = args.copy()
        elif action in ("stock_items", "unstock_items"):
            slot, qty = self.slots[args["slot_id"]], args["quantity"]
            pid = args.get("product_id", slot.product_id)
            if action == "stock_items":
                if pid not in self.prices:
                    return reject("price_required")
                if slot.product_id not in (None, pid):
                    return reject("slot_product_mismatch")
                if slot.quantity + qty > self.config.slot_capacity:
                    return reject("slot_full")
                if sum(l.quantity for l in self.storage[pid]) < qty:
                    return reject("insufficient_stock")
                transfer(self.storage[pid], slot.lots, qty)
                slot.product_id = pid
            else:
                if slot.quantity < qty:
                    return reject("insufficient_stock")
                transfer(slot.lots, self.storage[pid], qty)
                if not slot.quantity:
                    slot.product_id = None
            result = dict(moved_quantity=qty, slot_id=slot.id, slot_quantity=slot.quantity,
                          storage_quantity=sum(l.quantity for l in self.storage[pid]))
        elif action == "collect_cash":
            result = dict(transferred_cents=self.machine_cash)
            self.cash += self.machine_cash
            self.machine_cash = 0
        elif action == "search_products":
            result = self.catalog(args.get("product_id"))
        return result

    def advance(self, minutes):
        events, sales = [], Counter()
        step = self.config.tick_minutes
        if minutes < 0 or minutes % step:
            raise ValueError("advancement must be a nonnegative tick multiple")
        for _ in range(minutes // step):
            tick = self.minute // step
            multiplier = self.config.day_multipliers[(self.minute // 1440) % len(self.config.day_multipliers)]
            for index, (pid, p) in enumerate(self.products.items()):
                price = self.prices.get(pid, p.reference_price_cents)
                count = demand.sample(self.seed, index, tick, demand.expected_daily(p, price, multiplier) * step / 1440)
                available = sum(s.quantity for s in self.slots.values() if s.product_id == pid)
                sold = min(available, count)
                self.stockouts[pid] += count - sold
                if count:
                    self.private_events.append(dict(tick=tick, product_id=pid, demand=count, sold=sold))
                remaining = sold
                for slot in self.slots.values():
                    if slot.product_id != pid or not remaining:
                        continue
                    take = min(slot.quantity, remaining)
                    self.cogs += transfer(slot.lots, [], take)
                    remaining -= take
                    if not slot.quantity:
                        slot.product_id = None
                revenue = sold * price
                self.machine_cash += revenue
                self.revenue += revenue
                self.sold[pid] += sold
                self.today[pid] += sold
                sales[pid] += sold
            self.minute += step
            if self.minute % 1440 == 0:
                arrears = min(self.cash, self.debt)
                self.cash -= arrears
                self.debt -= arrears
                fee = self.config.daily_fee_cents
                paid = min(self.cash, fee)
                self.cash -= paid
                self.debt += fee - paid
                self.fees_assessed += fee
                self.fees_paid += arrears + paid
                self.failures = self.failures + 1 if paid < fee else 0
                events.append(dict(type="day", day=self.minute // 1440, sales=dict(self.today),
                                   fee_assessed_cents=fee, fee_paid_cents=paid, arrears_paid_cents=arrears,
                                   failure_streak=self.failures, **self.balance()))
                self.today.clear()
                if self.failures >= self.config.failure_limit:
                    self.state, self.reason = "ended", "missed_fees"
                elif self.config.max_days and self.minute // 1440 >= self.config.max_days:
                    self.state, self.reason = "ended", "smoke_day_cap"
                if self.state == "ended":
                    break
        return ([dict(type="sales", product_id=p, quantity=n) for p, n in sales.items() if n] + events)

    def execute(self, action, payload):
        if self.state != "running":
            raise RuntimeError("engine is terminal")
        args = self.validate(action, payload)
        start = self.minute
        result = self.apply(action, args)
        self.action_count += 1
        self.counts[action] += 1
        minutes = 1440 - self.minute % 1440 if action == "end_day" else self.config.durations[action]
        events = self.advance(minutes)
        # Read actions expose the resulting state, including incidental sales.
        if action == "observe":
            result = self.observe()
        elif action == "get_balance":
            result = self.balance()
        elif action == "get_inventory":
            result = dict(storage=self.inventory())
        elif action == "get_machine":
            result = self.machine()
        response = dict(action_id=f"act_{self.action_count:04}", state=self.state,
                        sim_time=dict(day=self.minute // 1440 + 1, minute_of_day=self.minute % 1440),
                        elapsed_minutes=self.minute - start, result=result, events=events,
                        metrics=dict(**self.balance(), units_sold=sum(self.sold.values())), termination_reason=self.reason)
        if self.state == "ended":
            response["score"] = score(self)
        return response

    def summary(self, complete=True):
        return dict(state=self.state, termination_reason=self.reason, complete=complete,
                    scenario_version=self.config.version, score=score(self), simulated_minutes=self.minute,
                    completed_days=self.minute // 1440,
                    metrics=dict(revenue_cents=self.revenue, cost_of_goods_sold_cents=self.cogs,
                                 fees_assessed_cents=self.fees_assessed, fees_paid_cents=self.fees_paid,
                                 fees_unpaid_cents=self.debt, units_sold=dict(self.sold), purchases=self.purchase_count,
                                 negotiated_discounts_cents=self.discounts, action_counts=dict(self.counts),
                                 invalid_calls=self.invalid_calls))
