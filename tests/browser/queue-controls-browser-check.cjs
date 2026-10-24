const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
fs.mkdirSync(path.resolve(__dirname,'../../artifacts/tmp'),{recursive:true});
fs.mkdirSync(path.resolve(__dirname,'../../artifacts/tests/browser/general'),{recursive:true});
(async()=>{
 const root=path.resolve(__dirname,'../..'),tmp=fs.mkdtempSync(path.join(root,'artifacts/tmp/queue-browser-')),out=path.resolve(root,'artifacts/tests/browser/queue-controls');fs.mkdirSync(out,{recursive:true});
 const child=spawn(process.env.SCHEDULER_BINARY||path.resolve(root,'target/debug/note4-screen-scheduler.exe'),['--port','38524','--config',path.join(tmp,'settings.json'),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],{windowsHide:true,stdio:'ignore'});
 let browser;const errors=[],checks=[];
 try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});const p=await browser.newPage({viewport:{width:1440,height:1050}});p.on('pageerror',e=>errors.push(e.message));
  for(let n=0;n<60;n++){try{await p.goto('http://127.0.0.1:38524');break}catch{await new Promise(r=>setTimeout(r,150))}}
  await p.locator('.connection-fields .select-trigger').waitFor();
  const state=()=>p.evaluate(async()=>(await(await fetch('/control/state')).json()));
  const command=async(op,id='',data={})=>{const s=await state(),r=await p.request.post('http://127.0.0.1:38524/control/command',{headers:{'x-control-token':s.token},data:{op,id,data}});assert.equal(r.status(),200,await r.text());};
  for(const name of ['队列甲','队列乙'])await command('add','',{name,priority:3,min_ms:0,hold_ms:0,ttl_ms:0,persistent:true,bypass:false,enabled:true,format:'mono'});
  await p.locator('.nav[data-view=sources]').click();await p.locator('.source-card').first().waitFor();assert.equal(await p.locator('#source-list [data-action=boost]').count(),0);
  for(const card of await p.locator('.source-card').all()){await card.locator('[data-action=test]').click();await p.locator('#test-form [type=submit]').click();await p.locator('#test-editor').waitFor({state:'hidden'});}
  const ids=(await state()).sources.map(s=>s.config.id);await p.locator('.nav[data-view=overview]').click();await p.locator('[data-boost-id]').nth(1).waitFor();
  await p.locator(`[data-boost-id="${ids[1]}"]`).click();assert.equal(await p.locator('#boost-source-name').textContent(),'队列乙');await p.locator('#boost-form [type=submit]').click();
  await p.waitForFunction(id=>fetch('/control/state').then(r=>r.json()).then(s=>s.sources.find(x=>x.config.id===id).config.boost?.priority===1),ids[1]);
  assert.equal((await state()).sources.find(x=>x.config.id===ids[0]).config.boost,null);await p.locator('#queue-list .priority.boost').waitFor();
  await p.locator(`[data-boost-id="${ids[1]}"]`).click();assert.equal(await p.locator('#boost-form [name=priority]').inputValue(),'1');await p.locator('#clear-boost').click();
  assert.equal((await state()).sources.find(x=>x.config.id===ids[1]).config.boost,null);checks.push('queue_action_targets_correct_source_and_clears_boost');
  for(const kind of ['forever','replaced']){await p.locator(`[data-boost-id="${ids[0]}"]`).click();await p.locator('#boost-form [name=kind]').selectOption(kind);await p.locator('#boost-form [type=submit]').click();await p.locator('#boost-editor').waitFor({state:'hidden'});await p.locator(`[data-boost-id="${ids[0]}"]`).click();assert.equal(await p.locator('#boost-form [name=kind]').inputValue(),kind);await p.locator('#clear-boost').click();}
  checks.push('existing_boost_duration_modes_preserved');
  const mode=p.locator('.connection-fields .select-trigger');await mode.click();await p.locator('.select-menu:popover-open').waitFor();assert.equal(await p.locator('.select-menu:popover-open [role=option]').count(),2);await p.keyboard.press('Escape');await mode.focus();await p.keyboard.press('ArrowDown');await p.keyboard.press('Enter');assert.equal(await p.locator('#mode').inputValue(),'simulation');checks.push('destination_menu_mouse_and_keyboard');
  for(const theme of ['light','dark']){await p.locator('#appearance-mode').selectOption(theme);for(const width of [390,760,1024,1440]){await p.setViewportSize({width,height:1050});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,theme+width);const style=await mode.evaluate(e=>{const s=getComputedStyle(e),t=e.children[0].getBoundingClientRect(),a=e.children[1].getBoundingClientRect();return{border:s.borderTopWidth,background:s.backgroundColor,delta:Math.abs(t.y+t.height/2-a.y-a.height/2)}});assert.equal(style.border,'1px');assert.notEqual(style.background,'rgba(0, 0, 0, 0)');assert(style.delta<4,JSON.stringify(style));await p.screenshot({path:path.join(out,`${theme}-${width}.png`),fullPage:true});}}
  checks.push('light_dark_four_widths_no_overflow_and_centered_arrow');assert.deepEqual(errors,[]);checks.push('no_browser_errors');fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:checks.length,checks},null,2));console.log(JSON.stringify({passed:checks.length,checks}));
 }finally{if(browser)await browser.close();child.kill();if(child.exitCode===null)await new Promise(r=>child.once('exit',r));}
})().catch(e=>{console.error(e);process.exitCode=1});
