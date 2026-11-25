const {chromium}=require('playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const temp=path.join(root,'artifacts/tmp');fs.mkdirSync(temp,{recursive:true});
const tmp=fs.mkdtempSync(path.join(temp,'plugin-update-ui-'));
const out=path.join(root,'artifacts/tests/browser/plugin-update');fs.mkdirSync(out,{recursive:true});
const sample=path.join(root,'dist/plugins/desk-note.screen-plugin.zip'),updated=path.join(tmp,'updated.zip'),invalid=path.join(tmp,'invalid.zip');
execFileSync('python',['-c',`import io,json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as old,zipfile.ZipFile(sys.argv[2],'w') as new:
 for name in old.namelist():
  content=old.read(name)
  if name=='plugin.json':
   manifest=json.loads(content);manifest['version']='9.0-browser';content=json.dumps(manifest).encode()
  new.writestr(name,content)
`,sample,updated]);
fs.writeFileSync(invalid,'invalid zip');
(async()=>{
 const child=spawn(process.env.SCHEDULER_BINARY||path.join(root,'target/debug/note4-screen-scheduler.exe'),['--port','38504','--config',path.join(tmp,'settings.json'),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],{stdio:'ignore',windowsHide:true});
 let browser;const checks=[],errors=[];
 try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
  const page=await browser.newPage({viewport:{width:1400,height:950}});page.setDefaultTimeout(5000);page.on('pageerror',e=>errors.push(e.message));
  for(let n=0;n<60;n++){try{await page.goto('http://127.0.0.1:38504');break}catch{await new Promise(r=>setTimeout(r,150))}}
  await page.locator('.nav[data-view=plugins]').click();
  const button=page.locator('#plugin-install-form [type=submit]');
  await page.locator('#install-plugin').click();assert.equal(await button.isDisabled(),true);
  await page.locator('#plugin-file').setInputFiles(sample);
  await page.locator('#plugin-package-preview').filter({hasText:'新增插件'}).waitFor();
  await page.locator('#plugin-trust').check();await button.click();
  await page.locator('[data-plugin-id=desk-note]').waitFor();
  checks.push('existing_install_entry_previews_and_installs_new_id');
  await page.evaluate(async()=>{const s=await(await fetch('/control/state')).json(),p=s.plugins.find(p=>p.id==='desk-note');const r=await fetch('/control/plugins/desk-note',{method:'POST',headers:{'content-type':'application/json','x-control-token':s.token},body:JSON.stringify({op:'settings',data:{...p.settings,title:'private browser title'}})});if(!r.ok)throw Error(await r.text())});
  await page.locator('#install-plugin').click();await page.locator('#plugin-file').setInputFiles(updated);
  await page.locator('#plugin-package-preview').filter({hasText:'9.0-browser'}).waitFor();
  assert.equal(await button.textContent(),'更新并保留数据');
  await page.screenshot({path:path.join(out,'update-preview.png'),fullPage:true});
  await page.locator('#plugin-trust').check();await button.click();
  await page.locator('[data-plugin-id=desk-note] small').filter({hasText:'9.0-browser'}).waitFor();
  const state=await page.evaluate(async()=>(await(await fetch('/control/state')).json()));
  assert.equal(state.plugins.length,1);assert.equal(state.plugins[0].settings.title,'private browser title');assert.equal(state.plugins[0].enabled,false);
  checks.push('same_entry_previews_update_replaces_package_and_preserves_data');
  await page.locator('#install-plugin').click();await page.locator('#plugin-file').setInputFiles(invalid);
  await page.waitForFunction(()=>document.querySelector('#plugin-package-preview').textContent.includes('无法安装'));
  assert.equal(await button.isDisabled(),true);
  await page.locator('#plugin-file').setInputFiles(sample);
  await page.locator('#plugin-package-preview').filter({hasText:'将更新'}).waitFor();assert.equal(await button.isDisabled(),false);
  checks.push('invalid_zip_blocks_submit_and_file_reselection_recovers');
  await page.locator('[data-plugin-close=plugin-install]').click();
  // Delay an old inspection response and verify it cannot overwrite a newer selection.
  let release,intercepted;const first=new Promise(r=>intercepted=r);
  await page.route('**/control/plugins/inspect',async route=>{await new Promise(r=>{release=r;intercepted()});await route.continue()},{times:1});
  await page.locator('#install-plugin').click();await page.locator('#plugin-file').setInputFiles(sample);await first;
  await page.locator('#plugin-file').setInputFiles(updated);
  await page.locator('#plugin-package-preview').filter({hasText:'9.0-browser → v9.0-browser'}).waitFor();
  const oldResponse=page.waitForResponse(r=>r.url().endsWith('/control/plugins/inspect'));
  release();await oldResponse;
  assert.match(await page.locator('#plugin-package-preview').textContent(),/9\.0-browser → v9\.0-browser/);
  checks.push('late_inspection_does_not_overwrite_new_file_selection');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:checks.length,checks},null,2));console.log(JSON.stringify({passed:checks.length,checks},null,2));
 }finally{if(browser)await browser.close();child.kill();await new Promise(r=>child.once('exit',r));fs.rmSync(tmp,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
