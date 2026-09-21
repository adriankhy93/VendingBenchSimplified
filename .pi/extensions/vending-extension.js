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
  let canContinue = false, progress = 0, lastProgress = 0, idleTurns = 0;
  const restore = (_event, ctx) => {
    canContinue = false; progress = 0; lastProgress = 0; idleTurns = 0;
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
  pi.on('agent_start', () => { canContinue = false; });
  pi.on('agent_end', event => {
    const last = [...event.messages].reverse().find(message => message.role === 'assistant');
    // Respect manual cancellation and provider failures; Pi owns its error retries.
    canContinue = last?.stopReason === 'stop' || last?.stopReason === 'length';
  });
  pi.on('agent_settled', (_event, ctx) => {
    if (!canContinue || !client) return;
    canContinue = false;
    const view = client.controller.view();
    if (['done', 'halted'].includes(view.phase) || !view.permitted_actions.length) return;
    if (progress !== lastProgress) { idleTurns = 0; lastProgress = progress; }
    if (idleTurns >= 3) {
      idleTurns = 0;
      ctx.ui?.notify('Vending paused: the model made no API progress after three continuation prompts.', 'warning');
      return;
    }
    idleTurns++;
    pi.sendUserMessage(
      `The vending environment still needs action. Invoke the vending tool now; do not print JSON as text. Choose a permitted action and continue until done or halted. Controller: ${JSON.stringify(view)}`,
      {deliverAs: 'followUp'},
    );
  });
  pi.on('tool_call', event => {
    if (event.toolName !== 'vending') return {block: true, reason: 'Use only the structured vending tool.'};
  });
  pi.registerTool({
    name: 'vending', label: 'Vending controller',
    description: 'Operate the vending environment. Follow controller.permitted_actions; quantities are maxima. One public API request per call. Begin with create and an empty payload.',
    parameters: Type.Object({action: Type.Union(actions.map(action => Type.Literal(action))), payload}, {additionalProperties: false}),
    async execute(_id, params, signal) {
      const result = await client.execute(params.action, params.payload, signal);
      if (result.response) progress++;
      return {content: [{type: 'text', text: JSON.stringify(result)}], details: result};
    },
  });
}
