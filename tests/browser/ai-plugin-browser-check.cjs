const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const temp=path.join(root,'artifacts/tmp');fs.mkdirSync(temp,{recursive:true});
const tmp=fs.mkdtempSync(path.join(temp,'ai-ui-'));
const out=path.join(root,'artifacts/tests/browser/ai-plugin');fs.mkdirSync(out,{recursive:true});
const files={'plugin.json':JSON.stringify({api_version:1,id:'ai-browser',name:'AI 浏览器测试',version:'1.0.0'}),'main.py':'def handle(ctx, event):\n    ctx.show(ctx.canvas(), "mono")\n'};
let bodySeen;
const mock=http.createServer((req,res)=>{let raw='';req.on('data',c=>raw+=c);req.on('end',()=>{bodySeen=JSON.parse(raw);res.setHeader('content-type','application/json');if(bodySeen.model==='bad'){res.end(JSON.stringify({choices:[{message:{content:'invalid json'}}]}));return}res.end(JSON.stringify({choices:[{message:{content:JSON.stringify({files,summary:'模拟生成结果'})}}]}));})});
(async()=>{
 await new Promise(resolve=>mock.listen(0,'127.0.0.1',resolve));
 const child=spawn(process.env.SCHEDULER_BINARY||path.join(root,'target/debug/note4-screen-scheduler.exe'),['--port','38514','--config',path.join(tmp,'settings.json'),'--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],{stdio:'ignore',windowsHide:true});
 let browser;const errors=[],checks=[];
 try{
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
  const page=await browser.newPage({viewport:{width:1400,height:1100}});page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
  for(let n=0;n<80;n++){try{await page.goto('http://127.0.0.1:38514');break}catch{await new Promise(r=>setTimeout(r,150))}}
  await page.locator('#create-ai-plugin').waitFor({state:'attached'});
  assert.equal(await page.locator('#mode').count(),0);
  const screen=await page.locator('.screen-panel').boundingBox(),queue=await page.locator('.queue-panel').boundingBox();assert(queue.y>=screen.y+screen.height);assert(Math.abs(queue.x-screen.x)<3);
  const icon=await page.request.get('http://127.0.0.1:38514/favicon.ico');assert(icon.ok());assert.equal(Buffer.compare(await icon.body(),fs.readFileSync(path.join(root,'packaging/windows/InkHub.ico'))),0);
  await page.screenshot({path:path.join(out,'overview-light.png'),fullPage:true});checks.push('queue_below_preview_mode_selector_removed_shared_icon');
  await page.locator('.nav[data-view=plugins]').click();await page.locator('#create-ai-plugin').click();
  await page.locator('#ai-prompt').fill('显示一个时钟');
  await page.locator('#ai-provider').selectOption({value:'deepseek'},{force:true});assert.equal(await page.locator('#ai-endpoint').inputValue(),'https://api.deepseek.com/v1');
  await page.locator('#ai-provider').selectOption({value:'custom'},{force:true});await page.locator('#ai-endpoint').fill(`http://127.0.0.1:${mock.address().port}/v1`);await page.locator('#ai-model').fill('mock');await page.locator('#ai-key').fill('private-secret');
  await page.locator('#ai-generate').click();await page.locator('#ai-result').waitFor();assert(bodySeen.messages[0].content.includes('ctx.show'));assert(!bodySeen.messages[0].content.includes('private-secret'));assert(!(await page.evaluate(()=>localStorage.getItem('inkhub-ai'))).includes('private-secret'));
  await page.locator('#ai-files summary').first().click();await page.screenshot({path:path.join(out,'generated-light.png'),fullPage:true});
  const downloadPromise=page.waitForEvent('download');await page.locator('#ai-download').click();const download=await downloadPromise;assert.equal(download.suggestedFilename(),'ai-browser.screen-plugin.zip');
  await page.locator('#ai-install').click();await page.locator('#plugin-package-preview').filter({hasText:'新增插件'}).waitFor();await page.locator('#plugin-trust').check();await page.locator('#plugin-install-form [type=submit]').click();await page.locator('[data-plugin-id=ai-browser]').waitFor();
  const s=await page.evaluate(async()=>(await(await fetch('/control/state')).json()));assert.equal(s.plugins[0].enabled,false);checks.push('api_generate_inspect_download_install_disabled_and_secret_not_saved');
  await page.locator('#create-ai-plugin').click();await page.locator('#ai-model').fill('bad');await page.locator('#ai-generate').click();await page.locator('#ai-status').filter({hasText:'未完成'}).waitFor();assert.equal(await page.locator('#ai-generate').isEnabled(),true);checks.push('invalid_ai_response_recovers');
  await page.locator('#ai-mode').selectOption({value:'mcp'},{force:true});await page.locator('#ai-transport').selectOption({value:'stdio'},{force:true});
  await page.locator('#ai-mcp-command').fill(process.env.PYTHON_BINARY||'python');await page.locator('#ai-mcp-args').fill(JSON.stringify([path.join(root,'tests/support/ai-mcp-mock.py')]));await page.locator('#ai-tools').click();await page.locator('#ai-status').filter({hasText:'读取到 1 个工具'}).waitFor();await page.locator('#ai-tool').selectOption({value:'generate'},{force:true});await page.locator('#ai-generate').click();await page.locator('#ai-result').waitFor();assert.match(await page.locator('#ai-result-title').textContent(),/AI Clock/);checks.push('local_stdio_mcp_discovery_and_generation');
  const skillPromise=page.waitForEvent('download');await page.locator('#ai-skill').click();const skill=await skillPromise;assert.equal(skill.suggestedFilename(),'inkhub-plugin.skill.zip');await skill.saveAs(path.join(out,'inkhub-plugin.skill.zip'));checks.push('bundled_skill_download');
  await page.locator('#ai-close').click();await page.locator('.nav[data-view=overview]').click();
  await page.locator('#appearance-mode').selectOption({value:'dark'},{force:true});await page.screenshot({path:path.join(out,'overview-dark.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'overview-mobile.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('.nav[data-view=plugins]').click();await page.locator('#create-ai-plugin').click();await page.locator('#ai-plugin').evaluate(el=>Promise.all(el.getAnimations().map(a=>a.finished)));await page.screenshot({path:path.join(out,'ai-mobile-dark.png'),fullPage:true});assert(await page.locator('#ai-plugin').evaluate(el=>el.scrollWidth<=el.clientWidth));checks.push('dark_mobile_layout_without_horizontal_overflow');
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:checks.length,checks},null,2));fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:checks.length,checks},null,2));
 }finally{if(browser)await browser.close();child.kill();mock.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
