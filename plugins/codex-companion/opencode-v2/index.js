import {spawn} from 'node:child_process';
import {isAbsolute} from 'node:path';
import {Plugin} from '@opencode/plugin';

const types=[
  'session.execution.started','session.step.started','session.execution.succeeded',
  'session.execution.failed','session.execution.interrupted','permission.asked','permission.replied',
];

export default Plugin.define({
  id:'inkhub.companion',
  setup(ctx){
    const {inbox,bridge,python='python3'}=ctx.options;
    if(typeof inbox!=='string'||!isAbsolute(inbox)||typeof bridge!=='string'||!isAbsolute(bridge))return;
    const controller=new AbortController();
    void (async()=>{
      for await(const event of ctx.event.subscribe({types,signal:controller.signal})){
        const sessionID=event.data?.sessionID;
        if(!sessionID||controller.signal.aborted)continue;
        await new Promise(resolve=>{
          const worker=spawn(python,[bridge,'--source','opencode','--inbox',inbox],{
            stdio:['pipe','ignore','ignore'],windowsHide:true,timeout:2000,
          });
          worker.once('error',resolve);
          worker.once('close',resolve);
          worker.stdin.on('error',()=>{});
          worker.stdin.end(JSON.stringify({type:event.type,data:{sessionID}}));
        });
      }
    })().catch(()=>{});
    return ()=>controller.abort();
  },
});
