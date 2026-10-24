const {chromium}=require('playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
fs.mkdirSync(path.resolve(__dirname,'../../artifacts/tmp'),{recursive:true});
fs.mkdirSync(path.resolve(__dirname,'../../artifacts/tests/browser/general'),{recursive:true});
(async()=>{
 const root=path.resolve(__dirname,'../..'),tmp=fs.mkdtempSync(path.join(root,'artifacts/tmp/channels-browser-')),config=path.join(tmp,'settings.json'),port=38492,url=`http://127.0.0.1:${port}`;
 const pkg=path.join(tmp,'settings.plugins/packages/local-gallery');fs.mkdirSync(path.dirname(pkg),{recursive:true});fs.cpSync(path.join(root,'plugins/local-gallery'),pkg,{recursive:true});
 const child=spawn(process.env.SCHEDULER_BINARY||path.join(root,'target/debug/note4-screen-scheduler.exe'),['--port',String(port),'--config',config,'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],{stdio:'ignore',windowsHide:true});
 let browser;const checks=[];
 try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  for(let n=0;n<50;n++){try{await page.goto(url);break}catch{await new Promise(r=>setTimeout(r,150))}}
  await page.locator('#plugin-count').filter({hasText:'1'}).waitFor();
  assert.equal(await page.locator('#plugin-navigation button').count(),0);checks.push('disabled_plugin_has_no_sidebar_entry');
  await page.locator('[data-view=plugins]').first().click();
  await page.locator('[data-plugin-id=local-gallery] [data-plugin-action=toggle]').click();
  await page.locator('#plugin-navigation [data-view="plugin:local-gallery"]').waitFor();
  await page.locator('#plugin-navigation [data-view="plugin:local-gallery"]').click();
  const frame=page.frameLocator('#plugin-frame');await frame.locator('#add').click();await frame.locator('.album').nth(0).waitFor();await frame.locator('#add').click();await frame.locator('.album').nth(1).waitFor();
  assert.equal(await frame.locator('.album').count(),2,JSON.stringify(errors));
  await frame.locator('.album').nth(0).locator('[data-key=name]').fill('旅行照片');await frame.locator('.album').nth(0).locator('[data-key=folder]').fill(tmp);await frame.locator('.album').nth(0).locator('[data-key=fit]').selectOption('cover');
  await frame.locator('.album').nth(1).locator('[data-key=name]').fill('桌面收藏');await frame.locator('.album').nth(1).locator('[data-key=folder]').fill(tmp);
  const [savedResponse]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/control/plugins/local-gallery')&&r.request().method()==='POST'),frame.locator('#save').press('Enter')]);assert.equal(savedResponse.status(),200,await savedResponse.text());
  await page.waitForFunction(async()=>{const s=await (await fetch('/control/state')).json();const p=s.plugins[0];return Object.keys(p.channels).length===2&&p.settings.sources[0].name==='旅行照片'&&p.settings.sources[0].fit==='cover'&&p.settings.sources[1].name==='桌面收藏'});
  const s=await page.evaluate(async()=>await (await fetch('/control/state')).json());assert.equal(s.plugins[0].settings.sources[0].fit,'cover');checks.push('album_ui_adds_two_sources_and_saves_plugin_owned_fit');
  await frame.locator('body').evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(root,'artifacts/tests/browser/general/gallery-multichannel.png'),fullPage:true});
  await page.locator('[data-view=sources]').first().click();await page.locator('[data-action=manage-channel]').first().click();await page.locator('#plugin-home-view').waitFor({state:'visible'});checks.push('channel_card_opens_plugin_source_management');
  await page.locator('[data-view=plugins]').first().click();await page.locator('[data-plugin-id=local-gallery] [data-plugin-action=source]').first().click();assert.equal(await page.locator('#source-form [name=fit]').count(),0);await page.locator('[data-close=editor]').first().click();checks.push('host_source_editor_has_no_fit_control');
  await page.locator('#plugin-navigation [data-view="plugin:local-gallery"]').click();
  // Disable through the host API while its homepage is active; navigation must recover.
  await page.evaluate(async()=>{const s=await(await fetch('/control/state')).json();await fetch('/control/plugins/local-gallery',{method:'POST',headers:{'content-type':'application/json','x-control-token':s.token},body:JSON.stringify({op:'disable'})})});
  await page.locator('#plugin-home-view').waitFor({state:'hidden'});assert.equal(await page.locator('#plugin-navigation button').count(),0);checks.push('disable_active_home_removes_navigation_and_returns_overview');
  await page.locator('.nav[data-view=overview]').click();await page.locator('.settings-details summary').click();await page.locator('#reconnect-enabled').check();await page.locator('#reconnect-window').fill('180');await page.locator('#reconnect-interval').fill('3');await page.locator('#save-reconnect').click();await page.reload();await page.locator('.nav[data-view=overview]').click();await page.locator('.settings-details summary').click();await page.locator('#reconnect-window').filter({}).waitFor();
  await page.waitForFunction(()=>document.querySelector('#reconnect-window').value==='180');assert.equal(await page.locator('#reconnect-enabled').isChecked(),true);checks.push('reconnect_settings_save_and_reload');
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(root,'artifacts/tests/browser/general/reconnect-mobile.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.deepEqual(errors,[]);checks.push('desktop_mobile_no_page_errors_or_horizontal_overflow');
  fs.writeFileSync(path.join(root,'artifacts/tests/browser/general/channels-browser-result.json'),JSON.stringify({passed:checks.length,checks},null,2));console.log(JSON.stringify({passed:checks.length,checks}));
 }finally{if(browser)await browser.close();child.kill();await new Promise(r=>child.once('exit',r));fs.rmSync(tmp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
