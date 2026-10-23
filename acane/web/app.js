'use strict';
const $ = id => document.getElementById(id);
const labels = {pending:'待复核', approved:'已通过', redo:'需要重做', rejected:'已拒绝'};
const roles = {unknown:'未分类', vocals:'人声', instrumental:'伴奏', other:'其他'};
let items = [], current = null, busy = false, loadVersion = 0;
const identity = item => item.job_id + ':' + item.output.path;
const formatTime = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2,'0')}`;
const modelName = item => (item.parameters.model || '未知模型').replace('model_bs_roformer_ep_317_sdr_12.9755.ckpt','BS-RoFormer · Viperx 1297').replace('UVR_MDXNET_KARA_2.onnx','MDX · KARA 2');
function dirty() { return current && ($('note').value!==current.review.note || $('role').value!==current.review.role); }
function leaveDraft() { return !dirty() || window.confirm('当前音轨的备注或类型尚未保存，确定放弃这些修改吗？'); }
window.addEventListener('beforeunload',event=>{if(dirty()||busy){event.preventDefault();event.returnValue='';}});
function notice(message, error=false) { $('notice').textContent=message; $('notice').className='notice'+(error?' error':''); $('notice').hidden=!message; }
async function request(path, data) {
  const response = await fetch(path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败，请重试。');
  return result;
}
function lock(value) { busy=value; for (const id of ['approve','redo','reject','reset','refresh','open-export']) $(id).disabled=value; renderList(); }
function mediaUrl(item, kind) { return '/audio?' + new URLSearchParams({job:item.job_id,output:item.output.path,kind}); }
function renderList() {
  $('total').textContent=items.length;
  $('pending').textContent=items.filter(i=>i.review.decision==='pending').length;
  $('approved').textContent=items.filter(i=>i.review.decision==='approved').length;
  const search=$('search').value.toLocaleLowerCase();
  const filtered=items.filter(i=>($('filter').value==='all'||i.review.decision===$('filter').value) && (i.source_filename+' '+modelName(i)+' '+i.output.path).toLocaleLowerCase().includes(search));
  const container=$('queue'); container.replaceChildren();
  for (const item of filtered) {
    const button=document.createElement('button'); button.className='queue-item'+(current&&identity(current)===identity(item)?' selected':''); button.disabled=busy;
    button.setAttribute('aria-pressed',String(Boolean(current&&identity(current)===identity(item))));
    const title=document.createElement('span'); title.className='queue-title'; title.textContent=item.source_filename; title.title=item.source_filename;
    const meta=document.createElement('span'); meta.className='queue-meta';
    const model=document.createElement('span'); model.className='queue-model';
    const hint=item.output.path.includes('(Vocals)')?'人声文件':item.output.path.includes('(Instrumental)')?'伴奏文件':roles[item.review.role];
    model.textContent=hint+' · '+modelName(item); model.title=modelName(item)+' · '+hint;
    const badge=document.createElement('span'); badge.textContent=labels[item.review.decision];
    meta.append(model,badge); button.append(title,meta); button.onclick=()=>select(item); container.append(button);
  }
  $('list-empty').hidden=filtered.length>0;
}
async function reload(preferred) {
  const data=await request('/api/queue'); items=data.items;
  const next=items.find(i=>identity(i)===(preferred||(current&&identity(current)))) || items[0];
  if(next) await select(next); else {current=null;$('detail').hidden=true;$('empty').hidden=false;renderList();}
}
async function select(item) {
  if(current && identity(current)!==identity(item) && !leaveDraft())return;
  current=item; const version=++loadVersion;
  $('original').pause(); $('result').pause();
  $('detail').hidden=false; $('empty').hidden=true; $('filename').textContent=item.source_filename;
  $('model').textContent=modelName(item); $('duration').textContent=formatTime(item.output.duration)+' · '+(item.output.sample_rate/1000)+' kHz · '+item.output.channels+' 声道';
  const offset=Number(item.parameters.preview_start_s || 0);
  $('sample-label').textContent=item.operation==='separate_preview'?'短片样本':'整段结果';
  $('original-offset').textContent=offset?'对照从原录音 '+formatTime(offset)+' 开始':'保留原始录音';
  $('output-name').textContent=item.output.path.split('/').pop();
  $('decision-badge').className='badge '+item.review.decision; $('decision-badge').textContent=labels[item.review.decision];
  $('integrity').hidden=item.integrity==='valid'; $('integrity').textContent=item.integrity_error || '';
  $('role').value=item.review.role; $('note').value=item.review.note;
  $('original').src=mediaUrl(item,'original'); $('result').src=mediaUrl(item,'result');
  $('download-original').href=mediaUrl(item,'original')+'&download=1'; $('download-result').href=mediaUrl(item,'result')+'&download=1';
  $('original').onloadedmetadata=()=>{if(current===item)$('original').currentTime=Math.min(offset,$('original').duration || offset);};
  $('parameters').textContent=JSON.stringify({任务:item.job_id,处理参数:item.parameters,输出:item.output.path,文件指纹:item.output.sha256},null,2);
  $('history').replaceChildren(); $('history-empty').textContent='正在读取审核历史…'; $('history-empty').hidden=false; renderList();
  try {
    const data=await request('/api/history?'+new URLSearchParams({job:item.job_id,output:item.output.path}));
    if(version!==loadVersion)return;
    $('history-empty').textContent='还没有审核记录。'; $('history-empty').hidden=data.items.length>0;
    for(const entry of data.items.reverse()) {
      const li=document.createElement('li');li.className='history-item';
      const heading=document.createElement('strong');heading.textContent=labels[entry.decision]+' · '+roles[entry.role];
      const time=document.createElement('small');time.textContent=new Date(entry.created_at).toLocaleString();
      const note=document.createElement('p');note.className='history-note';note.textContent=entry.note || '未填写备注';
      li.append(heading,time,note);$('history').append(li);
    }
  } catch(error){notice(error.message,true);}
}
async function save(decision) {
  if(!current||busy)return;
  if(decision==='approved'&&$('role').value==='unknown'){notice('请先选择音轨类型，再确认通过。',true);$('role').focus();return;}
  lock(true);const item=current;
  try {
    await request('/api/review',{job_id:item.job_id,output_path:item.output.path,decision,role:$('role').value,note:$('note').value,expected_sequence:item.review.sequence,expected_sha256:item.output.sha256});
    await reload(identity(item));notice('已保存：'+labels[decision]+'。审核历史已保留。');
  } catch(error){notice(error.message,true);} finally {lock(false);}
}
function offset(){return Number(current?.parameters.preview_start_s || 0);}
async function switchPlayer(toOriginal) {
  if(!current)return;
  const from=$(toOriginal?'result':'original'),to=$(toOriginal?'original':'result');
  from.pause();
  if(to.readyState<1){notice('音频尚未载入，请稍后再试。',true);return;}
  const target=from.currentTime+(toOriginal?offset():-offset());
  to.currentTime=Math.max(0,Math.min(target,Number.isFinite(to.duration)?Math.max(0,to.duration-.02):target));
  try{await to.play();}catch(error){notice('无法播放此格式，可下载音轨后使用本地播放器试听。',true);}
}
$('original').onplay=()=>$('result').pause();$('result').onplay=()=>$('original').pause();
for(const id of ['original','result']) $(id).onerror=()=>notice('这条音频暂时无法播放，请检查文件是否完整，或下载音轨试听。',true);
$('switch-original').onclick=()=>switchPlayer(true);$('switch-result').onclick=()=>switchPlayer(false);
$('search').oninput=renderList;$('filter').onchange=renderList;
$('refresh').onclick=async()=>{if(busy||!leaveDraft())return;lock(true);try{await reload();notice('列表已刷新。');}catch(error){notice(error.message,true);}finally{lock(false);}};
$('approve').onclick=()=>save('approved');$('redo').onclick=()=>save('redo');$('reject').onclick=()=>save('rejected');$('reset').onclick=()=>save('pending');
$('open-export').onclick=()=>{$('export-error').textContent='';$('export-dialog').showModal();};
$('cancel-export').onclick=()=>$('export-dialog').close();
$('export-form').onsubmit=async event=>{
  event.preventDefault();if(busy||!current)return;lock(true);$('confirm-export').disabled=true;$('cancel-export').disabled=true;$('export-error').textContent='';$('export-status').textContent='正在导出，请保留程序窗口…';
  const rate=$('export-rate').value,channels=$('export-channels').value;
  try {
    const result=await request('/api/export',{job_ids:$('export-scope').value==='current'?[current.job_id]:null,sample_rate:rate?Number(rate):null,channels:channels?Number(channels):null});
    $('export-status').textContent=`已导出 ${result.count} 份人声：${result.directory}`;$('export-dialog').close();notice('数据集已保存，来源和审核记录已写入清单。');
  }catch(error){$('export-error').textContent=error.message;$('export-status').textContent='导出未完成。';}
  finally{lock(false);$('confirm-export').disabled=false;$('cancel-export').disabled=false;}
};
(async()=>{
  try{
    const key=new URLSearchParams(location.hash.slice(1)).get('key');
    if(key){const response=await fetch('/api/session',{method:'POST',headers:{'X-Session-Key':key}});if(!response.ok)throw new Error((await response.json()).error);history.replaceState(null,'',location.pathname);}
    await reload();
    await pollWorkbench();
    await request('/api/check',{});
    await pollWorkbench();
  }catch(error){notice(error.message,true);}
})();

// Import -> separation -> listening, without leaving the local application.
let workbenchState=null, selectedAssets=new Set(), uploading=false, polling=false;
function showView(name) {
  $('process-view').hidden=name!=='process';$('review-view').hidden=name!=='review';
  $('tab-process').classList.toggle('active',name==='process');$('tab-review').classList.toggle('active',name==='review');
}
$('tab-process').onclick=()=>{if(leaveDraft())showView('process');};
$('tab-review').onclick=async()=>{if(!leaveDraft())return;showView('review');try{await reload();}catch(error){notice(error.message,true);}};
function processButtonState(){
  $('start-separation').disabled=uploading||!workbenchState?.environment.ready||!selectedAssets.size;
  $('start-separation').textContent=selectedAssets.size?`开始分离（${selectedAssets.size}）`:'开始分离';
}
async function seeResults(assetId){
  if(!leaveDraft())return;
  showView('review');$('filter').value='all';$('search').value='';
  const data=await request('/api/queue');items=data.items;
  const matches=items.filter(item=>item.asset_id===assetId);
  const result=matches.filter(item=>item.output.path.includes('(Vocals)')).at(-1)||matches.at(-1);
  if(result){$('search').value=result.source_filename;await select(result);}else{notice('这份素材还没有成功的处理结果。',true);}
}
function renderWorkbench(){
  if(!workbenchState)return;
  const {assets,tasks,environment}=workbenchState;
  $('environment-title').textContent=environment.message;
  $('environment-detail').textContent=environment.ready?`${environment.device||'NVIDIA GPU'} · 处理结果单独保存`:'首次使用请准备运行组件；已安装的 GPU 环境会被复用。';
  const active=tasks.some(t=>['queued','running'].includes(t.status));
  $('check-environment').disabled=['checking','installing'].includes(environment.status)||active;
  $('prepare-environment').disabled=['checking','installing'].includes(environment.status)||active||environment.ready;
  $('asset-count').textContent=assets.length;$('assets-empty').hidden=assets.length>0;$('asset-list').replaceChildren();
  const live=new Map(tasks.filter(t=>['queued','running'].includes(t.status)).map(t=>[t.asset_id,t]));
  for(const asset of assets){
    const row=document.createElement('div');row.className='asset-row';
    const check=document.createElement('input');check.type='checkbox';check.checked=selectedAssets.has(asset.id);check.setAttribute('aria-label','选择 '+asset.filename);check.onchange=()=>{check.checked?selectedAssets.add(asset.id):selectedAssets.delete(asset.id);processButtonState();};
    const info=document.createElement('div');info.className='asset-info';const title=document.createElement('strong');title.textContent=asset.filename;
    const meta=document.createElement('small');const state=live.get(asset.id)?.status;meta.textContent=`${formatTime(asset.duration)} · ${(asset.sample_rate/1000).toFixed(1)} kHz · ${state==='running'?'正在分离':state==='queued'?'已排队':asset.successful_jobs?'已有处理结果':'待处理'}`;info.append(title,meta);row.append(check,info);
    if(asset.successful_jobs){const button=document.createElement('button');button.className='secondary';button.textContent='对比试听';button.onclick=()=>seeResults(asset.id).catch(error=>notice(error.message,true));row.append(button);}
    $('asset-list').append(row);
  }
  $('tasks-empty').hidden=tasks.length>0;$('task-list').replaceChildren();
  const stateNames={queued:'等待处理',running:'正在分离',completed:'已完成',failed:'处理失败'};
  for(const task of [...tasks].reverse()){
    const row=document.createElement('div');row.className='task-row';const head=document.createElement('div');head.className='task-heading';const title=document.createElement('strong');title.textContent=task.filename;const state=document.createElement('span');state.textContent=stateNames[task.status]+(task.status==='running'&&task.progress!=null?` · ${task.progress}%`:'');head.append(title,state);row.append(head);
    if(task.status==='running'){const bar=document.createElement('progress');bar.max=100;if(task.progress!=null)bar.value=task.progress;row.append(bar);}
    if(task.error){const error=document.createElement('p');error.className='task-error';error.textContent=task.error;row.append(error);}
    if(task.status==='completed'){const button=document.createElement('button');button.className='secondary';button.textContent='试听处理结果';button.onclick=()=>seeResults(task.asset_id).catch(error=>notice(error.message,true));row.append(button);}
    $('task-list').append(row);
  }
  const logs=[workbenchState.setup_log,...tasks.map(t=>t.log)].filter(Boolean);$('runtime-log').textContent=logs.join('\n\n')||environment.error||'暂无运行记录。';
  processButtonState();
}
async function pollWorkbench(){
  if(polling)return;polling=true;
  try{workbenchState=await request('/api/workbench');renderWorkbench();}catch(error){$('environment-title').textContent='连接暂时中断，请确认程序窗口仍在运行。';}finally{polling=false;}
}
$('select-all').onchange=()=>{selectedAssets=$('select-all').checked?new Set(workbenchState.assets.map(a=>a.id)):new Set();renderWorkbench();};
$('check-environment').onclick=async()=>{try{await request('/api/check',{});await pollWorkbench();}catch(error){notice(error.message,true);}};
$('prepare-environment').onclick=async()=>{try{await request('/api/prepare',{});await pollWorkbench();}catch(error){notice(error.message,true);}};
$('start-separation').onclick=async()=>{
  $('start-separation').disabled=true;
  try{const data=await request('/api/separate',{asset_ids:[...selectedAssets],force:$('force-new').checked});notice(data.count?`已加入 ${data.count} 份素材，处理完成后可对比试听。`:'所选素材已在处理中。');selectedAssets.clear();$('select-all').checked=false;await pollWorkbench();}catch(error){notice(error.message,true);}finally{processButtonState();}
};
async function upload(files){
  if(uploading||!files.length)return;uploading=true;$('choose-files').disabled=true;processButtonState();
  let imported=0;const failures=[];
  for(const file of files){
    $('upload-status').textContent=`正在导入 ${imported+failures.length+1}/${files.length}：${file.name}`;
    try{
      const response=await fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-File-Name':encodeURIComponent(file.name)},body:file});
      const data=await response.json();if(!response.ok)throw new Error(data.error);selectedAssets.add(data.id);imported++;
    }catch(error){failures.push(file.name+'：'+error.message);}
  }
  uploading=false;$('choose-files').disabled=false;$('file-picker').value='';
  $('upload-status').textContent=`已导入 ${imported} 份素材`+(failures.length?`，${failures.length} 份失败。`:'，可以开始分离。');
  if(failures.length)notice(failures.join('；'),true);await pollWorkbench();
}
$('choose-files').onclick=()=>$('file-picker').click();$('file-picker').onchange=()=>upload([...$('file-picker').files]);
for(const event of ['dragenter','dragover'])$('drop-zone').addEventListener(event,e=>{e.preventDefault();$('drop-zone').classList.add('dragging');});
for(const event of ['dragleave','drop'])$('drop-zone').addEventListener(event,e=>{e.preventDefault();$('drop-zone').classList.remove('dragging');});
$('drop-zone').addEventListener('drop',e=>upload([...e.dataTransfer.files]));
setInterval(pollWorkbench,2500);
