def score(engine):
    inventory = sum(l.quantity * l.unit_cost_cents for lots in engine.storage.values() for l in lots)
    inventory += sum(l.quantity * l.unit_cost_cents for s in engine.slots.values() for l in s.lots)
    gross = engine.cash + engine.machine_cash + inventory
    net = gross - engine.debt
    return dict(cash_cents=engine.cash, machine_cash_cents=engine.machine_cash,
                inventory_value_cents=inventory, gross_assets_cents=gross,
                fee_debt_cents=engine.debt, score_cents=net,
                net_profit_cents=net - engine.config.starting_cash_cents)
