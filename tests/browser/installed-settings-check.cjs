const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../..'),tmp=fs.mkdtempSync(path.join(root,'artifacts/tmp/installed-ui-'));
 const profile=path.join(tmp,'profile');fs.mkdirSync(profile);const user=path.join(tmp,'user');fs.mkdirSync(user);
 const version=fs.readFileSync(path.join(root,'Cargo.toml'),'utf8').match(/^version\s*=\s*"([^"]+)"/m)[1];
 const binary=path.join(root,'artifacts/package/windows-x64',version,'InkHub.exe'),port=38657,url=`http://127.0.0.1:${port}`;
 const child=spawn(binary,['--no-browser','--port',String(port),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],{env:{...process.env,LOCALAPPDATA:profile,USERPROFILE:user,PATH:path.join(process.env.SYSTEMROOT,'System32')},windowsHide:true,stdio:'ignore'});
 let browser;const errors=[],checks=[];
 const state=async()=>await(await fetch(url+'/control/state')).json();
 const stop=async()=>{const s=await state();await fetch(url+'/control/command',{method:'POST',headers:{'content-type':'application/json','x-control-token':s.token},body:JSON.stringify({op:'stop',data:{},id:''})})};
 try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});const page=await browser.newPage({viewport:{width:1440,height:1050}});page.on('pageerror',e=>errors.push(e.message));
  for(let n=0;n<60;n++){try{await page.goto(url);break}catch{await new Promise(r=>setTimeout(r,100))}}
  await page.locator('.application-settings summary').click();await page.locator('#autostart-enabled').waitFor();assert.equal(await page.locator('#autostart-enabled').isEnabled(),true);
  await page.locator('#autostart-enabled').check();await Promise.all([page.waitForResponse(r=>r.url().endsWith('/control/command')&&r.request().method()==='POST'),page.locator('#save-application').click()]);assert.equal((await state()).application.autostart,true);
  await page.reload();await page.locator('.application-settings summary').click();await page.waitForFunction(()=>document.querySelector('#autostart-enabled').checked);checks.push('installed_settings_ui_saves_and_reloads_autostart');
  await page.locator('#autostart-enabled').uncheck();await Promise.all([page.waitForResponse(r=>r.url().endsWith('/control/command')&&r.request().method()==='POST'),page.locator('#save-application').click()]);assert.equal((await state()).application.autostart,false);
  const output=path.join(root,'artifacts/tests/browser/installed');fs.mkdirSync(output,{recursive:true});await page.screenshot({path:path.join(output,'application-settings.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);checks.push('installed_settings_has_no_mobile_horizontal_overflow');
  await browser.close();browser=null;assert.equal((await state()).application.packaged,true);assert.equal(child.exitCode,null);checks.push('closing_browser_keeps_background_service_running');assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({passed:checks.length,checks},null,2));console.log(JSON.stringify({passed:checks.length,checks}));
 }finally{if(browser)await browser.close();if(child.exitCode===null){try{await stop()}catch{}await new Promise(r=>child.exitCode===null?child.once('exit',r):r())}if(path.dirname(tmp)===path.join(root,'artifacts/tmp'))fs.rmSync(tmp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
