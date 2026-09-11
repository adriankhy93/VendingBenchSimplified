"""PCG64 streams keyed by seed/product/absolute tick; no action-dependent RNG."""
import numpy as np

def expected_daily(product, price, day_multiplier):
    return product.base_demand * (product.reference_price_cents / price) ** product.elasticity * day_multiplier

def sample(seed, product_index, absolute_tick, mean):
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, 2, product_index, absolute_tick])))
    return int(rng.poisson(mean))
