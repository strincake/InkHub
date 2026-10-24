import {mountPlugins} from '/plugins.js';
const $=s=>document.querySelector(s);
const systemTheme=matchMedia('(prefers-color-scheme: dark)');
let appearance='system';try{const saved=localStorage.getItem('screen-scheduler-appearance');if(['system','light','dark'].includes(saved))appearance=saved}catch{}
function applyAppearance(){const resolved=appearance==='system'?(systemTheme.matches?'dark':'light'):appearance;document.documentElement.dataset.theme=resolved;document.documentElement.style.colorScheme=resolved;$('#appearance-mode').value=appearance;window.schedulerControls?.refresh();dispatchEvent(new CustomEvent('scheduler-theme',{detail:{mode:appearance,resolved}}));}
$('#appearance-mode').onchange=()=>{appearance=$('#appearance-mode').value;try{localStorage.setItem('screen-scheduler-appearance',appearance)}catch{}applyAppearance()};systemTheme.addEventListener('change',applyAppearance);applyAppearance();

let state=null, token='', selectedView='overview', refreshing=false, toastTimer;
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4500)}
async function command(op,id='',data={}){const r=await fetch('/control/command',{method:'POST',headers:{'content-type':'application/json','x-control-token':token},body:JSON.stringify({op,id,data})});if(!r.ok)throw Error(await r.text());const result=await r.json();await refresh();return result}
function action(f){return async e=>{try{await f(e)}catch(err){toast(err.message)}}}
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const seconds=n=>n===0?'不限时':`${Math.round(n/1000)} 秒`;
const field=(form,name)=>form.elements.namedItem(name);
const quit=document.createElement('button');quit.textContent='退出墨枢';quit.className='text-button';quit.onclick=action(async()=>{await command('stop');toast('调度已停止，设备连接正在释放。可以关闭此页面。')});$('.side-bottom').append(quit);
function source(id){return state.sources.find(s=>s.config.id===id)}
function external(id){return state.external?.find(s=>s.id===id)??(state.plugins?.some(p=>p.source===id||Object.values(p.channels??{}).includes(id))?{transport:'plugin',receipts:[]}:undefined)}
const transportName={sdk:'原版 SDK · 托管接入',http:'HTTP 来源',test:'测试来源',plugin:'本地插件'};
async function refresh(){if(refreshing)return;refreshing=true;try{const r=await fetch('/control/state');if(!r.ok)throw Error('无法读取调度状态');state=await r.json();token=state.token;render()}catch(e){$('#connection').textContent='管理服务未连接';}finally{refreshing=false}}
let lastScreen='', lastCards='';
function render(){
  const app=state.application??{};
  const auto=$('#autostart-enabled');auto.disabled=!app.autostart_supported;$('#save-application').disabled=!app.autostart_supported;
  if(document.activeElement!==auto)auto.checked=app.autostart??false;
  $('#autostart-hint').textContent=app.autostart_supported?'登录 Windows 后驻留托盘，不自动弹出网页。':'安装版可设置随 Windows 启动。';
  pluginUI.render(state);
  document.body.dataset.view=selectedView;
  const dev=state.device,current=source(state.current?.frame.id);
  $('#sdk-address').textContent=state.access.sdk;$('#http-address').textContent='http://'+state.access.http;
  const queue=state.queue;$('#queue-count').textContent=queue.rows.length;$('#queue-status').textContent=queue.blocked?'发送暂停':queue.paused?'自动切换已暂停':queue.sending?'正在发送':'每秒更新';
  const roles={sending:'正在发送',current:'当前显示',updating:'新画面待更新',next:'下一候选',waiting:'等待显示',fallback:'保留待回落',empty:'等待画面'};
  $('#queue-list').innerHTML=queue.rows.length?queue.rows.map((row,n)=>{const boost=source(row.id)?.config.boost,boosted=boost&&(boost.until===null||boost.until>state.now);return `<div class="queue-row"><span class="queue-number">${String(n+1).padStart(2,'0')}</span><div class="queue-name"><strong>${escape(row.name)}</strong><small>${transportName[row.transport]} · 最新第 ${row.revision} 次${row.sending_revision!==null?' / 发送第 '+row.sending_revision+' 次':row.shown_revision!==null?' / 屏幕第 '+row.shown_revision+' 次':''}</small></div><span class="priority ${boosted?'boost':''}">P${row.priority}${boosted?' ↑':''}</span><span class="queue-role ${row.role}">${roles[row.role]}</span><span class="queue-reason">${escape(row.reason)}</span><span class="queue-time">${row.revision===0?'尚未开始':row.ttl_remaining_ms===null?'一直有效':Math.ceil(row.ttl_remaining_ms/1000)+' 秒后到期'}</span><button type="button" class="queue-boost" data-boost-id="${escape(row.id)}" aria-label="${escape(row.name)}：${boosted?'调整临时优先':'临时优先'}">${boosted?'调整优先':'临时优先'}</button></div>`}).join(''):'<div class="empty-queue">没有正在参与显示的来源。接入一个程序，或启用一个生图插件。</div>';
  $('#connection').textContent=dev.mode==='simulation'?'● 模拟运行':dev.connected?'● NOTE4 已连接':'○ NOTE4 未连接';
  $('#mode-badge').textContent=dev.mode==='simulation'?'模拟屏幕':'真实设备';
  if(document.activeElement!==$('#mode'))$('#mode').value=dev.mode;
  if(document.activeElement!==$('#target'))$('#target').value=dev.target;
  $('#device-health').textContent=dev.health+(dev.reconnect_until?` · 自动重连剩余 ${Math.max(0,Math.ceil((dev.reconnect_until-state.now)/1000))} 秒`:'');$('#preempt').checked=state.preempt;
  $('#connect').textContent=dev.connecting?'正在连接…':dev.connected?'设备已连接':'连接设备';
  $('#connect').disabled=dev.connected||dev.connecting||dev.sending;$('#disconnect').disabled=(!dev.connected&&!dev.reconnect_until)||dev.sending;
  for(const [id,key] of [['reconnect-enabled','enabled'],['reconnect-window','window_seconds'],['reconnect-interval','interval_seconds']]){const el=$('#'+id);if(document.activeElement!==el){if(key==='enabled')el.checked=dev.reconnect?.[key]??false;else el.value=dev.reconnect?.[key]??(key==='window_seconds'?120:5);}}
  $('#retry').hidden=!dev.blocked;$('#pause').textContent=state.paused?'恢复自动切换':'暂停切换';
  $('#current-name').textContent=current?.config.name??'等待内容';
  $('#current-detail').textContent=dev.sending?'正在换图，按键暂不转交':current?`${transportName[external(current.config.id)?.transport??'test']} · ${current.config.format==='mono'?'黑白':current.config.format==='gray4'?'四级灰阶':'十六级灰阶'} · ${state.paused?'已暂停自动切换':state.current.yielded?'已让出，暂时保留画面':'已显示 '+Math.floor((state.now-state.current.shown_at)/1000)+' 秒'}`:'没有有效来源时，保留屏幕最后画面';
  const screenKey=`${state.current?.frame.id}:${state.current?.frame.revision}:${state.current?.shown_at}`;
  if(screenKey!==lastScreen){lastScreen=screenKey;const img=$('#screen');img.src='/control/screen.png?v='+encodeURIComponent(screenKey);img.onload=()=>{img.hidden=false;$('#empty-screen').hidden=true};img.onerror=()=>{img.hidden=true;$('#empty-screen').hidden=false};}
  const danger=state.sources.some(({config:s})=>s.enabled&&s.hold_ms===0&&s.ttl_ms===0);
  $('#global-warning').hidden=state.preempt||!danger;$('#global-warning').textContent='有来源设置为一直有效且持续显示。关闭提前切入后，其他来源可能一直等待；仍允许保存此设置。';
  $('#source-count').textContent=state.sources.length;
  const cards=state.sources.map(s=>{const c=s.config,isCurrent=current?.config.id===c.id,boost=c.boost&&(c.boost.until===null||c.boost.until>state.now),ext=external(c.id),channelOwner=state.plugins?.find(p=>Object.values(p.channels??{}).includes(c.id)),owner=channelOwner??state.plugins?.find(p=>p.source===c.id),receipt=ext?.receipts?.at(-1);
    const keys=s.keys??[],last=keys.at(-1);
    const resultLabels={accepted:'已接收，等待显示',displaying:'正在发送',displayed:'实机报告已显示',simulated:'仅模拟显示',superseded:'已被新状态替换',failed:'发送失败',result_unknown:'实机结果未知',expired:'任务已到期'};
    return `<article class="source-card ${isCurrent?'current':''}" data-id="${c.id}"><div class="card-top"><span class="source-symbol">◴</span><div class="card-name"><strong>${escape(c.name)}</strong><small>${escape(owner?'来源插件：'+owner.manifest.name:ext?'来源程序：'+(ext.name??c.name):'测试来源')}</small></div><span class="priority ${boost?'boost':''}">P${s.effective}${boost?' ↑':''}</span></div><div class="source-thumb">${c.revision?`<img src="/control/image/${c.id}?v=${c.revision}" alt="${escape(c.name)}的最新画面">`:'等待第一张画面'}</div><div class="source-reason">${escape(s.reason)}${boost?` · 临时优先${c.boost.until===null?'':`剩 ${Math.max(1,Math.ceil((c.boost.until-state.now)/60000))} 分钟`}`:''}${receipt?`<small class="receipt-state">${resultLabels[receipt.state]??escape(receipt.state)}</small>`:''}</div><div class="card-actions">${ext?'':`<button data-action="test">更新画面</button>`}<button data-action="settings">设置</button><div class="source-quick"><label class="field">显示优先级<select data-source-setting="priority" aria-label="${escape(c.name)}：显示优先级">${[1,2,3,4,5].map(p=>`<option value="${p}" ${p===c.priority?'selected':''}>${p} · ${['最高','较高','普通','较低','最低'][p-1]}</option>`).join('')}</select></label><label class="field">设备显示效果<select data-source-setting="format" aria-label="${escape(c.name)}：设备显示效果">${[['mono','黑白'],['gray4','四级灰阶'],['gray16','十六级灰阶']].map(([v,label])=>`<option value="${v}" ${v===c.format?'selected':''}>${label}</option>`).join('')}</select></label><label class="check-row source-enabled"><input type="checkbox" data-source-setting="enabled" ${c.enabled?'checked':''}>启用</label></div>${channelOwner?`<button data-action="manage-channel">管理来源</button>`:''}</div><details class="source-details"><summary>显示规则</summary><div class="card-extra"><span>${c.persistent?'可返回最后画面':'不回放旧状态'}</span><span>${last?'最近按键 '+escape(last.key):'至少显示 '+seconds(c.min_ms)}</span></div></details></article>`}).join('');
  if(cards!==lastCards&&!$('#source-list .select-menu:popover-open')){$('#source-list').innerHTML=cards||'<div class="empty-sources">还没有内容通道。前往插件与接入启用插件，或在“插件与接入”的外接程序管理中接入程序。</div>';lastCards=cards;}
  window.schedulerControls?.refresh();
  $('#logs-list').innerHTML=state.logs.length?state.logs.map(l=>`<div class="log-row"><time>+${Math.floor(l.at/1000)} 秒</time><span>${escape(l.message)}</span></div>`).join(''):'<p class="hint">发生换图或按键操作后，记录会出现在这里。</p>';
}
function view(name){
  const home=pluginUI.activate(name);selectedView=name;document.body.dataset.view=name;
  document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===name));
  for(const page of ['overview','sources','logs','plugins'])$('#'+page+'-view').hidden=!!home||name!==page;
  const titles={overview:'屏幕总览',sources:'内容通道',logs:'切换记录',plugins:'插件与接入'};
  $('#view-label').textContent=titles[name]??home?.manifest.navigation_title??home?.manifest.name;
  $('#page-title').textContent=titles[name]??home?.manifest.name;
  $('#page-description').textContent=home?(home.manifest.description??''):({overview:'查看当前画面和接下来的显示次序。',sources:'管理来源的显示规则与优先级。',logs:'查看画面切换、设备结果与按键去向。',plugins:'管理本地插件与外接程序，让内容有序接入。'}[name]??'');
}

const pluginUI=mountPlugins({getState:()=>state,refresh,onView:view,toast,editSource:edit,command});
$('#copy-api-key').onclick=action(async()=>{await navigator.clipboard.writeText(state.access.api_key);toast('接入密钥已复制')});
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>view(b.dataset.view));
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$('#'+b.dataset.close).close());
function edit(id=''){const f=$('#source-form');f.reset();field(f,'id').value=id;$('#editor-title').textContent=id?'来源设置':'添加内容通道';if(id){const c=source(id).config;for(const key of ['name'])field(f,key).value=c[key];for(const key of ['persistent'])field(f,key).value=String(c[key]);for(const key of ['bypass'])field(f,key).checked=c[key];for(const [input,key] of [['min','min_ms'],['hold','hold_ms'],['ttl','ttl_ms']])field(f,input).value=c[key]/1000;}$('#editor').showModal()}

$('#source-form').onsubmit=action(async e=>{e.preventDefault();const f=e.currentTarget,id=field(f,'id').value;const data={name:field(f,'name').value,min_ms:+field(f,'min').value*1000,hold_ms:+field(f,'hold').value*1000,ttl_ms:+field(f,'ttl').value*1000,persistent:field(f,'persistent').value==='true',bypass:field(f,'bypass').checked};await command(id?'settings':'add',id,data);$('#editor').close();toast('来源设置已保存；发送新画面即可参与显示')});
$('#queue-list').onclick=action(async e=>{const b=e.target.closest('[data-boost-id]');if(!b)return;const id=b.dataset.boostId,c=source(id)?.config;if(!c)return;const f=$('#boost-form');f.reset();field(f,'id').value=id;$('#boost-source-name').textContent=c.name;const boost=c.boost;if(boost&&(boost.until===null||boost.until>state.now)){field(f,'priority').value=boost.priority;field(f,'kind').value=boost.until_replaced?'replaced':boost.until===null?'forever':'minutes';if(boost.until!==null)field(f,'minutes').value=Math.max(1,Math.ceil((boost.until-state.now)/60000));}$('#boost-editor').showModal()});
$('#boost-form').onsubmit=action(async e=>{e.preventDefault();const f=e.currentTarget;await command('boost',field(f,'id').value,{priority:+field(f,'priority').value,duration_ms:field(f,'kind').value==='minutes'?+field(f,'minutes').value*60000:0,until_replaced:field(f,'kind').value==='replaced'});$('#boost-editor').close()});
$('#clear-boost').onclick=action(async()=>{await command('boost',field($('#boost-form'),'id').value,{clear:true});$('#boost-editor').close()});
$('#source-list').onchange=action(async e=>{const input=e.target.closest('[data-source-setting]');if(!input)return;const id=input.closest('[data-id]').dataset.id,key=input.dataset.sourceSetting,value=key==='enabled'?input.checked:key==='priority'?Number(input.value):input.value;input.disabled=true;try{await command('settings',id,{[key]:value});toast('显示设置已生效')}catch(error){lastCards='';render();throw error}finally{input.disabled=false}});
$('#source-list').onclick=action(async e=>{const b=e.target.closest('[data-action]');if(!b)return;const id=b.closest('[data-id]').dataset.id;switch(b.dataset.action){case'settings':edit(id);break;case'test':{const f=$('#test-form');f.reset();field(f,'id').value=id;$('#test-editor').showModal();break;}case'manage-channel':{const p=state.plugins.find(p=>Object.values(p.channels??{}).includes(id));if(p?.enabled&&(p.manifest.homepage||p.manifest.settings_page))view('plugin:'+p.id);else edit(id);break;}}});
$('#test-form').onsubmit=action(async e=>{e.preventDefault();const f=e.currentTarget,id=field(f,'id').value,c=source(id).config,canvas=document.createElement('canvas');canvas.width=400;canvas.height=300;const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,400,300);const file=field(f,'picture').files[0];if(file){const image=await createImageBitmap(file,{imageOrientation:'from-image'});const scale=Math.min(400/image.width,300/image.height);ctx.drawImage(image,(400-image.width*scale)/2,(300-image.height*scale)/2,image.width*scale,image.height*scale);image.close();}else{ctx.fillStyle='#222';ctx.font='14px Microsoft YaHei';ctx.fillText(c.name,25,35);ctx.fillRect(25,52,350,1);ctx.font='bold 34px Microsoft YaHei';ctx.fillText(field(f,'status').value,25,128);ctx.font='15px Microsoft YaHei';const message=field(f,'message').value;ctx.fillText(message.slice(0,22),25,177);ctx.fillText(message.slice(22),25,200);ctx.font='12px Microsoft YaHei';ctx.fillText(new Date().toLocaleTimeString('zh-CN'),25,271);}const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));const r=await fetch('/control/image/'+id,{method:'POST',headers:{'x-control-token':token},body:blob});if(!r.ok)throw Error(await r.text());$('#test-editor').close();await refresh();toast('已更新状态，任务有效期已刷新')});
$('#mode').onchange=action(async()=>{await command('mode','',{mode:$('#mode').value})});
$('#connect').onclick=action(async()=>{toast('正在连接指定设备…');await command('connect','',{target:$('#target').value});toast('设备已连接')});
$('#disconnect').onclick=action(async()=>command('disconnect'));
$('#preempt').onchange=action(async()=>command('global','',{preempt:$('#preempt').checked,paused:state.paused}));
$('#pause').onclick=action(async()=>command('global','',{preempt:state.preempt,paused:!state.paused}));
$('#retry').onclick=action(async()=>command('retry'));
document.querySelectorAll('[data-key]').forEach(b=>b.onclick=action(async()=>command('key','',{key:b.dataset.key})));
await refresh();setInterval(refresh,1000);

$('#save-reconnect').onclick=action(async()=>{await command('reconnect_settings','',{enabled:$('#reconnect-enabled').checked,window_seconds:+$('#reconnect-window').value,interval_seconds:+$('#reconnect-interval').value});toast('重连设置已保存')});

$('#save-application').onclick=action(async()=>{await command('application_settings','',{autostart:$('#autostart-enabled').checked});toast('软件设置已保存')});
