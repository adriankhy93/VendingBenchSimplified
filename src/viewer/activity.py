"""Public activity summaries shared by saved runs and live Pi sessions."""
from collections import Counter


class Activity:
    def __init__(self):
        self.days = {}
        self.names = {}
        self.sold = Counter()
        self.completed_sales = Counter()
        self.day_events = []
        self.machine = None
        self.inventory = None
        self.previous_clock = None

    def day(self, number):
        return self.days.setdefault(number, dict(
            day=number, completed=False, actions={}, purchases=[], sales={},
            purchase_cost_cents=0, collected_cents=0,
        ))

    def add(self, record):
        response = record.get("response") or {}
        result = response.get("result") or {}
        clock = response.get("sim_time")
        for product in result.get("products", []):
            self.names[product["product_id"]] = product.get("name", product["product_id"])
        if "slots" in result:
            self.machine = dict(slots=result["slots"], prices=result.get("prices", {}), sim_time=clock)
        if "storage" in result:
            self.inventory = dict(storage=result["storage"], sim_time=clock)
        if not clock:
            return
        end = (clock["day"] - 1) * 1440 + clock["minute_of_day"]
        start = record.get("start_sim_time")
        if start:
            day_number = start["day"]
        elif "elapsed_minutes" in response:
            day_number = max(0, end - response["elapsed_minutes"]) // 1440 + 1
        else:
            day_number = (self.previous_clock or clock)["day"]
        self.previous_clock = clock
        day = self.day(day_number)
        action = record.get("action", "unknown")
        day["actions"][action] = day["actions"].get(action, 0) + 1
        payload = record.get("payload") or {}
        if action == "make_offer" and result.get("outcome") == "accepted":
            cost = result.get("total_cents", payload.get("quantity", 0) * payload.get("unit_price_cents", 0))
            day["purchases"].append(dict(
                product_id=payload.get("product_id", "unknown"),
                quantity=payload.get("quantity"), total_cents=cost,
            ))
            day["purchase_cost_cents"] += cost
        day["collected_cents"] += result.get("transferred_cents", 0)
        for event in response.get("events", []):
            if event.get("type") == "sales":
                self.sold[event["product_id"]] += event.get("quantity", 0)
            elif event.get("type") == "day":
                self.day_events.append(event)
                completed = self.day(event["day"])
                completed.update(completed=True, sales=event.get("sales", {}))
                self.completed_sales.update(event.get("sales", {}))
        # Day events contain exact per-day sales, including actions crossing midnight.
        # Remaining recorded sales belong to the current, unfinished day.
        current = self.day(clock["day"])
        current["sales"] = dict(self.sold - self.completed_sales)

    def fields(self):
        return dict(
            daily_activity=[self.days[key] for key in sorted(self.days)
                            if self.days[key]["actions"] or self.days[key]["completed"]
                            or self.days[key]["sales"]],
            sales=[dict(product_id=pid, name=self.names.get(pid, pid), quantity=qty)
                   for pid, qty in sorted(self.sold.items())],
            day_events=self.day_events[-100:], product_names=self.names,
            machine=self.machine, inventory=self.inventory,
        )
