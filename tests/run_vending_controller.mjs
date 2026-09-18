import {writeFileSync} from 'node:fs';
import {VendingClient} from '../.pi/lib/vending-client.mjs';
const [url,mode,path]=process.argv.slice(2);
const client=new VendingClient({baseUrl:url});
const messages=[]; let calls=0, refreshes=0, lastResult;
async function call(action,payload={}) {
  const id=`call-${++calls}`;
  messages.push({type:'message',message:{role:'assistant',content:[{type:'toolCall',id,name:'vending',arguments:{action,payload}}]}});
  const result=await client.execute(action,payload);
  messages.push({type:'message',message:{role:'toolResult',toolCallId:id,content:[{type:'text',text:JSON.stringify(result)}]}});
  if(result.blocked || result.transport_error) throw new Error(JSON.stringify(result));
  if(result.http_status>=400 && result.http_status!==410) throw new Error(JSON.stringify(result));
  if(result.response?.result?.outcome==='rejected') throw new Error(JSON.stringify(result));
  if(action==='search_products') refreshes++;
  if(action==='result') lastResult=result.response;
}
await call('create'); await call('observe');
if(mode==='deadline') await new Promise(resolve=>setTimeout(resolve,1200));
while(client.controller.state.phase!=='done' && calls<2500) {
  const choices=client.controller.allowed();
  if(!choices.length) throw new Error('Controller deadlock: '+JSON.stringify(client.controller.view()));
  const selected=choices[0];
  await call(selected.action,selected.payload);
}
if(client.controller.state.phase!=='done') throw new Error('Controller did not terminate');
writeFileSync(path,messages.map(m=>JSON.stringify(m)).join('\n')+'\n');
console.log(JSON.stringify({calls,refreshes,day:client.controller.state.day,result:lastResult}));
