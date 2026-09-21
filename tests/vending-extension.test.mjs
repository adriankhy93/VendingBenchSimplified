import test from 'node:test';
import assert from 'node:assert/strict';
import {loadExtensions, createExtensionRuntime} from '../.tools/pi/node_modules/@earendil-works/pi-coding-agent/dist/core/extensions/loader.js';

test('installed Pi loads tool, injects skill, disables shell, and restores session', async () => {
  const runtime=createExtensionRuntime();
  let active=[]; const entries=[];
  runtime.setActiveTools=tools=>{active=tools;};
  runtime.appendEntry=(customType,data)=>entries.push({type:'custom',customType,data});
  const {extensions,errors}=await loadExtensions([process.cwd()+'/.pi/extensions/vending-extension.js'],process.cwd(),undefined,runtime);
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

test('automatic continuation follows normal completion but respects aborts, errors, and stalls', async () => {
  const runtime=createExtensionRuntime(), messages=[], notices=[];
  runtime.setActiveTools=()=>{}; runtime.appendEntry=()=>{};
  runtime.sendUserMessage=(text,options)=>messages.push({text,options});
  const {extensions,errors}=await loadExtensions([process.cwd()+'/.pi/extensions/vending-extension.js'],process.cwd(),undefined,runtime);
  assert.deepEqual(errors,[]);
  const extension=extensions[0], ctx={sessionManager:{getBranch:()=>[]},ui:{notify:text=>notices.push(text)}};
  for(const handler of extension.handlers.get('session_start')) await handler({},ctx);
  const end=extension.handlers.get('agent_end')[0], settled=extension.handlers.get('agent_settled')[0];
  for(const stopReason of ['aborted','error']) {
    await end({messages:[{role:'assistant',stopReason}]},ctx); await settled({},ctx);
  }
  assert.equal(messages.length,0);
  for(let i=0;i<4;i++) {
    await end({messages:[{role:'assistant',stopReason:'stop'}]},ctx); await settled({},ctx);
    await settled({},ctx); // Repeated settled notification must not enqueue twice.
  }
  assert.equal(messages.length,3); assert.equal(notices.length,1);
  assert.equal(messages[0].options.deliverAs,'followUp');
  assert.ok(messages[0].text.includes('Invoke the vending tool'));
  for(const phase of ['done','halted']) {
    const state={version:1,phase,envId:null,selected:{},balances:{}};
    const terminalCtx={...ctx,sessionManager:{getBranch:()=>[{type:'custom',customType:'vending-controller-v1',data:state}]}};
    for(const handler of extension.handlers.get('session_start')) await handler({},terminalCtx);
    await end({messages:[{role:'assistant',stopReason:'stop'}]},terminalCtx); await settled({},terminalCtx);
  }
  assert.equal(messages.length,3);
});

test('actual launcher flags leave vending active in a real Pi session', async () => {
  const {mkdtempSync,writeFileSync,rmSync}=await import('node:fs');
  const {tmpdir}=await import('node:os');
  const {join}=await import('node:path');
  const {execFileSync}=await import('node:child_process');
  const {parseArgs}=await import('../.tools/pi/node_modules/@earendil-works/pi-coding-agent/dist/cli/args.js');
  const {createAgentSession}=await import('../.tools/pi/node_modules/@earendil-works/pi-coding-agent/dist/core/sdk.js');
  const {DefaultResourceLoader}=await import('../.tools/pi/node_modules/@earendil-works/pi-coding-agent/dist/core/resource-loader.js');
  const {SessionManager}=await import('../.tools/pi/node_modules/@earendil-works/pi-coding-agent/dist/core/session-manager.js');
  const directory=mkdtempSync(join(tmpdir(),'vending-launcher-'));
  let session;
  try {
    const executable=join(directory,'capture-pi');
    writeFileSync(executable,'#!/bin/sh\nprintf "%s\\n" "$@"\n',{mode:0o755});
    const args=execFileSync('bash',['scripts/run_pi_agent.sh'],{encoding:'utf8',env:{...process.env,PI_BIN:executable}}).trimEnd().split('\n');
    const parsed=parseArgs(args);
    const loader=new DefaultResourceLoader({cwd:directory,agentDir:directory,
      noExtensions:true,noSkills:true,noPromptTemplates:true,noContextFiles:true,
      additionalExtensionPaths:[process.cwd()+'/.pi/extensions/vending-extension.js']});
    await loader.reload();
    ({session}=await createAgentSession({cwd:directory,agentDir:directory,resourceLoader:loader,
      sessionManager:SessionManager.inMemory(directory),tools:parsed.tools,
      noTools:parsed.noTools?'all':parsed.noBuiltinTools?'builtin':undefined,
      model:{id:'test',name:'test',provider:'test',api:'openai-completions',baseUrl:'http://localhost',
        reasoning:false,input:['text'],contextWindow:10000,maxTokens:1000,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}}));
    assert.deepEqual(session.getActiveToolNames(),['vending']);
  } finally {session?.dispose(); rmSync(directory,{recursive:true,force:true});}
});
