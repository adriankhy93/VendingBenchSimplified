"""Public operational guidance supplied with native tool schemas."""
TOOL_DESCRIPTIONS = {
    'observe': 'Get a full current public snapshot: inventory, slots, prices, balances, catalog, quotes and rules. Large response; prefer targeted inspection when possible.',
    'search_products': 'Discover products and supplier quotes. Supply product_id to restrict the response and reduce context. Quotes are asking prices, not guaranteed profitable costs.',
    'make_offer': 'Offer to buy quantity units from a supplier. Only accepted purchases deduct cash and deliver immediately to storage. Counteroffers and no_reply do not deliver stock; adjust your next offer using the result.',
    'get_inventory': 'Inspect current storage inventory before buying or stocking. Earlier inventory snapshots may be stale.',
    'get_balance': 'Inspect spendable cash, machine cash and fee debt. Reserve cash for daily fees and purchases.',
    'get_machine': 'Inspect valid slot IDs, capacity and current contents. Sales reduce slot stock as simulated time advances.',
    'set_price': 'Set the retail price for a product within its public price bounds. Required BEFORE stock_items, even when stock has already been purchased. Resolves price_required refusals.',
    'stock_items': 'Move purchased units from storage to a compatible machine slot. First set_price for the product; ensure sufficient stored units and free slot capacity. On price_required call set_price, not stock_items again.',
    'unstock_items': 'Move quantity units from a machine slot back to storage to free capacity or change the assortment.',
    'collect_cash': 'Transfer accumulated machine cash into spendable cash for purchases and daily fees.',
    'wait': 'Advance simulated time by the configured wait duration, allowing stocked products to sell. Thinking alone does not advance simulation.',
    'end_day': 'Advance to the next day boundary, generating sales and assessing daily fees. Use after stocking to evaluate sales; inspect and replenish as needed.',
}
