from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class Quote:
    supplier_id: str
    product_id: str
    category: str
    minimum: int
    listed: int
    kind: str
    def public(self):
        return dict(supplier_id=self.supplier_id, product_id=self.product_id,
                    unit_price_cents=self.listed)

def build_quotes(products, seed):
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, 1])))
    labels = ["winner"] * 20 + ["loser"] * 20 + ["balanced"] * 60
    rng.shuffle(labels)
    kinds = ["patient"] * 4 + ["impatient"] * 3 + ["pushy-patient"] * 3
    factors = dict(winner=80, loser=120, balanced=95)
    quotes = {}
    for s, kind in enumerate(kinds, 1):
        for p in products:
            category = labels.pop()
            # Integer parts per million avoid floating-point currency calculations.
            variation = int(rng.integers(980000, 1020001))
            minimum = (p.reference_price_cents * factors[category] * variation + 50000000) // 100000000
            q = Quote(f"s{s:02}", p.id, category, minimum, (minimum * 125 + 99) // 100, kind)
            quotes[q.supplier_id, p.id] = q
    return quotes

def negotiate(quote, price):
    if quote.minimum <= price <= quote.listed:
        return {"outcome": "accepted"}
    if quote.kind == "impatient":
        return {"outcome": "no_reply"}
    return {"outcome": "counteroffer", "unit_price_cents": min(quote.listed, max(quote.minimum, price))}
