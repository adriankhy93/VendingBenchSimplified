'use strict';
const $ = id => document.getElementById(id);
const state = {
    id: null,
    data: null,
    runOffset: 0,
    actionOffset: 0,
    listSeq: 0,
    detailSeq: 0,
    actionSeq: 0
};
const money = value => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD'
}).format(value / 100) : '—';
const number = value => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 1
}).format(value) : '—';
const words = value => String(value ?? 'Unknown').replaceAll('_', ' ');
const timeLabel = minute => `Day ${Math.floor(minute/1440)+1} · ${String(Math.floor(minute%1440/60)).padStart(2,'0')}:${String(minute%60).padStart(2,'0')}`;
const seconds = value => typeof value === 'number' ? `${number(value)} s` : '—';
const node = (tag, className = '', text = null) => {
    const e = document.createElement(tag);
    e.className = className;
    if (text !== null) e.textContent = text;
    return e;
};
const svgNode = (tag, attrs = {}) => {
    const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
    return e;
};

function badge(status) {
    return node('span', `badge ${['completed','failed','budget_truncated','unfinished'].includes(status)?status:''}`, words(status));
}

function empty(target, text) {
    target.replaceChildren(node('p', 'empty-message', text));
}
async function api(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(response.status === 404 ? 'This run is no longer available.' : `Could not read run data (HTTP ${response.status}).`);
    return response.json();
}

function error(message) {
    $('error').textContent = message;
    $('error').hidden = !message;
}

function rows(target, entries) {
    const wrap = node('div', 'data-rows');
    for (const [label, value] of entries) {
        const row = node('div', 'data-row');
        row.append(node('span', 'muted', label), node('span', 'data-value', value));
        wrap.append(row);
    }
    target.replaceChildren(wrap);
}

function bars(target, entries, secondary = false) {
    if (!entries.length) return empty(target, 'No recorded activity yet.');
    const wrap = node('div', 'bars');
    const max = Math.max(1, ...entries.map(e => e[1]));
    for (const [label, value] of entries) {
        const row = node('div', 'bar-item');
        const title = node('span', 'bar-label', label);
        title.title = label;
        const track = node('div', 'bar-track');
        const svg = svgNode('svg', {
            viewBox: '0 0 100 7',
            preserveAspectRatio: 'none',
            'aria-hidden': 'true'
        });
        svg.append(svgNode('rect', {
            width: Math.max(0, value / max * 100),
            height: 7,
            rx: 3,
            class: `bar-fill${secondary?' secondary':''}`
        }));
        track.append(svg);
        row.append(title, track, node('span', 'bar-value', number(value)));
        wrap.append(row);
    }
    target.replaceChildren(wrap);
}

function table(headers) {
    const t = node('table');
    const head = node('thead'),
        tr = node('tr');
    headers.forEach(h => tr.append(node('th', '', h)));
    head.append(tr);
    t.append(head);
    const body = node('tbody');
    t.append(body);
    return [t, body];
}

function metric(label, value, note, extra = '') {
    const card = node('div', 'metric');
    card.append(node('div', 'metric-label', label), node('div', `metric-value ${extra}`, value), node('div', 'metric-note', note));
    return card;
}

async function loadRuns(selectFirst = false) {
    const seq = ++state.listSeq;
    try {
        const params = new URLSearchParams({
            q: $('search').value,
            classification: $('status-filter').value,
            offset: state.runOffset,
            limit: 30
        });
        const data = await api(`/api/runs?${params}`);
        if (seq !== state.listSeq) return;
        $('run-count').textContent = data.total;
        $('runs-page').textContent = data.total ? `${data.offset+1}–${Math.min(data.offset+30,data.total)} of ${data.total}` : '0 runs';
        $('runs-prev').disabled = state.runOffset === 0;
        $('runs-next').disabled = state.runOffset + 30 >= data.total;
        const list = $('run-list');
        list.replaceChildren();
        for (const run of data.runs) {
            const button = node('button', `run${run.run_id===state.id?' selected':''}`);
            button.dataset.runId = run.run_id;
            button.setAttribute('aria-pressed', String(run.run_id === state.id));
            const top = node('div', 'run-top');
            top.append(node('span', '', words(run.agent)), node('span', '', money(run.score?.score_cents)));
            const bottom = node('div', 'run-bottom');
            bottom.append(badge(run.classification), node('span', '', `Seed ${run.seed??'—'} · ${run.run_id.slice(0,6)}`));
            button.append(top, node('div', 'run-env', run.environment), bottom);
            button.addEventListener('click', () => selectRun(run.run_id));
            list.append(button);
        }
        if (!data.runs.length) empty(list, $('search').value || $('status-filter').value ? 'No runs match these filters.' : 'No recorded runs yet.');
        if (selectFirst && !state.id && data.runs.length) await selectRun(data.runs[0].run_id);
        error('');
    } catch (exc) {
        error(exc.message);
    }
}
async function selectRun(id) {
    state.id = id;
    state.actionOffset = 0;
    state.data = null;
    history.replaceState(null, '', `#${encodeURIComponent(id)}`);
    $('action-filter').value = '';
    for (const e of document.querySelectorAll('.run')) {
        const active = e.dataset.runId === id;
        e.classList.toggle('selected', active);
        e.setAttribute('aria-pressed', String(active));
    }
    await loadDetail();
}
async function loadDetail() {
    if (!state.id) return;
    const seq = ++state.detailSeq;
    const id = state.id;
    try {
        const data = await api(`/api/runs/${encodeURIComponent(id)}`);
        if (seq !== state.detailSeq || id !== state.id) return;
        state.data = data;
        renderDetail(data);
        await loadActions();
        error('');
    } catch (exc) {
        if (seq !== state.detailSeq) return;
        $('run-detail').hidden = true;
        $('empty').hidden = false;
        error(exc.message);
    }
}

function renderDetail(d) {
    $('empty').hidden = true;
    $('run-detail').hidden = false;
    $('run-environment').textContent = d.environment;
    $('run-title').textContent = `${words(d.agent)} run`;
    $('run-meta').textContent = `${d.run_id} · Seed ${d.seed??'—'} · ${new Date(d.created_at).toLocaleString()}${d.model?` · ${d.model}`:''}`;
    const status = badge(d.classification);
    status.id = 'run-status';
    $('run-status').replaceWith(status);
    const notices = [...d.warnings, ...d.errors.map(e => `Run error: ${e}`)];
    if (d.classification === 'unfinished') notices.push('No final summary has been written. This run may be in progress or may have been interrupted.');
    $('warnings').textContent = notices.join(' ');
    $('warnings').hidden = !notices.length;
    $('score-note').textContent = d.score_source === 'pre_deletion' ? 'Score from the trusted pre-deletion snapshot. This run did not complete naturally.' : d.score_source === 'terminal' ? `Ended: ${words(d.reason)}.` : 'Final score unavailable; balances and sales below reflect recorded actions.';
    const score = d.score || {};
    const sold = d.sales.reduce((n, p) => n + p.quantity, 0);
    $('metrics').replaceChildren(metric('Final score', money(score.score_cents), 'Cash + inventory − debt'), metric('Net profit', money(score.net_profit_cents), 'Relative to starting cash', score.net_profit_cents > 0 ? 'positive' : score.net_profit_cents < 0 ? 'negative' : ''), metric('Units sold', number(sold), `${d.sales.length} products with sales`), metric('Simulated days', number((d.simulated_minutes ?? 0) / 1440), `${number(d.action_total)} recorded actions`));
    renderChart(d.timeline);
    rows($('score-breakdown'), [
        ['Spendable cash', money(score.cash_cents ?? d.last_balances?.cash_cents)],
        ['Machine cash', money(score.machine_cash_cents ?? d.last_balances?.machine_cash_cents)],
        ['Inventory at cost', money(score.inventory_value_cents)],
        ['Unpaid fee debt', money(score.fee_debt_cents ?? d.last_balances?.fee_debt_cents)],
        ['Final score', money(score.score_cents)]
    ]);
    const usage = d.usage || {};
    rows($('resource-use'), [
        ['Wall time', seconds(usage.wall_seconds)],
        ['Policy calls', number(usage.calls)],
        ['Input / output tokens', `${number(usage.input_tokens)} / ${number(usage.output_tokens)}`],
        ['Model cost', usage.cost_usd == null ? 'Not reported' : money(usage.cost_usd * 100)],
        ['Mean action latency', usage.action_latency_mean_seconds == null ? '—' : `${number(usage.action_latency_mean_seconds*1000)} ms`],
        ['Stop reason', words(d.reason)]
    ]);
    bars($('sales'), d.sales.sort((a, b) => b.quantity - a.quantity).map(p => [p.name, p.quantity]));
    bars($('action-mix'), Object.entries(d.action_counts).sort((a, b) => b[1] - a[1]).map(([a, n]) => [words(a), n]), true);
    renderMachine(d);
    renderDays(d.day_events);
    const selected = $('action-filter').value;
    $('action-filter').replaceChildren(new Option('All actions', ''), ...Object.keys(d.action_counts).sort().map(a => new Option(words(a), a)));
    $('action-filter').value = selected;
    $('config-json').textContent = JSON.stringify(d.config, null, 2);
    $('usage-json').textContent = d.usage_records.length ? JSON.stringify(d.usage_records, null, 2) : 'No model usage recorded. Scripted agents do not consume model tokens.';
    $('memory-text').textContent = d.memory || 'The agent did not write a notebook for this run.';
}

function renderChart(points) {
    const target = $('chart');
    $('chart-readout').textContent = 'Move across the chart to inspect balances.';
    if (!points.length) {
        empty(target, 'No balance observations recorded yet.');
        return;
    }
    const svg = svgNode('svg', {
        viewBox: '0 0 760 240',
        role: 'img',
        'aria-label': 'Spendable cash, machine cash, and fee debt over simulated time',
        tabindex: 0
    });
    const title = svgNode('title');
    title.textContent = 'Balances over simulated time. Use left and right arrow keys to inspect each point.';
    svg.append(title);
    const left = 64,
        right = 738,
        top = 18,
        bottom = 204;
    const maxTime = Math.max(1, points.at(-1).minute);
    const series = [
        ['cash_cents', 'cash'],
        ['machine_cash_cents', 'machine'],
        ['fee_debt_cents', 'debt']
    ];
    const max = Math.max(100, ...points.flatMap(p => series.map(([key]) => Number.isFinite(p[key]) ? p[key] : 0)));
    const x = p => left + p.minute / maxTime * (right - left),
        y = value => bottom - (Number.isFinite(value) ? value : 0) / max * (bottom - top);
    for (let i = 0; i <= 4; i++) {
        const level = max * i / 4;
        const yPos = y(level);
        svg.append(svgNode('line', {
            x1: left,
            y1: yPos,
            x2: right,
            y2: yPos,
            class: 'grid-line'
        }));
        const label = svgNode('text', {
            x: left - 10,
            y: yPos + 4,
            'text-anchor': 'end',
            class: 'axis-label'
        });
        label.textContent = money(level);
        svg.append(label);
    }
    for (let i = 0; i <= 4; i++) {
        const label = svgNode('text', {
            x: left + (right - left) * i / 4,
            y: 229,
            'text-anchor': 'middle',
            class: 'axis-label'
        });
        label.textContent = `${number(maxTime*i/4/1440)} d`;
        svg.append(label);
    }
    for (const [key, name] of series) {
        svg.append(svgNode('polyline', {
            points: points.map(p => `${x(p)},${y(p[key])}`).join(' '),
            class: `chart-line chart-${name}`
        }));
        if (points.length === 1) svg.append(svgNode('circle', {
            cx: x(points[0]),
            cy: y(points[0][key]),
            r: 3,
            class: `chart-line chart-${name}`
        }));
    }
    const cursor = svgNode('line', {
        x1: left,
        x2: left,
        y1: top,
        y2: bottom,
        class: 'chart-cursor',
        visibility: 'hidden'
    });
    svg.append(cursor);
    let active = 0;
    const inspect = index => {
        active = Math.max(0, Math.min(points.length - 1, index));
        const p = points[active];
        cursor.setAttribute('x1', x(p));
        cursor.setAttribute('x2', x(p));
        cursor.setAttribute('visibility', 'visible');
        $('chart-readout').textContent = `${timeLabel(p.minute)} · Spendable ${money(p.cash_cents)} · Machine ${money(p.machine_cash_cents)} · Debt ${money(p.fee_debt_cents)}`;
    };
    svg.addEventListener('pointermove', event => {
        const rect = svg.getBoundingClientRect();
        const minute = ((event.clientX - rect.left) / rect.width * 760 - left) / (right - left) * maxTime;
        let nearest = 0;
        for (let i = 1; i < points.length; i++)
            if (Math.abs(points[i].minute - minute) < Math.abs(points[nearest].minute - minute)) nearest = i;
        inspect(nearest);
    });
    svg.addEventListener('keydown', event => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault();
            inspect(active + (event.key === 'ArrowRight' ? 1 : -1));
        }
    });
    target.replaceChildren(svg);
}

function renderMachine(d) {
    const target = $('machine-grid');
    target.replaceChildren();
    if (!d.machine) {
        $('machine-time').textContent = '';
        return empty(target, 'No machine snapshot recorded.');
    }
    const clock = d.machine.sim_time;
    $('machine-time').textContent = `Last observed ${clock?timeLabel((clock.day-1)*1440+clock.minute_of_day):''}. Stock may have changed afterward.`;
    const names = d.product_names || Object.fromEntries(d.sales.map(p => [p.product_id, p.name]));
    for (const p of d.config.environment_definition?.scenario?.products ?? []) names[p.id] = p.name;
    for (const slot of d.machine.slots) {
        const card = node('div', 'slot');
        const label = node('div', 'slot-label');
        label.append(node('span', '', slot.slot_id), node('span', '', slot.product_id ? money(d.machine.prices[slot.product_id]) : '—'));
        card.append(label, node('div', 'slot-name', slot.product_id ? (names[slot.product_id] ?? slot.product_id) : 'Empty slot'), node('div', 'slot-quantity', `${slot.quantity} / ${slot.capacity} units`));
        target.append(card);
    }
}

function renderDays(days) {
    if (!days.length) return empty($('days'), 'No completed days recorded.');
    const [t, body] = table(['Day', 'Units sold', 'Fee paid', 'Cash', 'Debt', 'Missed fees']);
    for (const day of days) {
        const tr = node('tr');
        [day.day, number(Object.values(day.sales || {}).reduce((a, b) => a + b, 0)), money(day.fee_paid_cents), money(day.cash_cents), money(day.fee_debt_cents), day.failure_streak].forEach(value => tr.append(node('td', '', value)));
        body.append(tr);
    }
    $('days').replaceChildren(t);
}
async function loadActions() {
    if (!state.id) return;
    const id = state.id,
        seq = ++state.actionSeq;
    try {
        const params = new URLSearchParams({
            offset: state.actionOffset,
            limit: 50,
            action: $('action-filter').value
        });
        const data = await api(`/api/runs/${encodeURIComponent(id)}/actions?${params}`);
        if (seq !== state.actionSeq || id !== state.id) return;
        $('actions-prev').disabled = state.actionOffset === 0;
        $('actions-next').disabled = state.actionOffset + 50 >= data.total;
        $('actions-page').textContent = data.total ? `${state.actionOffset+1}–${Math.min(state.actionOffset+50,data.total)} of ${data.total}` : '0 actions';
        if (!data.actions.length) return empty($('action-table'), 'No matching actions recorded.');
        const [t, body] = table(['#', 'Simulated time', 'Action', 'Outcome', 'Spendable', 'Units sold']);
        for (const entry of data.actions) {
            const r = entry.response || {},
                result = r.result || {},
                clock = r.sim_time;
            const tr = node('tr');
            const button = node('button', 'action-toggle', `▸ ${words(entry.action)}`);
            button.setAttribute('aria-expanded', 'false');
            const actionCell = node('td');
            actionCell.append(button);
            tr.append(node('td', '', entry.index), node('td', '', clock ? timeLabel((clock.day - 1) * 1440 + clock.minute_of_day) : '—'), actionCell, node('td', '', words(r.error?.code || result.reason || result.outcome || r.state || 'Recorded')), node('td', '', money(r.metrics?.cash_cents)), node('td', '', number(r.metrics?.units_sold)));
            const detail = node('tr', 'action-detail');
            detail.hidden = true;
            const td = node('td');
            td.colSpan = 6;
            td.append(node('pre', '', JSON.stringify({
                request: {
                    action: entry.action,
                    payload: entry.payload
                },
                response: entry.response
            }, null, 2)));
            detail.append(td);
            button.addEventListener('click', () => {
                detail.hidden = !detail.hidden;
                button.setAttribute('aria-expanded', String(!detail.hidden));
                button.textContent = `${detail.hidden?'▸':'▾'} ${words(entry.action)}`;
            });
            body.append(tr, detail);
        }
        $('action-table').replaceChildren(t);
    } catch (exc) {
        if (id === state.id) error(exc.message);
    }
}
for (const tab of document.querySelectorAll('[data-tab]')) tab.addEventListener('click', () => {
    for (const button of document.querySelectorAll('[data-tab]')) {
        const active = button === tab;
        button.classList.toggle('active', active);
        if (active) button.setAttribute('aria-current', 'page');
        else button.removeAttribute('aria-current');
        $(button.dataset.tab).hidden = !active;
    }
});
$('refresh').addEventListener('click', async () => {
    await loadRuns(!state.id);
    if (state.id) await loadDetail();
});
let searchTimer;
$('search').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        state.runOffset = 0;
        loadRuns();
    }, 200);
});
$('status-filter').addEventListener('change', () => {
    state.runOffset = 0;
    loadRuns();
});
$('runs-prev').addEventListener('click', () => {
    state.runOffset = Math.max(0, state.runOffset - 30);
    loadRuns();
});
$('runs-next').addEventListener('click', () => {
    state.runOffset += 30;
    loadRuns();
});
$('action-filter').addEventListener('change', () => {
    state.actionOffset = 0;
    loadActions();
});
$('actions-prev').addEventListener('click', () => {
    state.actionOffset = Math.max(0, state.actionOffset - 50);
    loadActions();
});
$('actions-next').addEventListener('click', () => {
    state.actionOffset += 50;
    loadActions();
});
let refreshing = false;
setInterval(async () => {
    if (!$('auto-refresh').checked || document.hidden || refreshing) return;
    refreshing = true;
    try {
        await loadRuns(!state.id);
        if (state.id) await loadDetail();
    } finally {
        refreshing = false;
    }
}, 5000);
window.addEventListener('hashchange', () => {
    try {
        if (location.hash) selectRun(decodeURIComponent(location.hash.slice(1)));
    } catch {
        error('Invalid run link.');
    }
});
(async () => {
    try {
        if (location.hash) state.id = decodeURIComponent(location.hash.slice(1));
        await loadRuns(!state.id);
        if (state.id && !state.data) await loadDetail();
    } catch (exc) {
        error(exc.message);
    }
})();
