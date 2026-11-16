'use strict';
let settings, avatars = [], csrf = '', editingRole = '';
const el = id => document.getElementById(id);
function notice(message, error=false) { const n=el('notice'); n.textContent=message; n.hidden=false; n.className=error?'error':''; }
async function api(path, options={}) {
  const headers = {...options.headers};
  if(options.method && options.method!=='GET') headers['X-Kiosk-CSRF']=csrf;
  if(options.body && !(options.body instanceof FormData)) { headers['Content-Type']='application/json'; options.body=JSON.stringify(options.body); }
  const res = await fetch(path,{...options,headers});
  const value = await res.json();
  if(!res.ok) throw new Error(typeof value.detail==='string'?value.detail:JSON.stringify(value.detail||value));
  return value;
}
function bindValue(input,value) { if(input.type==='checkbox') input.checked=!!value; else input.value=value??''; }
function readValue(input) { return input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value; }
function role() { return settings.roles.find(r=>r.id===editingRole); }
function collectRole() { if(!settings||!role())return; document.querySelectorAll('[data-role]').forEach(i=>role()[i.dataset.role]=readValue(i)); if(el('active-role').checked)settings.active_role=editingRole; }
function showRole() { document.querySelectorAll('[data-role]').forEach(i=>bindValue(i,role()[i.dataset.role])); el('active-role').checked=settings.active_role===editingRole; }
function refreshRolePicker() { el('role-picker').replaceChildren(...settings.roles.map(r=>new Option(r.name,r.id))); el('role-picker').value=editingRole; }
function populate() {
  document.querySelectorAll('[data-bind]').forEach(i=>{const [a,b]=i.dataset.bind.split('.');bindValue(i,settings[a][b]);});
  el('avatar_id').replaceChildren(...avatars.map(a=>new Option(a.name,a.id))); el('avatar_id').value=settings.avatar_id;
  avatarNote(); editingRole=settings.active_role;refreshRolePicker();showRole();
  el('orientation').value=settings.display.width===1080&&settings.display.height===1920?'portrait':settings.display.width===1920&&settings.display.height===1080?'landscape':'custom';
  const active=settings.roles.find(r=>r.id===settings.active_role);el('role-status').textContent=active.name;el('voice-status').textContent=active.voice;
}
function avatarNote() { const a=avatars.find(x=>x.id===el('avatar_id').value);el('avatar-note').textContent=a?.license_note||''; }
async function save() {
  collectRole();document.querySelectorAll('[data-bind]').forEach(i=>{const [a,b]=i.dataset.bind.split('.');settings[a][b]=readValue(i);});
  settings.avatar_id=el('avatar_id').value;
  settings=await api('/api/settings',{method:'PUT',body:settings});populate();notice('设置已保存。当前对话已结束，新设置已发送给人物客户端。');
}
async function health() {
  const h=await api('/health');el('ue-status').textContent=h.ue_connected?'已连接':'等待客户端';el('fay-status').textContent=h.fay_running?'正在运行':'未启动';
  el('status').textContent=h.ue_connected&&h.fay_running?'系统已连接':'本机管理服务正常';el('status').className='badge'+(h.ue_connected&&h.fay_running?' good':'');
}
async function documents() {
  const docs=await api('/api/documents');el('documents').replaceChildren();
  for(const d of docs) { const tr=document.createElement('tr');for(const v of [d.name,d.kb,`${d.indexed} / ${d.chunks}`]){const td=document.createElement('td');td.textContent=v;tr.append(td);}const td=document.createElement('td'),b=document.createElement('button');b.textContent='删除';b.onclick=()=>action(async()=>{await api('/api/documents/'+encodeURIComponent(d.id),{method:'DELETE'});await documents();notice('资料与索引已删除，当前对话已重置。');});td.append(b);tr.append(td);el('documents').append(tr); }
  if(!docs.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=4;td.textContent='暂无资料，请导入第一份知识文档。';tr.append(td);el('documents').append(tr);}
}
async function events() {
  const rows=await api('/api/events');el('events').replaceChildren();
  const names={sources:'知识引用',answer:'回答',tool:'接口回执',error:'服务异常',renderer_metrics:'渲染性能',client_error:'客户端异常'};
  for(const r of rows.slice(0,30)){const d=document.createElement('details'),s=document.createElement('summary'),p=document.createElement('pre');d.className='event';s.textContent=new Date(r.at*1000).toLocaleTimeString()+' · '+(names[r.kind]||r.kind);p.textContent=JSON.stringify(r.data,null,2);d.append(s,p);el('events').append(d);}
  if(!rows.length)el('events').textContent='暂无运行记录。连接人物客户端后开始测试。';
}
async function action(fn) { try { await fn(); } catch(e) { notice(e.message,true); } }
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.id===b.dataset.tab));if(b.dataset.tab==='connection')action(events);if(b.dataset.tab==='knowledge')action(documents);});
document.querySelectorAll('.save').forEach(b=>b.onclick=()=>action(save));
el('role-picker').onchange=()=>{collectRole();editingRole=el('role-picker').value;showRole();};
el('add-role').onclick=()=>{if(settings.roles.length>=20)return notice('最多可配置20个角色',true);collectRole();const r=structuredClone(role());r.id='role_'+Date.now().toString(36);r.name='新角色';settings.roles.push(r);editingRole=r.id;refreshRolePicker();showRole();};
el('avatar_id').onchange=avatarNote;
el('orientation').onchange=()=>{const v=el('orientation').value;if(v==='custom')return;document.querySelector('[data-bind="display.width"]').value=v==='portrait'?1080:1920;document.querySelector('[data-bind="display.height"]').value=v==='portrait'?1920:1080;};
el('upload-form').onsubmit=e=>{e.preventDefault();action(async()=>{const file=el('upload-file').files[0];if(!file)throw new Error('请选择文件');if(file.size>15*1024*1024)throw new Error('单文件不能超过15MB');const form=new FormData();form.append('file',file);form.append('knowledge_base',el('upload-kb').value);await api('/api/documents',{method:'POST',body:form});await documents();el('upload-file').value='';notice('资料已导入。建立向量索引后可提高检索效果。');});};
el('build-index').onclick=()=>action(async()=>{await api('/api/knowledge/index',{method:'POST'});notice('索引任务已启动，将调用云端向量服务。');});
el('save-key').onclick=()=>action(async()=>{const r=await api('/api/credentials',{method:'POST',body:{api_key:el('api-key').value}});el('api-key').value='';notice(r.message);});
el('send-text').onclick=()=>action(async()=>{await api('/api/input',{method:'POST',body:{text:el('test-text').value}});notice('问题已发送，请在人物客户端查看与收听。');});
el('interrupt').onclick=()=>action(async()=>{await api('/api/interrupt',{method:'POST'});notice('已发送停止播报指令。');});
el('refresh').onclick=()=>action(async()=>{await health();await events();});
action(async()=>{const data=await api('/api/bootstrap');settings=data.settings;avatars=data.avatars;csrf=data.csrf;populate();await health();await documents();});
setInterval(()=>action(async()=>{await health();const jobs=await api('/api/jobs');el('job-status').textContent=jobs.index?.message||'';if(el('connection').classList.contains('active'))await events();}),10000);
