"""Policies use public observations only; no engine or evaluator state access."""
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

@dataclass
class Decision:
    calls: list[dict]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None

class ModelAdapter(Protocol):
    def decide(self, messages, tools, max_output_tokens: int, timeout: float) -> Decision: ...

class Idle:
    def choose(self, latest):
        return 'end_day', {}

class Baseline:
    """Refresh public inventory daily, refill to capacity, and collect before buying."""
    def __init__(self, negotiate=False):
        self.negotiate = negotiate
        self.queue = deque([('search_products', {})])
        self.terms = {}
        self.waiting_offer = None
        self.initialized = False
        self.selected = []

    def choose(self, latest):
        result = latest.get('result', {})
        if self.waiting_offer:
            offer = self.waiting_offer
            self.waiting_offer = None
            if result.get('outcome') == 'counteroffer':
                self.terms[offer['product_id']]['price'] = result['unit_price_cents']
            elif result.get('outcome') == 'no_reply':
                self.terms[offer['product_id']]['price'] = self.terms[offer['product_id']]['listed']
            if result.get('outcome') in ('counteroffer', 'no_reply'):
                self.queue.appendleft(('make_offer', offer | {'unit_price_cents': self.terms[offer['product_id']]['price']}))
        if not self.initialized and result.get('quotes') and self.queue == deque():
            products = {p['product_id']: p for p in result['products']}
            for pid, product in products.items():
                q = min((q for q in result['quotes'] if q['product_id'] == pid), key=lambda q: q['unit_price_cents'])
                retail = min(product['max_price_cents'], max(product['min_price_cents'], product['reference_price_cents'] * 3 // 2))
                self.terms[pid] = dict(supplier_id=q['supplier_id'], price=1 if self.negotiate else q['unit_price_cents'], listed=q['unit_price_cents'], retail=retail)
            # Relative public margins, tie broken by product ID. Diversify across ten products.
            self.selected = sorted(products, key=lambda p: (self.terms[p]['listed'] / products[p]['reference_price_cents'], p))
            self.initialized = True
            self.queue.extend([('collect_cash', {}), ('observe', {})])
        elif self.initialized and 'storage' in result and 'slots' in result and not self.queue:
            cash = result['cash_cents']
            for index, slot in enumerate(result['slots']):
                pid = self.selected[index % len(self.selected)]
                terms = self.terms[pid]
                needed = slot['capacity'] - slot['quantity']
                if needed <= 0:
                    continue
                stored = result['storage'][pid]['quantity']
                buy = max(0, needed - stored)
                # Preserve a day's fee and reserve listed cost until negotiation is known.
                reserve_price = terms['listed'] if terms['price'] == 1 else terms['price']
                buy = min(buy, result['rules']['quantity_cap'], max(0, cash - result['rules']['daily_fee_cents']) // reserve_price)
                cash -= buy * reserve_price
                stock = min(needed, stored + buy, result['rules']['quantity_cap'])
                result['storage'][pid]['quantity'] = max(0, stored - stock)
                if buy:
                    self.queue.append(('make_offer', dict(supplier_id=terms['supplier_id'], product_id=pid,
                                                         quantity=buy, unit_price_cents=terms['price'])))
                if stock:
                    self.queue.append(('set_price', dict(product_id=pid, unit_price_cents=terms['retail'])))
                    self.queue.append(('stock_items', dict(slot_id=slot['slot_id'], product_id=pid, quantity=stock)))
            self.queue.extend([('end_day', {}), ('collect_cash', {}), ('observe', {})])
        if not self.queue:
            self.queue.append(('observe', {}))
        action, payload = self.queue.popleft()
        if action == 'make_offer':
            self.waiting_offer = payload
        return action, payload
