// Browser validation using the repository's existing plain-Playwright convention.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');

fs.mkdirSync(path.resolve(__dirname,'../../artifacts/tmp'),{recursive:true});
fs.mkdirSync(path.resolve(__dirname,'../../artifacts/tests/browser/general'),{recursive:true});
(async()=>{
 const root=path.resolve(__dirname,'../..'),tmp=fs.mkdtempSync(path.join(root,'artifacts/tmp/companion-browser-'));
 const port=Number(process.env.COMPANION_BROWSER_PORT||38489),url=`http://127.0.0.1:${port}`;
 const binary=process.env.SCHEDULER_BINARY||path.join(root,'target/debug/note4-screen-scheduler.exe');
 const child=spawn(binary,['--port',String(port),'--config',path.join(tmp,'settings.json'),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],{stdio:'ignore',windowsHide:true});
 let browser,page,token;const errors=[];
 try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
  page=await browser.newPage({viewport:{width:1440,height:1120}});page.on('pageerror',error=>errors.push(error.message));
  for(let n=0;n<60;n++){try{await page.goto(url);break}catch{await new Promise(resolve=>setTimeout(resolve,150))}}
  const state=async()=>{const r=await page.request.get(url+'/control/state');return r.json()};
  token=(await state()).token;
  const post=async(endpoint,data)=>{const r=await page.request.post(url+endpoint,{headers:{'x-control-token':token},data});assert.equal(r.status(),200,await r.text());return r.json()};
  const archive=path.resolve(root,'dist/plugins/codex-companion.screen-plugin.zip');
  const installed=await page.request.post(url+'/control/plugins/install',{headers:{'x-control-token':token,'content-type':'application/zip'},data:fs.readFileSync(archive)});assert.equal(installed.status(),200);
  let plugin=(await state()).plugins.find(p=>p.id==='codex-companion');
  fs.mkdirSync(path.join(tmp,'sessions'));
  await post('/control/plugins/codex-companion',{op:'settings',data:{...plugin.settings,sessions_path:path.join(tmp,'sessions'),animation:false}});
  await post('/control/plugins/codex-companion',{op:'enable'});
  await page.reload();await page.locator('.nav[data-view="plugin:codex-companion"]').click();
  const frame=page.frameLocator('#plugin-frame');
  await frame.getByText('已连接墨枢',{exact:true}).waitFor();
  assert.equal(await page.locator('#plugin-frame').getAttribute('sandbox'),'allow-scripts');
  assert.equal(await frame.locator('body').evaluate(()=>{try{return !!parent.document.body}catch{return false}}),false);
  assert.equal(await frame.locator('#sound_enabled').isChecked(),false);
  await frame.locator('#volume').fill('35');await frame.getByRole('button',{name:'保存设置',exact:true}).click();
  for(let n=0;n<50;n++){plugin=(await state()).plugins.find(p=>p.id==='codex-companion');if(plugin.settings.volume===35&&!plugin.running)break;await page.waitForTimeout(150)}
  assert.equal(plugin.settings.volume,35);assert.equal(plugin.settings.animation,false);
  await frame.locator('summary').filter({hasText:'看看小搭子的表情'}).click();
  await frame.getByRole('button',{name:'工作',exact:true}).click();
  await frame.locator('#mode').filter({hasText:'演示画面'}).waitFor();
  await frame.getByRole('button',{name:'返回实时',exact:true}).click();await frame.locator('#mode').filter({hasText:'实时任务'}).waitFor();
  await frame.getByRole('button',{name:'试听等待',exact:true}).click();
  for(let n=0;n<60;n++){if((await state()).device.audio.status==='simulated')break;await page.waitForTimeout(150)}
  assert.equal((await state()).device.audio.status,'simulated');
  const output=path.resolve(root,'artifacts/tests/browser/general');fs.mkdirSync(output,{recursive:true});
  await page.screenshot({path:path.join(output,'companion-home-desktop.png'),fullPage:true});
  // State pushes from manual events must not overwrite an unsaved input.
  await frame.locator('summary').filter({hasText:'本机跟随设置'}).click();
  await frame.locator('#sessions_path').fill('未保存的编辑');
  await frame.getByRole('button',{name:'工作',exact:true}).click();await frame.locator('#mode').filter({hasText:'演示画面'}).waitFor();
  assert.equal(await frame.locator('#sessions_path').inputValue(),'未保存的编辑');
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'host horizontal overflow');
  assert.equal(await frame.locator('body').evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'plugin horizontal overflow');
  await page.screenshot({path:path.join(output,'companion-home-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  await post('/control/command',{op:'stop'});
  const result={passed:8,checks:['sandboxed_homepage_context','settings_persist_and_hidden_fields_preserved','separate_demo_and_realtime_modes','explicit_sound_action_simulated','unsaved_input_survives_state_push','desktop_render','mobile_no_horizontal_overflow','no_browser_script_errors'],physical_device_tested:false};
  fs.writeFileSync(path.join(root,'artifacts/tests/browser/general/companion-browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{
  if(browser)await browser.close();
  if(child.exitCode===null)child.kill();
  await new Promise(resolve=>child.exitCode!==null?resolve():child.once('exit',resolve));
  // The directory was freshly created under this repository, never user configuration.
  if(path.dirname(path.resolve(tmp))===path.resolve(root,'artifacts/tmp')&&path.basename(tmp).startsWith('companion-browser-'))fs.rmSync(tmp,{recursive:true,force:true});
 }
})().catch(error=>{console.error(error);process.exitCode=1});
