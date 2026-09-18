import {readFileSync} from 'node:fs';
import {Type} from '@earendil-works/pi-ai';
import {VendingClient} from '../lib/vending-client.mjs';

const actions = ['create','observe','status','result','delete','get_machine','get_inventory',
  'collect_cash','search_products','set_price','make_offer','stock_items','end_day'];
const integer = Type.Integer({minimum: 1});
const payload = Type.Object({
  product_id: Type.Optional(Type.String()), supplier_id: Type.Optional(Type.String()),
  slot_id: Type.Optional(Type.String()), quantity: Type.Optional(integer),
  unit_price_cents: Type.Optional(integer),
}, {additionalProperties: false});

export default function (pi) {
  const skill = readFileSync(new URL('../skills/vending-machine/SKILL.md', import.meta.url), 'utf8');
  let client;
  const restore = (_event, ctx) => {
    let saved, legacyEnvironment;
    for (const entry of ctx.sessionManager.getBranch()) {
      if (entry.type === 'custom' && entry.customType === 'vending-controller-v1') saved = entry.data;
      if (entry.type === 'message' && entry.message?.role === 'toolResult') {
        try {
          const output = JSON.parse((entry.message.content || []).map(part => part.text || '').join(''));
          if (/^env_[a-f0-9]+$/.test(output.env_id || '')) legacyEnvironment = output.env_id;
        } catch { /* Non-API output is not controller state. */ }
      }
    }
    client = new VendingClient({baseUrl: process.env.VENDING_API_URL || 'http://127.0.0.1:8000', saved,
      persist: state => pi.appendEntry('vending-controller-v1', state)});
    if (saved) client.controller.resume();
    else if (legacyEnvironment) {
      client.controller.state.envId = legacyEnvironment;
      client.controller.state.phase = 'halted';
      client.controller.state.haltReason = 'This legacy session has no controller checkpoint. Start a new Pi session instead of creating a replacement inside this trace.';
    }
    pi.setActiveTools(['vending']);
  };
  pi.on('session_start', restore);
  pi.on('session_switch', restore);
  pi.on('session_tree', restore);
  pi.on('before_agent_start', event => ({systemPrompt: `${event.systemPrompt}\n\n${skill}`}));
  pi.on('tool_call', event => {
    if (event.toolName !== 'vending') return {block: true, reason: 'Use only the structured vending tool.'};
  });
  pi.registerTool({
    name: 'vending', label: 'Vending controller',
    description: 'Operate the vending environment. Follow controller.permitted_actions; quantities are maxima. One public API request per call. Begin with create and an empty payload.',
    parameters: Type.Object({action: Type.Union(actions.map(action => Type.Literal(action))), payload}, {additionalProperties: false}),
    async execute(_id, params, signal) {
      const result = await client.execute(params.action, params.payload, signal);
      return {content: [{type: 'text', text: JSON.stringify(result)}], details: result};
    },
  });
}
