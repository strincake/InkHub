const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const net=require('node:net');
const assert=require('node:assert/strict');

const root=path.resolve(__dirname,'../..');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function wait(fn){
 for(let i=0;i<100;i++){
  try{const value=await fn();if(value)return value}catch(error){if(i===99)throw error}
  await delay(100);
 }
 throw new Error('等待便签状态超时');
}
async function freePort(){
 const server=net.createServer();
 await new Promise((resolve,reject)=>server.once('error',reject).listen(0,'127.0.0.1',resolve));
 const port=server.address().port;
 await new Promise(resolve=>server.close(resolve));
 return port;
}

(async()=>{
 const temp=path.join(root,'artifacts/tmp');
 fs.mkdirSync(temp,{recursive:true});
 const config=path.join(fs.mkdtempSync(path.join(temp,'desk-note-browser-')),'settings.json');
 const binary=process.env.SCHEDULER_BINARY||path.join(root,'target/release',
   process.platform==='win32'?'note4-screen-scheduler.exe':'note4-screen-scheduler');
 const port=await freePort(),url=`http://127.0.0.1:${port}`;
 const child=spawn(binary,['--no-browser','--no-tray','--port',String(port),'--config',config,
   '--http-bind','127.0.0.1:0','--sdk-bind','127.0.0.1:0'],{stdio:['ignore','ignore','inherit'],windowsHide:true});
 let browser,token;
 const state=async()=>{const response=await fetch(url+'/control/state');return response.json()};
 const post=(endpoint,body)=>fetch(url+endpoint,{method:'POST',
   headers:{'content-type':'application/json','x-control-token':token},body:JSON.stringify(body)});
 const note=async()=>(await state()).plugins.find(p=>p.id==='desk-note');
 try{
  const initial=await wait(state);
  token=initial.token;
  const enable=await post('/control/plugins/desk-note',{op:'enable'});
  assert.equal(enable.status,200);
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
  const page=await browser.newPage();
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url);
  const open=page.locator('button[data-view="plugin:desk-note"]');
  const overview=page.locator('button[data-view="overview"]');
  await open.click();
  const frame=page.frameLocator('#plugin-frame');
  const savedText=async()=>(await note()).settings.document.notes?.[0].text;
  const input=frame.locator('#notes');
  await input.fill('不按保存按钮\n第二行');
  await frame.locator('#message').filter({hasText:'已保存'}).waitFor();
  assert.equal(await savedText(),'不按保存按钮\n第二行');

  const patches=[];
  await page.route('**/control/plugins/desk-note',async route=>{
   const data=route.request().postDataJSON();
   if(data.op==='patch_settings'){
    patches.push(data.data.document.notes[0].text);
    if(patches.length===1)await delay(600);
   }
   await route.continue();
  });
  await input.fill('较早的编辑');
  await wait(()=>patches.length===1);
  const theme=await post('/control/plugins/desk-note',{op:'patch_settings',data:{theme:'深色'}});
  assert.equal(theme.status,200);
  await input.fill('更新的编辑');
  await input.fill('离开页面前的最终编辑');
  await overview.click();
  await wait(async()=>await savedText()==='离开页面前的最终编辑');
  assert.deepEqual(patches,['较早的编辑','离开页面前的最终编辑']);
  assert.equal((await note()).settings.theme,'深色');
  await open.click();
  await wait(async()=>await input.inputValue()==='离开页面前的最终编辑');
  const persisted=JSON.parse(fs.readFileSync(path.join(path.dirname(config),
    'settings.plugins/data/desk-note/record.json'),'utf8'));
  assert.equal(persisted.settings.document.notes[0].text,'离开页面前的最终编辑');
  assert.deepEqual(errors,[]);
  console.log('PASS: autosave, edits during a pending write, navigation, and persisted settings patch');
 }finally{
  await browser?.close();
  if(token)await post('/control/command',{op:'stop',id:'',data:{}}).catch(()=>{});
  if(child.exitCode===null)child.kill();
 }
})().catch(error=>{console.error(error);process.exitCode=1});
