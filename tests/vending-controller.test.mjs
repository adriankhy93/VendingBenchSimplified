import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {Controller, POLICY} from '../.pi/lib/vending-controller.mjs';
import {VendingClient} from '../.pi/lib/vending-client.mjs';

const clock = (day=1, minute_of_day=5) => ({day, minute_of_day});
const balances = {cash_cents: 50000, machine_cash_cents: 0, fee_debt_cents: 0};
const response = (result={}, extra={}) => ({action_id:'act_0001',state:'running',sim_time:clock(),metrics:balances,result,events:[],...extra});
function initialized() {
  const c = new Controller();
  c.apply('create', {}, {env_id:'env_abc'});
  c.apply('observe', {}, response({
    products:['p01','p04','p08'].map(product_id => ({product_id,reference_price_cents:100,min_price_cents:25,max_price_cents:500})),
    quotes:['p01','p04','p08'].map(product_id => ({supplier_id:'s01',product_id,unit_price_cents:100})),
    rules:{slot_capacity:10,quantity_cap:1000,daily_fee_cents:200,supplier_reshuffle_days:30},
    slots:['r1s1','r2s2','r2s3','r3s1'].map(slot_id => ({slot_id,product_id:null,quantity:0,capacity:10})),
    storage:{},prices:{},
  }));
  return c;
}
function selected() {
  const c = initialized();
  c.apply('set_price',{product_id:'p01',unit_price_cents:150},response({product_id:'p01',unit_price_cents:150}));
  return c;
}
function stock(c, quantity=10) {
  const s = c.state;
  s.storage.p01 = {quantity, lots:[{quantity,unit_cost_cents:80}]};
  c.apply('stock_items',{product_id:'p01',slot_id:'r1s1',quantity},response({moved_quantity:quantity}));
}
const has = (c, action) => c.allowed().some(x => x.action === action);

test('lifecycle uses actual IDs, rejects out-of-phase/invalid payloads locally', () => {
  const c = new Controller();
  assert.throws(() => c.validate('stock_items', {quantity:1}));
  c.validate('create',{});
  c.apply('create', {}, {env_id:'env_a123'});
  assert.equal(c.state.envId,'env_a123');
  assert.deepEqual(c.allowed(),[{action:'observe',payload:{}}]);
  const d = selected();
  assert.throws(() => d.validate('stock_items',{product_id:'p01',slot_id:'r1s1',quantity:1}));
  for (const quantity of [0,-1,1.5,true,11]) assert.throws(() => d.validate('make_offer',{product_id:'p01',supplier_id:'s01',quantity,unit_price_cents:90}));
  assert.throws(() => d.validate('make_offer',{product_id:'p01',supplier_id:'s01',quantity:1,unit_price_cents:90,extra:1}));
});

test('replenishment subtracts storage and machine, preserves debt and fee reserve', () => {
  const c = selected();
  assert.equal(c.target('p01').shortage,10);
  c.state.storage.p01 = {quantity:10,lots:[{quantity:10,unit_cost_cents:80}]};
  assert.equal(c.target('p01').shortage,0);
  assert.equal(has(c,'make_offer'),false);
  assert.equal(has(c,'stock_items'),true);
  c.state.storage.p01.quantity=0;
  c.state.balances={...balances,cash_cents:1000,fee_debt_cents:200};
  assert.equal(c.offerCandidates('p01')[0].payload.quantity,2);
  c.state.balances.cash_cents=800;
  assert.equal(has(c,'make_offer'),false);
  assert.equal(has(c,'end_day'),true);
});

test('negotiation permits only discounted first offer and one counter/listed fallback', () => {
  const c=selected(), payload={supplier_id:'s01',product_id:'p01',quantity:10,unit_price_cents:90};
  c.validate('make_offer',payload);
  c.apply('make_offer',payload,response({outcome:'counteroffer',unit_price_cents:95}));
  assert.equal(c.offerCandidates('p01')[0].payload.unit_price_cents,95);
  assert.throws(() => c.validate('make_offer',payload));
  c.apply('make_offer',{...payload,unit_price_cents:95},response({outcome:'accepted',purchase_id:'buy1'}));
  assert.equal(c.storageQuantity('p01'),10);
  assert.equal(c.offerCandidates('p01').length,0);
  const d=selected();
  d.apply('make_offer',payload,response({outcome:'no_reply'}));
  assert.equal(d.offerCandidates('p01')[0].payload.unit_price_cents,100);
  d.apply('make_offer',{...payload,unit_price_cents:100},response({outcome:'no_reply'}));
  assert.equal(d.offerCandidates('p01').length,0);
});

test('trace-derived slot refusals and orange-juice overbuy are blocked', () => {
  const fixture=JSON.parse(readFileSync(new URL('./fixtures/pi-controller-regressions.json',import.meta.url)));
  for(const row of fixture.stock_refusals) {
    const c=initialized(), s=c.state;
    s.phase='replenish'; s.prices[row.product_id]=150;
    s.selected[row.product_id]={slots:[row.slot_id],boost:0};
    Object.assign(s.slots.find(x=>x.slot_id===row.slot_id),{quantity:row.actual_quantity,product_id:row.product_id});
    s.storage[row.product_id]={quantity:20,lots:[{quantity:20,unit_cost_cents:80}]};
    assert.throws(()=>c.validate('stock_items',{slot_id:row.slot_id,product_id:row.product_id,quantity:row.quantity}));
  }
  const c=initialized(), s=c.state, row=fixture.orange_juice;
  s.phase='replenish'; s.day=row.day; s.prices.p04=350;
  s.selected.p04={slots:['r1s1','r2s2','r2s3'],boost:0};
  for(const slot of s.slots.slice(0,3)) Object.assign(slot,{product_id:'p04',quantity:10});
  s.storage.p04={quantity:3,lots:[{quantity:3,unit_cost_cents:247}]};
  s.history.p04=row.recent_sales.map(quantity=>({quantity,price:350}));
  assert.equal(c.target('p04').shortage,0);
  assert.throws(()=>c.validate('make_offer',{supplier_id:'s08',product_id:'p04',quantity:20,unit_price_cents:247}));
});

test('rejected stocking changes no stock and requires fresh snapshots', () => {
  const c=selected(); c.state.storage.p01={quantity:10,lots:[{quantity:10,unit_cost_cents:80}]};
  c.apply('stock_items',{product_id:'p01',slot_id:'r1s1',quantity:10},response({outcome:'rejected',reason:'slot_full'}));
  assert.equal(c.storageQuantity('p01'),10); assert.equal(c.machineQuantity('p01'),0);
  assert.deepEqual(c.allowed(),[{action:'get_machine',payload:{}}]);
});

test('every midnight triggers cash, machine, inventory and quote refresh in order', () => {
  const c=selected(); stock(c);
  c.apply('end_day',{},response({}, {sim_time:clock(31,0),metrics:{...balances,machine_cash_cents:300},events:[{type:'day',day:30,sales:{p01:2}},{type:'supplier_reshuffle',day:31}]}));
  assert.equal(c.state.phase,'collect'); assert.equal(c.state.refreshQuotes,true); assert.deepEqual(c.state.history,{});
  c.apply('collect_cash',{},response({transferred_cents:300},{sim_time:clock(31,5)}));
  assert.equal(c.state.phase,'machine');
  c.apply('get_machine',{},response({slots:c.state.slots,prices:c.state.prices},{sim_time:clock(31,10)}));
  assert.equal(c.state.phase,'inventory');
  c.apply('get_inventory',{},response({storage:c.state.storage},{sim_time:clock(31,15)}));
  assert.equal(c.state.phase,'quotes'); assert.equal(has(c,'make_offer'),false);
  c.apply('search_products',{},response({quotes:c.state.quotes},{sim_time:clock(31,40)}));
  assert.equal(c.state.phase,'review');
  c.apply('get_inventory',{},response({storage:{}},{sim_time:clock(32,0),events:[{type:'day',day:31,sales:{}}]}));
  assert.equal(c.state.phase,'machine');
});

test('two sellouts allocate one slot, non-sellout days cannot', () => {
  const c=selected(); stock(c);
  c.settle({day:1,sales:{p01:10}});
  assert.equal(c.state.selected.p01.slots.length,1);
  stock(c); c.settle({day:2,sales:{p01:10}});
  assert.equal(c.state.selected.p01.slots.length,2);
  assert.equal(c.state.selected.p01.boost,10);
});

test('pricing requires three comparable days, one trial, and reverts unprofitable trial', () => {
  const c=selected(); stock(c); c.state.phase='review';
  c.state.history.p01=[1,2].map(day=>({day,price:150,quantity:2,profit:140,comparable:true}));
  assert.equal(c.priceCandidates().length,0);
  c.state.history.p01.push({day:3,price:150,quantity:2,profit:140,comparable:true});
  const change={product_id:'p01',unit_price_cents:165};
  c.validate('set_price',change); c.apply('set_price',change,response(change));
  assert.equal(c.priceCandidates().length,0);
  for(let day=4;day<=6;day++) { if(day>4) stock(c,1); c.settle({day,sales:{p01:1}}); }
  assert.equal(c.state.trial.revert,true);
  assert.deepEqual(c.allowed(),[{action:'set_price',payload:{product_id:'p01',unit_price_cents:150}}]);
  c.apply('set_price',{product_id:'p01',unit_price_cents:150},response({product_id:'p01',unit_price_cents:150}));
  assert.equal(c.state.trial,null); assert.deepEqual(c.state.history.p01,[]);
});

test('sellouts do not count as comparable price evidence', () => {
  const c=selected(); stock(c);
  c.state.trial={pid:'p01',oldPrice:140,baseline:0,profits:[],revert:false};
  c.settle({day:1,sales:{p01:10}});
  assert.equal(c.state.trial.profits.length,0);
});

test('resume checks status and reconciles snapshot; terminal result precedes delete', () => {
  const c=selected(); stock(c);
  const resumed=new Controller(c.snapshot()); resumed.resume();
  assert.equal(resumed.state.phase,'resume_status');
  resumed.apply('status',{}, {state:'running'});
  assert.equal(resumed.state.phase,'resume_observe');
  resumed.apply('observe',{}, response({slots:c.state.slots,prices:c.state.prices,storage:c.state.storage}));
  assert.equal(resumed.state.phase,'review');
  resumed.apply('end_day',{}, {error:{code:'environment_ended'}},410);
  assert.equal(resumed.state.phase,'terminal'); assert.throws(()=>resumed.validate('delete',{}));
  resumed.apply('result',{}, {state:'ended',score:{score_cents:55000}});
  assert.equal(resumed.state.terminal.score.score_cents,55000);
  resumed.validate('delete',{}); resumed.apply('delete',{}, {},204);
  assert.equal(resumed.state.phase,'done'); assert.throws(()=>resumed.validate('create',{}));
});

test('transport uncertainty retries once on a later call with the same key', async () => {
  let calls=0; const keys=[], snapshots=[];
  const saved=selected().snapshot();
  const client=new VendingClient({baseUrl:'http://localhost',saved,persist:s=>snapshots.push(s),fetchImpl:async (_url, opts)=>{
    calls++; keys.push(opts.headers['Idempotency-Key']);
    if(calls===1) throw new Error('network lost');
    return {status:200,json:async()=>response({outcome:'accepted',purchase_id:'buy1'})};
  }});
  const payload={supplier_id:'s01',product_id:'p01',quantity:10,unit_price_cents:90};
  const first=await client.execute('make_offer',payload);
  assert.equal(first.controller.phase,'retry'); assert.equal(calls,1);
  assert.equal(snapshots[0].pending.attempts,1);
  const altered=await client.execute('make_offer',{...payload,quantity:1});
  assert.equal(altered.blocked,true); assert.equal(calls,1);
  const second=await client.execute('make_offer',{unit_price_cents:90,quantity:10,product_id:'p01',supplier_id:'s01'});
  assert.equal(calls,2); assert.equal(keys[0],keys[1]); assert.equal(second.controller.phase,'initial');
  assert.equal(client.controller.storageQuantity('p01'),10);
});

test('failed create is not retried; two uncertain business requests halt', async () => {
  let calls=0;
  const fetchImpl=async()=>{calls++; throw new Error('network');};
  const create=new VendingClient({baseUrl:'http://localhost',fetchImpl});
  await create.execute('create',{}); assert.equal(create.controller.state.phase,'halted');
  create.controller.resume(); await create.execute('create',{}); assert.equal(calls,1);
  const client=new VendingClient({baseUrl:'http://localhost',saved:selected().snapshot(),fetchImpl});
  const payload=client.controller.offerCandidates('p01')[0].payload;
  await client.execute('make_offer',payload); await client.execute('make_offer',payload);
  assert.equal(client.controller.state.phase,'halted');
  client.controller.resume(); assert.equal(client.controller.state.phase,'halted');
});

test('requests are serialized and second call uses updated state', async () => {
  let calls=0;
  const client=new VendingClient({baseUrl:'http://localhost',fetchImpl:async()=>{calls++; await new Promise(resolve=>setTimeout(resolve,5)); return {status:201,json:async()=>({env_id:'env_abc'})};}});
  const [a,b]=await Promise.all([client.execute('create',{}),client.execute('create',{})]);
  assert.equal(a.response.env_id,'env_abc'); assert.equal(b.blocked,true); assert.equal(calls,1);
});

test('improved trial is retained after three comparable days, then needs new evidence', () => {
  const c=selected(); stock(c);
  c.state.trial={pid:'p01',oldPrice:140,baseline:100,profits:[],revert:false};
  for(let day=1;day<=3;day++) {
    if(day>1) stock(c,2);
    c.settle({day,sales:{p01:2}});
  }
  assert.equal(c.state.trial,null); assert.equal(c.state.prices.p01,150);
  assert.deepEqual(c.state.history.p01,[]);
});

test('recovery with changed machine quantities invalidates unknown cost evidence', () => {
  const c=selected(); stock(c);
  c.state.history.p01=[{price:150,quantity:2,profit:140,comparable:true}];
  c.resume(); c.apply('status',{}, {state:'running'});
  const slots=structuredClone(c.state.slots); slots[0].quantity=8;
  c.apply('observe',{},response({slots,prices:c.state.prices,storage:c.state.storage}));
  assert.deepEqual(c.state.history.p01,[]);
  c.settle({day:1,sales:{p01:2}});
  assert.equal(c.state.history.p01[0].profit,null);
  assert.equal(c.state.history.p01[0].comparable,false);
});

test('in-flight request is restored with its saved key and original phase', async () => {
  const c=selected(), payload=c.offerCandidates('p01')[0].payload;
  c.state.pending={action:'make_offer',payload,key:'stable-key',attempts:1,phase:'initial'};
  let key;
  const client=new VendingClient({baseUrl:'http://localhost',saved:c.snapshot(),fetchImpl:async(_url,opts)=>{
    key=opts.headers['Idempotency-Key'];
    return {status:200,json:async()=>response({outcome:'accepted',purchase_id:'buy1'})};
  }});
  client.controller.resume();
  const result=await client.execute('make_offer',payload);
  assert.equal(key,'stable-key'); assert.equal(result.controller.phase,'initial');
  assert.equal(client.controller.storageQuantity('p01'),10);
});

test('unaffordable startup permits settlement rather than deadlocking', () => {
  const c=initialized(); c.state.balances.cash_cents=100;
  assert.deepEqual(c.allowed(),[{action:'end_day',payload:{}}]);
});
