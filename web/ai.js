const providers=[
 ['openai','OpenAI','https://api.openai.com/v1','openai'],
 ['anthropic','Anthropic / Claude','https://api.anthropic.com/v1','anthropic'],
 ['deepseek','DeepSeek','https://api.deepseek.com/v1','openai'],
 ['qwen','通义千问（百炼 · 北京）','https://dashscope.aliyuncs.com/compatible-mode/v1','openai'],
 ['kimi','Kimi / Moonshot','https://api.moonshot.cn/v1','openai'],
 ['gemini','Google Gemini','https://generativelanguage.googleapis.com/v1beta/openai','openai'],
 ['ollama','Ollama（本机）','http://127.0.0.1:11434/v1','openai'],
 ['custom','自定义兼容服务','','openai']
];
export function mountAI({getState,onGenerated}){
 const $=s=>dialog.querySelector(s),dialog=document.createElement('dialog');dialog.className='ai-dialog';dialog.id='ai-plugin';
 dialog.innerHTML=`<div class="dialog-title"><h2>AI 写插件</h2><button type="button" class="close" id="ai-close" aria-label="关闭 AI 写插件">×</button></div>
 <p class="hint">描述想在 NOTE4 上显示的内容，生成后可检查源码、下载或安装。</p>
 <form id="ai-form"><fieldset id="ai-fields"><label class="field">插件需求<textarea id="ai-prompt" maxlength="12000" rows="4" required placeholder="例如：每分钟更新的番茄钟，确认键开始或暂停，上下键调整时长。"></textarea></label>
 <label class="field">连接方式<select id="ai-mode"><option value="api">API 服务</option><option value="mcp">本地 MCP</option></select></label>
 <div id="ai-api"><div class="form-grid"><label class="field">服务商<select id="ai-provider"></select></label><label class="field">接口格式<select id="ai-protocol"><option value="openai">OpenAI Chat Completions 兼容</option><option value="anthropic">Anthropic Messages</option></select></label></div>
 <label class="field">Endpoint（Base URL）<input id="ai-endpoint" type="url" placeholder="https://服务商地址/v1"><small>自动追加 /chat/completions 或 /messages；也可填写完整接口地址。</small></label>
 <div class="form-grid"><label class="field">API Key<input id="ai-key" type="password" autocomplete="off" spellcheck="false"><small>仅保留在本次页面会话；本地免密服务可留空。</small></label><label class="field">模型名称<input id="ai-model" placeholder="填写你账号可用的模型 ID"></label></div></div>
 <div id="ai-mcp" hidden><p class="hint">连接提供 AI 代码生成工具的本地 MCP 服务。普通文件或搜索 MCP 本身不提供模型。启动程序和调用工具会在本机执行。</p>
 <label class="field">传输方式<select id="ai-transport"><option value="http">Streamable HTTP</option><option value="stdio">stdio（启动本地程序）</option></select></label>
 <div id="ai-mcp-http"><label class="field">本地 MCP 地址<input id="ai-mcp-url" type="url" placeholder="http://127.0.0.1:3000/mcp"></label><label class="field">访问令牌（可选）<input id="ai-mcp-token" type="password" autocomplete="off"></label></div>
 <div id="ai-mcp-stdio" hidden><label class="field">程序路径<input id="ai-mcp-command" placeholder="例如 C:\\path\\to\\mcp-server.exe"></label><label class="field">启动参数（JSON 数组）<input id="ai-mcp-args" value="[]" spellcheck="false"></label><label class="field">环境变量（JSON 对象，可选）<textarea id="ai-mcp-env" rows="2" spellcheck="false">{}</textarea><small>令牌及环境变量仅保留在本次页面会话。</small></label></div>
 <div class="button-row"><button type="button" id="ai-tools">连接并读取工具</button></div><label class="field">生成工具<select id="ai-tool"><option value="">请先读取工具</option></select></label><details><summary>工具参数说明</summary><pre id="ai-schema">选择工具后显示其参数格式。</pre></details>
 <label class="field">调用参数（JSON 对象）<textarea id="ai-arguments" rows="4" spellcheck="false">{"prompt":"{{instructions}}\\n\\n{{prompt}}"}</textarea><small>按工具要求填写参数。{{prompt}} 替换为需求，{{instructions}} 替换为完整开发说明；两者都必须包含。</small></label></div>
 <p class="hint" id="ai-privacy">生成时将插件需求及开发说明发送给所选服务，不附带已安装插件或个人数据。连接设置自动保存在本机浏览器，密钥及环境变量不保存。</p>
 <div class="ai-toolbar"><button type="button" id="ai-skill">下载插件开发 Skill</button><button type="submit" id="ai-generate" class="primary">生成插件</button></div></fieldset></form>
 <p id="ai-status" class="hint ai-status" role="status" aria-live="polite"></p><section id="ai-result" class="ai-result" hidden><h3 id="ai-result-title"></h3><p class="hint" id="ai-summary"></p><p class="hint">已通过清单、路径与 Python 语法校验。尚未执行或验证功能；安装后可在模拟屏幕检查。</p><div id="ai-files" class="ai-files"></div><div class="ai-toolbar"><button type="button" id="ai-download">下载插件 ZIP</button><button type="button" class="primary" id="ai-install">查看安装预览</button></div></section>`;
 document.body.append(dialog);
 const provider=$('#ai-provider');providers.forEach(([id,name])=>provider.add(new Option(name,id)));
 const stored=['mode','provider','protocol','endpoint','model','transport','mcp-url','mcp-command','mcp-args','arguments'];
 try{const config=JSON.parse(localStorage.getItem('inkhub-ai')||'{}');for(const key of stored)if(typeof config[key]==='string')$('#ai-'+key).value=config[key]}catch{}
 if(!$('#ai-endpoint').value)$('#ai-endpoint').value=providers[0][2];
 function save(){const config={};for(const key of stored)config[key]=$('#ai-'+key).value;try{localStorage.setItem('inkhub-ai',JSON.stringify(config))}catch{}}
 function modes(){const mcp=$('#ai-mode').value==='mcp',stdio=$('#ai-transport').value==='stdio';$('#ai-api').hidden=mcp;$('#ai-mcp').hidden=!mcp;$('#ai-mcp-http').hidden=stdio;$('#ai-mcp-stdio').hidden=!stdio;for(const el of $('#ai-api').querySelectorAll('input,select'))el.disabled=mcp;for(const el of $('#ai-mcp').querySelectorAll('input,select,textarea,button'))el.disabled=!mcp;for(const el of $('#ai-mcp-http').querySelectorAll('input'))el.disabled=!mcp||stdio;for(const el of $('#ai-mcp-stdio').querySelectorAll('input,textarea'))el.disabled=!mcp||!stdio;window.schedulerControls?.refresh()}
 let busy=false,generated=null,tools=[];
 function setBusy(value,message){busy=value;$('#ai-fields').disabled=value;$('#ai-install').disabled=value;$('#ai-generate').textContent=value?'正在处理…':'生成插件';dialog.setAttribute('aria-busy',String(value));$('#ai-status').textContent=message;}
 function mcpConfig(){return {transport:$('#ai-transport').value,url:$('#ai-mcp-url').value.trim(),token:$('#ai-mcp-token').value,command:$('#ai-mcp-command').value.trim(),args:JSON.parse($('#ai-mcp-args').value||'[]'),env:JSON.parse($('#ai-mcp-env').value||'{}'),tool:$('#ai-tool').value,arguments:JSON.parse($('#ai-arguments').value||'{}')}}
 async function request(body){const r=await fetch('/control/ai',{method:'POST',headers:{'Content-Type':'application/json','x-control-token':getState().token},body:JSON.stringify(body)});if(!r.ok)throw Error(await r.text());return r.json()}
 async function work(message,fn){if(busy)return;save();setBusy(true,message);try{await fn()}catch(e){$('#ai-status').textContent='未完成：'+e.message+'。可检查配置后重试。'}finally{setBusy(false,$('#ai-status').textContent)}}
 function blob(data){return new Blob([Uint8Array.from(atob(data.zip_base64),c=>c.charCodeAt(0))],{type:'application/zip'})}
 function download(data,name){const url=URL.createObjectURL(blob(data)),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),2000)}
 $('#ai-close').onclick=()=>dialog.close();
 $('#ai-mode').onchange=$('#ai-transport').onchange=()=>{modes();save()};
 provider.onchange=()=>{const p=providers.find(p=>p[0]===provider.value);$('#ai-endpoint').value=p[2];$('#ai-protocol').value=p[3];$('#ai-model').value='';save();window.schedulerControls?.refresh()};
 $('#ai-form').addEventListener('change',save);
 $('#ai-tools').onclick=()=>work('正在连接本地 MCP 并读取工具…',async()=>{tools=[];$('#ai-tool').replaceChildren(new Option('请先读取工具',''));$('#ai-schema').textContent='正在读取…';const result=await request({op:'tools',mcp:mcpConfig()});tools=result.tools??[];const select=$('#ai-tool');select.replaceChildren(new Option('选择生成工具',''));tools.forEach(t=>select.add(new Option(t.title||t.name,t.name)));$('#ai-status').textContent=tools.length?`已连接，读取到 ${tools.length} 个工具。请选择生成工具并核对参数。`:'连接成功，但服务未提供工具。请连接提供代码生成工具的 MCP。';window.schedulerControls?.refresh()});
 $('#ai-tool').onchange=()=>{const tool=tools.find(t=>t.name===$('#ai-tool').value);$('#ai-schema').textContent=tool?`${tool.description||''}\n${JSON.stringify(tool.inputSchema,null,2)}`:'请选择工具';};
 $('#ai-form').onsubmit=e=>{e.preventDefault();work('正在生成并校验插件，通常需要几十秒，请等待…',async()=>{generated=null;$('#ai-result').hidden=true;const mode=$('#ai-mode').value;const result=await request({op:'generate',mode,prompt:$('#ai-prompt').value, ...(mode==='mcp'?{mcp:mcpConfig()}:{api:{endpoint:$('#ai-endpoint').value.trim(),key:$('#ai-key').value,model:$('#ai-model').value.trim(),protocol:$('#ai-protocol').value}})});generated=result;$('#ai-result-title').textContent=result.manifest.name+' · v'+result.manifest.version;$('#ai-summary').textContent=result.summary;const list=$('#ai-files');list.replaceChildren();for(const [name,content] of Object.entries(result.files)){const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent=name;pre.textContent=content;details.append(summary,pre);list.append(details)}$('#ai-result').hidden=false;$('#ai-status').textContent='生成完成。可查看源码后进入安装预览。';})};
 $('#ai-skill').onclick=()=>work('正在打包开发 Skill…',async()=>{const data=await request({op:'skill'});download(data,'inkhub-plugin.skill.zip');$('#ai-status').textContent='Skill 已下载。解压后将 inkhub-plugin 文件夹交给支持 Skill 的 AI 工具。'});
 $('#ai-download').onclick=()=>{if(generated)download(generated,generated.manifest.id+'.screen-plugin.zip')};
 $('#ai-install').onclick=()=>{if(!generated||busy)return;const file=new File([blob(generated)],generated.manifest.id+'.screen-plugin.zip',{type:'application/zip'});dialog.close();onGenerated(file)};
 modes();
 return {open(){dialog.showModal();window.schedulerControls?.refresh()}};
}
