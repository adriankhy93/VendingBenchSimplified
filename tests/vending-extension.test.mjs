import test from 'node:test';
import assert from 'node:assert/strict';
import {loadExtensions, createExtensionRuntime} from '../.tools/pi/node_modules/@earendil-works/pi-coding-agent/dist/core/extensions/loader.js';

test('installed Pi loads tool, injects skill, disables shell, and restores session', async () => {
  const runtime=createExtensionRuntime();
  let active=[]; const entries=[];
  runtime.setActiveTools=tools=>{active=tools;};
  runtime.appendEntry=(customType,data)=>entries.push({type:'custom',customType,data});
  const {extensions,errors}=await loadExtensions([process.cwd()+'/.pi/extensions/vending-guard.js'],process.cwd(),undefined,runtime);
  assert.deepEqual(errors,[]);
  const extension=extensions[0], ctx={sessionManager:{getBranch:()=>entries}};
  for(const handler of extension.handlers.get('session_start')) await handler({},ctx);
  assert.deepEqual(active,['vending']);
  const prompt=await extension.handlers.get('before_agent_start')[0]({systemPrompt:'BASE'},ctx);
  assert.ok(prompt.systemPrompt.startsWith('BASE'));
  assert.ok(prompt.systemPrompt.includes('## Controller graph'));
  const blocked=await extension.handlers.get('tool_call')[0]({toolName:'bash'},ctx);
  assert.equal(blocked.block,true);
  const tool=extension.tools.get('vending').definition;
  assert.equal(tool.parameters.properties.payload.additionalProperties,false);
  const original=globalThis.fetch;
  // Restore again to construct a client using the mocked public API transport.
  globalThis.fetch=async()=>({status:201,json:async()=>({env_id:'env_abc'})});
  try {
    for(const handler of extension.handlers.get('session_start')) await handler({},ctx);
    const result=await tool.execute('call1',{action:'create',payload:{}});
    assert.equal(result.details.response.env_id,'env_abc');
    assert.equal(entries.at(-1).data.phase,'observe');
    for(const handler of extension.handlers.get('session_switch')) await handler({},ctx);
    const invalid=await tool.execute('call2',{action:'create',payload:{}});
    assert.equal(invalid.details.blocked,true);
    assert.equal(invalid.details.controller.phase,'resume_status');
    entries.splice(0, entries.length, {type:'message',message:{role:'toolResult',content:[{type:'text',text:JSON.stringify({env_id:'env_abc'})}]}});
    for(const handler of extension.handlers.get('session_switch')) await handler({},ctx);
    const legacy=await tool.execute('call3',{action:'create',payload:{}});
    assert.equal(legacy.details.blocked,true);
    assert.equal(legacy.details.controller.phase,'halted');
  } finally {globalThis.fetch=original;}
});
