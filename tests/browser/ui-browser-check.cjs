const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
fs.mkdirSync(path.resolve(__dirname,'../../artifacts/tmp'),{recursive:true});
fs.mkdirSync(path.resolve(__dirname,'../../artifacts/tests/browser/general'),{recursive:true});
(async()=>{
 const root=path.resolve(__dirname,'../..'),tmp=fs.mkdtempSync(path.join(root,'artifacts/tmp/ui-browser-')),out=path.resolve(root,'artifacts/tests/browser/ui');fs.mkdirSync(out,{recursive:true});
 const packages=path.join(tmp,'settings.plugins/packages');fs.mkdirSync(packages,{recursive:true});
 fs.cpSync(path.join(root,'plugins/desk-note'),path.join(packages,'desk-note'),{recursive:true});
 const binary=process.env.SCHEDULER_BINARY||path.resolve(root,'target/debug/note4-screen-scheduler.exe');
 const child=spawn(binary,['--port','38495','--config',path.join(tmp,'settings.json'),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],{stdio:'ignore',windowsHide:true});
 let browser;const checks=[],errors=[];
 try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});page.on('pageerror',e=>errors.push(e.message));
  for(let n=0;n<60;n++){try{await page.goto('http://127.0.0.1:38495');break}catch{await new Promise(r=>setTimeout(r,150))}}
  await page.waitForFunction(()=>document.querySelector('#connection').textContent.includes('模拟运行'));
  const nav=async name=>{await page.locator(`.nav[data-view="${name}"]`).click();};
  const command=async(op,id='',data={})=>page.evaluate(async({op,id,data})=>{const s=await(await fetch('/control/state')).json();const r=await fetch('/control/command',{method:'POST',headers:{'content-type':'application/json','x-control-token':s.token},body:JSON.stringify({op,id,data})});if(!r.ok)throw Error(await r.text());return r.json()},{op,id,data});
  assert.equal(await page.locator('#add-source').count(),0);
  assert.equal(await page.locator('#source-list').isVisible(),false);
  assert.equal(await page.locator('#mode').isVisible(),true);
  assert.equal(await page.locator('.workspace-grid .queue-panel').count(),1);
  checks.push('overview_contains_preview_queue_and_device_connection');
  await command('add','',{name:'任务进度',priority:3,min_ms:2000,hold_ms:30000,ttl_ms:120000,persistent:false,bypass:false,enabled:true,format:'mono'});
  await nav('sources');await page.locator('.source-card').waitFor();
  await page.locator('[data-action=settings]').click();await page.locator('#source-form [name=name]').fill('工作进度');await page.locator('#source-form [name=hold]').fill('60');await page.locator('#source-form [type=submit]').click();
  await page.locator('.card-name strong').filter({hasText:'工作进度'}).waitFor();
  await page.locator('[data-action=test]').click();await page.locator('#test-form [name=status]').selectOption({label:'正在进行'});await page.locator('#test-form [type=submit]').click();
  await nav('overview');await page.locator('#screen').waitFor({state:'visible'});await page.locator('#current-name').filter({hasText:'工作进度'}).waitFor();
  await page.locator('[data-key=Confirm]').click();await nav('sources');await page.locator('.source-details summary').click();await page.getByText('最近按键 Confirm').waitFor();
  assert.equal(await page.locator('#source-list [data-action=boost]').count(),0);await nav('overview');await page.locator('#queue-list [data-boost-id]').click();await page.locator('#boost-form [type=submit]').click();await page.locator('#queue-list .priority.boost').waitFor();await nav('sources');
  await page.screenshot({path:path.join(out,'sources.png'),fullPage:true,style:"#toast{visibility:hidden}"});checks.push('source_edit_update_key_and_boost');
  await nav('overview');await page.locator('#pause').click();await page.locator('#pause').filter({hasText:'恢复自动切换'}).waitFor();await page.locator('#pause').click();
  await page.screenshot({path:path.join(out,'overview.png'),fullPage:true,style:"#toast{visibility:hidden}"});checks.push('pause_resume');
  await nav('overview');await page.locator('.settings-details summary').click();await page.locator('#reconnect-enabled').check();await page.locator('#reconnect-window').fill('180');await page.locator('#reconnect-interval').fill('3');await page.locator('#save-reconnect').click();
  await page.reload();await nav('overview');await page.locator('.settings-details summary').click();await page.waitForFunction(()=>document.querySelector('#reconnect-window').value==='180');assert.equal(await page.locator('#reconnect-enabled').isChecked(),true);
  await page.locator('#preempt').uncheck();await page.waitForFunction(async()=>(await(await fetch('/control/state')).json()).preempt===false);await page.locator('#preempt').check();
  await page.screenshot({path:path.join(out,'device.png'),fullPage:true,style:"#toast{visibility:hidden}"});checks.push('device_reconnect_persistence_and_preemption');
  await nav('plugins');await page.locator('#external-tab').click();await page.getByText('等待程序接入',{exact:true}).waitFor();
  assert.equal(await page.locator('#sdk-address').isVisible(),true);
  const hostState=await page.evaluate(async()=>(await(await fetch('/control/state')).json()));
  const access='http://'+hostState.access.http;
  const register=async name=>{const r=await fetch(access+'/v1/sessions',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+hostState.access.api_key},body:JSON.stringify({name})});assert.equal(r.status,200);return r.json()};
  const removed=await register('外接测试程序'),other=await register('保留的程序');
  const pulse=setInterval(()=>{for(const session of [removed,other])fetch(access+'/v1/sessions/'+session.id+'/heartbeat',{method:'POST',headers:{authorization:'Bearer '+session.token}}).catch(()=>{})},3000);
  try{
   await page.locator('[data-external-delete="'+removed.id+'"]').waitFor();
   const png=Buffer.from(await(await fetch('http://127.0.0.1:38495/control/screen.png')).arrayBuffer());
   const submit=await fetch(access+'/v1/sessions/'+removed.id+'/frames/1',{method:'POST',headers:{authorization:'Bearer '+removed.token,'x-image-format':'mono'},body:png});assert.equal(submit.status,200);
   await command('settings',removed.id,{priority:1,min_ms:0,hold_ms:30000,ttl_ms:120000,enabled:true});
   await page.waitForFunction(id=>fetch('/control/state').then(r=>r.json()).then(s=>s.current?.frame.id===id),removed.id);
   await page.screenshot({path:path.join(out,'external.png'),fullPage:true,style:"#toast{visibility:hidden}"});
   await page.locator('[data-external-delete="'+removed.id+'"]').click();await page.locator('#external-cancel').click();assert.equal(await page.locator('[data-external-delete="'+removed.id+'"]').count(),1);
   await page.locator('[data-external-delete="'+removed.id+'"]').click();await page.locator('#external-confirm').click();
   await page.locator('#external-delete').waitFor({state:'hidden'});
   const after=await page.evaluate(async()=>(await(await fetch('/control/state')).json()));
   assert(!after.external.some(x=>x.id===removed.id));assert(!after.sources.some(x=>x.config.id===removed.id));assert(!after.queue.rows.some(x=>x.id===removed.id));assert.notEqual(after.current?.frame.id,removed.id);assert(after.external.some(x=>x.id===other.id));assert(after.sources.some(x=>x.config.name==='工作进度'));
   const stale=await fetch(access+'/v1/sessions/'+removed.id+'/heartbeat',{method:'POST',headers:{authorization:'Bearer '+removed.token}});assert.equal(stale.status,401);
   await page.locator('#external-tab').focus();await page.keyboard.press('ArrowLeft');assert.equal(await page.locator('#plugins-tab').getAttribute('aria-selected'),'true');
   checks.push('external_tab_registration_cancel_delete_current_channel_and_old_session_revocation');
  }finally{clearInterval(pulse);await fetch(access+'/v1/sessions/'+other.id,{method:'DELETE',headers:{authorization:'Bearer '+other.token}})}
  await nav('plugins');const card=page.locator('[data-plugin-id=desk-note]');await card.locator('[data-plugin-action=toggle]').click();await page.locator('.nav[data-view="plugin:desk-note"]').waitFor();await card.locator('[data-plugin-action=settings]').click();await page.locator('#plugin-settings-form [name=refresh_seconds]').fill('45');await page.locator('#plugin-settings-form [type=submit]').click();
  await page.screenshot({path:path.join(out,'plugins.png'),fullPage:true,style:"#toast{visibility:hidden}"});
  await nav('plugin:desk-note');const frame=page.frameLocator('#plugin-frame');await frame.getByText('已连接 · 编辑后应用到设备',{exact:true}).waitFor();assert.equal(await page.locator('#plugin-frame').getAttribute('sandbox'),'allow-scripts');
  await frame.locator('#title').fill('新版工作台');await frame.getByRole('button',{name:'应用到设备'}).click();await frame.getByText('已保存，启用时自动更新画面。',{exact:true}).waitFor();
  assert.equal(await page.locator('#overview-view').isVisible(),false);assert.equal(await page.locator('#sources-view').isVisible(),false);assert.equal(await page.locator('#device-view').count(),0);
  await page.evaluate(()=>window.oldPluginFrame=document.querySelector('#plugin-frame').contentWindow);await nav('plugins');await nav('plugin:desk-note');await frame.getByText('已连接 · 编辑后应用到设备',{exact:true}).waitFor();
  await page.evaluate(async()=>{const s=await(await fetch('/control/state')).json();dispatchEvent(new MessageEvent('message',{source:window.oldPluginFrame,data:{protocol:'screen-plugin-ui-v1',type:'save_settings',settings:{...s.plugins[0].settings,title:'STALE'}}}));});
  await page.waitForTimeout(250);assert.equal(await page.evaluate(async()=>(await(await fetch('/control/state')).json()).plugins[0].settings.document.notes[0].title),'新版工作台');checks.push('plugin_settings_home_bridge_and_stale_frame_isolation');
  for(const width of [390,760,1024,1440]){await page.setViewportSize({width,height:900});for(const name of ['overview','sources','plugins','logs','plugin:desk-note']){await nav(name);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${width} ${name} overflow`);if(name==='plugins'){await page.locator('#external-tab').click();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${width} external overflow`);if(width===390)await page.screenshot({path:path.join(out,'mobile-external.png'),fullPage:true,style:'#toast{visibility:hidden}'});await page.locator('#plugins-tab').click();}if(width===390)await page.screenshot({path:path.join(out,`mobile-${name.replace(':','-')}.png`),fullPage:true,style:"#toast{visibility:hidden}"});}}
  checks.push('all_views_no_overflow_at_four_widths');assert.deepEqual(errors,[]);checks.push('no_browser_errors');
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:checks.length,checks},null,2));console.log(JSON.stringify({passed:checks.length,checks}));
 }finally{if(browser)await browser.close();child.kill();if(child.exitCode===null)await new Promise(r=>child.once('exit',r));/* Keep isolated test data for inspection. */}
})().catch(e=>{console.error(e);process.exitCode=1});
