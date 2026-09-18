/** Deterministic controller using only public API observations. */
export const POLICY = Object.freeze({
  assortmentSize: 4, historyDays: 3, machineDays: 1.5, reserveDays: 1,
  feeReserveDays: 3, initialMarkup: 1.5, priceStep: 0.1,
  negotiationDiscount: 0.9, offersPerPairPerDay: 2, selloutsToExpand: 2,
});
const copy = value => structuredClone(value);
const sum = values => values.reduce((a, b) => a + b, 0);
const qty = lots => sum((lots || []).map(lot => lot.quantity));
const candidate = (action, payload = {}) => ({action, payload});

export function initialState() {
  return {
    version: 1, envId: null, phase: 'create', lifecycle: 'running', day: 1,
    clock: null, rules: {}, products: [], quotes: [], prices: {}, slots: [], storage: {},
    balances: {}, selected: {}, history: {}, offers: {}, trial: null,
    refreshQuotes: false, lastMarket: 0, pending: null, terminal: null,
    slotLots: {}, uncertain: false,
  };
}

export class Controller {
  constructor(saved) { this.state = saved ? copy(saved) : initialState(); }
  snapshot() { return copy(this.state); }
  resume() {
    const s = this.state;
    if (s.phase === 'done') return;
    if (s.pending) { s.phase = s.pending.action === 'create' || s.pending.attempts >= 2 ? 'halted' : 'retry'; return; }
    if (s.envId) s.phase = 'resume_status';
  }
  product(pid) { return this.state.products.find(p => p.product_id === pid); }
  machineQuantity(pid) {
    return sum(this.state.slots.filter(slot => slot.product_id === pid).map(slot => slot.quantity));
  }
  storageQuantity(pid) { return this.state.storage[pid]?.quantity || 0; }
  freeCash() {
    const {balances: b, rules: r} = this.state;
    return Math.max(0, (b.cash_cents || 0) - (b.fee_debt_cents || 0) - POLICY.feeReserveDays * (r.daily_fee_cents || 0));
  }
  target(pid) {
    const s = this.state, selection = s.selected[pid];
    const rows = (s.history[pid] || []).filter(row => row.price === s.prices[pid]).slice(-POLICY.historyDays);
    const capacity = sum(selection.slots.map(id => s.slots.find(slot => slot.slot_id === id)?.capacity || 0));
    let machine = s.rules.slot_capacity || 0, reserve = 0;
    if (rows.length >= POLICY.historyDays) {
      const mean = sum(rows.map(row => row.quantity)) / rows.length;
      machine = Math.ceil(POLICY.machineDays * mean);
      reserve = Math.ceil(POLICY.reserveDays * mean);
    }
    machine = Math.min(capacity, machine + (selection.boost || 0));
    return {machine, reserve, shortage: Math.max(0, machine + reserve - this.machineQuantity(pid) - this.storageQuantity(pid))};
  }
  initialPrice(pid) {
    const p = this.product(pid);
    const quotes = this.state.quotes.filter(q => q.product_id === pid);
    if (!p || !quotes.length) return null;
    const cheapest = Math.min(...quotes.map(q => q.unit_price_cents));
    const price = Math.max(p.min_price_cents, Math.ceil(p.reference_price_cents * POLICY.initialMarkup), cheapest + 1);
    return price <= p.max_price_cents ? price : null;
  }
  offerCandidates(pid) {
    const s = this.state, target = this.target(pid), price = s.prices[pid];
    if (!target.shortage || s.refreshQuotes) return [];
    return s.quotes.filter(q => q.product_id === pid).flatMap(q => {
      const key = `${s.day}:${q.supplier_id}:${pid}`, attempt = s.offers[key];
      if ((attempt?.count || 0) >= POLICY.offersPerPairPerDay || attempt?.accepted) return [];
      const cost = attempt ? attempt.nextPrice : Math.max(1, Math.floor(q.unit_price_cents * POLICY.negotiationDiscount));
      if (!Number.isInteger(cost) || cost >= price) return [];
      const quantity = Math.min(target.shortage, s.rules.quantity_cap || 1000, Math.floor(this.freeCash() / cost));
      return quantity > 0 ? [candidate('make_offer', {supplier_id: q.supplier_id, product_id: pid, quantity, unit_price_cents: cost})] : [];
    }).sort((a, b) => a.payload.unit_price_cents - b.payload.unit_price_cents || a.payload.supplier_id.localeCompare(b.payload.supplier_id));
  }
  stockCandidates(pid) {
    const s = this.state, target = this.target(pid);
    const deficit = Math.max(0, target.machine - this.machineQuantity(pid));
    return s.selected[pid].slots.flatMap(id => {
      const slot = s.slots.find(slot => slot.slot_id === id);
      if (!slot || (slot.product_id && slot.product_id !== pid)) return [];
      const quantity = Math.min(slot.capacity - slot.quantity, this.storageQuantity(pid), deficit, s.rules.quantity_cap || 1000);
      return quantity > 0 ? [candidate('stock_items', {slot_id: id, product_id: pid, quantity})] : [];
    });
  }
  priceCandidates() {
    const s = this.state;
    if (s.trial?.revert) return [candidate('set_price', {product_id: s.trial.pid, unit_price_cents: s.trial.oldPrice})];
    if (s.trial) return [];
    return Object.keys(s.selected).flatMap(pid => {
      const rows = (s.history[pid] || []).filter(r => r.price === s.prices[pid] && r.comparable).slice(-POLICY.historyDays);
      if (rows.length < POLICY.historyDays) return [];
      const p = this.product(pid), current = s.prices[pid];
      const lots = [...(s.storage[pid]?.lots || []), ...s.selected[pid].slots.flatMap(id => s.slotLots[id] || [])];
      if (lots.some(lot => lot.unit_cost_cents == null)) return [];
      const cost = Math.max(0, ...lots.map(lot => lot.unit_cost_cents));
      return [...new Set([Math.ceil(current * (1 - POLICY.priceStep)), Math.floor(current * (1 + POLICY.priceStep))])]
        .filter(price => price !== current && price >= p.min_price_cents && price <= p.max_price_cents && price > cost)
        .map(price => candidate('set_price', {product_id: pid, unit_price_cents: price}));
    });
  }
  allowed() {
    const s = this.state;
    const forced = {create: 'create', observe: 'observe', resume_status: 'status',
      resume_observe: 'observe', collect: 'collect_cash', machine: 'get_machine',
      inventory: 'get_inventory', quotes: 'search_products', terminal: 'result', delete: 'delete'};
    if (s.phase === 'retry') return s.pending ? [candidate(s.pending.action, s.pending.payload)] : [];
    if (forced[s.phase]) return [candidate(forced[s.phase])];
    if (!['initial', 'review', 'replenish'].includes(s.phase)) return [];
    if (s.trial?.revert) return this.priceCandidates();
    let choices = [];
    if (s.phase === 'initial' && Object.keys(s.selected).length < POLICY.assortmentSize) {
      const allocated = Object.values(s.selected).flatMap(x => x.slots);
      if (s.slots.some(slot => !slot.quantity && !allocated.includes(slot.slot_id))) {
        choices.push(...s.products.filter(p => !s.selected[p.product_id]).flatMap(p => {
          const price = this.initialPrice(p.product_id);
          const cheapest = Math.min(...s.quotes.filter(q => q.product_id === p.product_id).map(q => Math.max(1, Math.floor(q.unit_price_cents * POLICY.negotiationDiscount))));
          return price !== null && cheapest <= this.freeCash() ? [candidate('set_price', {product_id: p.product_id, unit_price_cents: price})] : [];
        }));
      }
    }
    if (s.phase === 'review') choices.push(...this.priceCandidates());
    const work = Object.keys(s.selected).flatMap(pid => [...this.stockCandidates(pid), ...this.offerCandidates(pid)]);
    choices.push(...work);
    // Selection and price experiments are optional; affordable replenishment is not.
    if (!work.length && (Object.keys(s.selected).length || !choices.length)) choices.push(candidate('end_day'));
    return choices;
  }
  validate(action, payload) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('Payload must be an object.');
    const allowed = this.allowed();
    const match = allowed.find(c => c.action === action && Object.keys(payload).length === Object.keys(c.payload).length && Object.entries(c.payload).every(([key, value]) =>
      key === 'quantity' ? Number.isInteger(payload[key]) && payload[key] > 0 && payload[key] <= value : payload[key] === value));
    if (!match) throw new Error('Action is outside the current phase or its quantity/price limits. Use permitted_actions.');
  }
  view() {
    const s = this.state;
    return {phase: s.phase, env_id: s.envId, day: s.day, balances: s.balances,
      ...(s.haltReason ? {message: s.haltReason} : {}),
      inventory: Object.keys(s.selected).map(pid => ({product_id: pid, storage: this.storageQuantity(pid), machine: this.machineQuantity(pid), ...this.target(pid)})),
      permitted_actions: this.allowed(), quantity_note: s.phase === 'retry' ? 'Retry the exact pending payload, including quantity.' : 'Listed quantities are maxima; choose a positive integer up to that value.'};
  }
  transfer(source, target, quantity) {
    let cost = 0, remaining = quantity;
    while (remaining > 0 && source.length) {
      const lot = source[0], moved = Math.min(remaining, lot.quantity);
      target.push({...lot, quantity: moved});
      cost = cost === null || lot.unit_cost_cents == null ? null : cost + moved * lot.unit_cost_cents;
      lot.quantity -= moved; remaining -= moved;
      if (!lot.quantity) source.shift();
    }
    return remaining ? null : cost;
  }
  settle(event) {
    const s = this.state;
    for (const pid of Object.keys(s.selected)) {
      const available = this.machineQuantity(pid), sold = event.sales?.[pid] || 0;
      let remaining = sold, cost = 0;
      for (const slot of s.slots) {
        if (slot.product_id !== pid) continue;
        const take = Math.min(slot.quantity, remaining);
        const movedCost = this.transfer(s.slotLots[slot.slot_id] || [], [], take);
        cost = cost === null || movedCost === null ? null : cost + movedCost;
        slot.quantity -= take; remaining -= take;
        if (!slot.quantity) slot.product_id = null;
      }
      const selection = s.selected[pid], sellout = available > 0 && sold >= available;
      const comparable = available >= this.target(pid).machine && available > 0 && !sellout && cost !== null;
      const row = {day: event.day, price: s.prices[pid], quantity: sold, comparable, profit: cost === null ? null : sold * s.prices[pid] - cost};
      (s.history[pid] ||= []).push(row);
      s.history[pid] = s.history[pid].slice(-30);
      selection.sellouts = sellout ? (selection.sellouts || 0) + 1 : 0;
      if (selection.sellouts >= POLICY.selloutsToExpand) {
        const used = Object.values(s.selected).flatMap(x => x.slots);
        const slot = s.slots.find(slot => !slot.quantity && !used.includes(slot.slot_id));
        if (slot) { selection.slots.push(slot.slot_id); selection.boost = (selection.boost || 0) + slot.capacity; }
        selection.sellouts = 0;
      }
      if (s.trial?.pid === pid && !s.trial.revert && comparable) {
        s.trial.profits.push(row.profit);
        if (s.trial.profits.length >= POLICY.historyDays) {
          const improved = sum(s.trial.profits) / s.trial.profits.length > s.trial.baseline;
          if (improved) { s.trial = null; s.history[pid] = []; }
          else s.trial.revert = true;
        }
      }
    }
  }
  apply(action, payload, response, status = 200) {
    const s = this.state, r = response || {}, result = r.result || {};
    if (action === 'create') {
      if (status < 300 && /^env_[a-f0-9]+$/.test(r.env_id)) { s.envId = r.env_id; s.phase = 'observe'; }
      else s.phase = 'halted';
      return;
    }
    if (action === 'result' && status < 300) { s.terminal = r; s.phase = 'delete'; return; }
    if (action === 'delete' && (status < 300 || status === 404)) { s.phase = 'done'; return; }
    if (r.state === 'ended' || r.state === 'unavailable' || status === 410 || ['environment_ended','environment_unavailable'].includes(r.error?.code)) {
      s.lifecycle = r.state || (r.error?.code === 'environment_unavailable' ? 'unavailable' : 'ended');
      s.phase = 'terminal';
      // An accepted final business action still updates public inventory and sales.
      if (!r.action_id) return;
    } else if (status >= 400) {
      if (status === 404) s.phase = 'halted';
      return;
    }
    if (action === 'status') { if (r.state === 'running') s.phase = 'resume_observe'; return; }
    const wasResume = s.phase === 'resume_observe';
    const pid = payload.product_id;
    if (r.metrics) s.balances = copy(r.metrics);
    if (result.rules) s.rules = copy(result.rules);
    if (result.products) s.products = copy(result.products);
    if (result.quotes) { s.quotes = copy(result.quotes); s.refreshQuotes = false; }
    if (action === 'set_price' && result.unit_price_cents === payload.unit_price_cents) {
      if (!s.selected[pid]) {
        const used = Object.values(s.selected).flatMap(x => x.slots);
        const slot = s.slots.find(slot => !slot.quantity && !used.includes(slot.slot_id));
        s.selected[pid] = {slots: [slot.slot_id], boost: 0, sellouts: 0};
      } else if (s.trial?.revert && s.trial.pid === pid) {
        s.trial = null; s.history[pid] = [];
      } else {
        const rows = (s.history[pid] || []).filter(row => row.comparable && row.price === s.prices[pid]).slice(-POLICY.historyDays);
        s.trial = {pid, oldPrice: s.prices[pid], baseline: sum(rows.map(row => row.profit)) / rows.length, profits: [], revert: false};
      }
      s.prices[pid] = payload.unit_price_cents;
    }
    if (action === 'make_offer') {
      const key = `${s.day}:${payload.supplier_id}:${pid}`, old = s.offers[key];
      const quote = s.quotes.find(q => q.product_id === pid && q.supplier_id === payload.supplier_id);
      s.offers[key] = {count: (old?.count || 0) + 1, accepted: result.outcome === 'accepted',
        nextPrice: result.outcome === 'counteroffer' ? result.unit_price_cents : result.outcome === 'no_reply' ? quote?.unit_price_cents : null};
      if (result.outcome === 'accepted') {
        const item = s.storage[pid] ||= {quantity: 0, lots: []};
        item.quantity += payload.quantity;
        item.lots.push({quantity: payload.quantity, unit_cost_cents: payload.unit_price_cents, purchase_id: result.purchase_id});
      }
    }
    if (action === 'stock_items' && result.moved_quantity > 0) {
      const slot = s.slots.find(slot => slot.slot_id === payload.slot_id), item = s.storage[pid];
      this.transfer(item.lots, s.slotLots[slot.slot_id] ||= [], result.moved_quantity);
      item.quantity -= result.moved_quantity;
      slot.product_id = pid; slot.quantity += result.moved_quantity;
    }
    if (['make_offer','stock_items'].includes(action) && s.phase === 'review') s.phase = 'replenish';
    if (result.outcome === 'rejected' && action === 'stock_items') s.phase = 'machine';
    // Settle before applying end-of-action snapshots, which already include sales.
    for (const event of r.events || []) if (event.type === 'day') this.settle(event);
    if (result.slots) {
      if (wasResume) {
        for (const slot of result.slots) {
          if (qty(s.slotLots[slot.slot_id]) !== slot.quantity) {
            s.slotLots[slot.slot_id] = slot.quantity ? [{quantity: slot.quantity, unit_cost_cents: null}] : [];
            if (slot.product_id) s.history[slot.product_id] = [];
          }
        }
      }
      s.slots = copy(result.slots); s.prices = copy(result.prices || s.prices);
    }
    if (result.storage) s.storage = copy(result.storage);
    if (r.sim_time) {
      const newDay = r.sim_time.day, changedDay = newDay > s.day;
      s.clock = copy(r.sim_time); s.day = newDay;
      const market = Math.floor((newDay - 1) / (s.rules.supplier_reshuffle_days || 30));
      if (market > s.lastMarket || (r.events || []).some(e => e.type === 'supplier_reshuffle')) {
        s.lastMarket = market; s.refreshQuotes = true; s.history = {}; s.trial = null;
        for (const selection of Object.values(s.selected)) selection.sellouts = 0;
      }
      if (changedDay) {
        s.offers = {};
        s.phase = (s.balances.machine_cash_cents || 0) > 0 ? 'collect' : 'machine';
      } else if (action === 'observe') s.phase = wasResume ? (s.refreshQuotes ? 'quotes' : 'review') : 'initial';
      else if (action === 'collect_cash') s.phase = 'machine';
      else if (action === 'get_machine') s.phase = 'inventory';
      else if (action === 'get_inventory') s.phase = s.refreshQuotes ? 'quotes' : 'review';
      else if (action === 'search_products') s.phase = 'review';
    }
    if (s.lifecycle !== 'running') s.phase = 'terminal';
  }
}
