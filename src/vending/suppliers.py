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

def build_quotes(products, seed, config=None, epoch=0):
    from .config import Scenario
    config = config or Scenario()
    # Keep the original market unchanged; later periods have independent streams.
    entropy = [seed, 1] if epoch == 0 else [seed, 1, epoch]
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(entropy)))
    categories = ['winner', 'loser', 'balanced']
    total_pairs = len(products) * len(config.suppliers)
    total_weight = sum(config.category_weights.values())
    counts = {c: total_pairs * config.category_weights[c] // total_weight for c in categories}
    # Largest remainder allocation is exact for any catalog size; ties use category order.
    remainder_order = sorted(categories, key=lambda c: -(total_pairs * config.category_weights[c] % total_weight))
    for category in remainder_order[:total_pairs - sum(counts.values())]:
        counts[category] += 1
    labels = [c for c in categories for _ in range(counts[c])]
    rng.shuffle(labels)
    quotes = {}
    # Explicit and saved quotes define the initial market, not permanent prices.
    overrides = {(q.supplier_id, q.product_id): q for q in config.supplier_quotes} if epoch == 0 else {}
    for supplier in config.suppliers:
        for p in products:
            category = labels.pop()
            variation = int(rng.integers(config.cost_variation_min_ppm, config.cost_variation_max_ppm + 1))
            minimum = max(1, (p.reference_price_cents * config.category_cost_percent[category] * variation + 50000000) // 100000000)
            listed = (minimum * config.listed_price_percent + 99) // 100
            override = overrides.get((supplier.id, p.id))
            if override:
                category, minimum, listed = override.category, override.minimum_cents, override.listed_cents
            q = Quote(supplier.id, p.id, category, minimum, listed, supplier.kind)
            quotes[q.supplier_id, p.id] = q
    return quotes

def negotiate(quote, price):
    if quote.minimum <= price <= quote.listed:
        return {"outcome": "accepted"}
    if quote.kind == "impatient":
        return {"outcome": "no_reply"}
    return {"outcome": "counteroffer", "unit_price_cents": min(quote.listed, max(quote.minimum, price))}
