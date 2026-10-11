'use strict';
const $ = id => document.getElementById(id);
const selection = {run_id: '', attempt: '', log: '', log_attempt: '', log_offset: ''};
let latest = null, busy = false, paused = false, timer = null, requestedRefresh = false;
const statusText = {queued:'排队中',running:'执行中',completed:'已完成',failed:'执行失败',timed_out:'已超时',cancelled:'已取消',interrupted:'执行中断',pending:'等待前序',not_run:'未执行',invalid:'验收未通过',insufficient:'证据不足'};
const reasonText = {stage_validation_blocked:'阶段验收未通过，后续阶段已停止。',checkpoint_restore_failed:'Checkpoint 重新打开验证失败。',tool_nonzero_exit:'工具以非零退出码结束。',run_budget_exhausted:'剩余预算不足，已停止启动后续阶段。',worker_missing_or_host_restarted:'后台 worker 已退出或执行机已重启。',memory_limit_exceeded:'工具进程组超过配置的内存限制。',cancelled:'任务已取消。',timed_out:'阶段运行超时。'};
function node(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; }
function date(value) { if(!value)return '—'; const d=new Date(value); return Number.isNaN(d.getTime())?'—':d.toLocaleString('zh-CN',{hour12:false}); }
function duration(seconds) { if(seconds==null||!Number.isFinite(seconds))return '—'; seconds=Math.max(0,Math.floor(seconds)); return seconds>=3600?`${Math.floor(seconds/3600)}h ${Math.floor(seconds%3600/60)}m`:seconds>=60?`${Math.floor(seconds/60)}m ${seconds%60}s`:`${seconds}s`; }
function memory(bytes) { return bytes==null?'—':`${(bytes/1024**3).toFixed(2)} GiB`; }
function viewStatus(run) { if(run.status==='completed'&&run.result_validity==='insufficient')return 'insufficient'; return run.status==='completed' && (run.result_validity!=='valid'||run.reason) ? 'invalid' : run.status; }
function color(status) { return status==='completed'?'good':status==='running'?'active':['queued','insufficient'].includes(status)?'wait':['failed','timed_out','interrupted','invalid'].includes(status)?'bad':''; }
function badge(status) { return node('span',`badge ${color(status)}`,statusText[status]||status); }
function syncSelect(element, options, value) {
  const signature=JSON.stringify(options);
  if(element.dataset.options!==signature){ element.replaceChildren(...options.map(([v,label])=>{const o=node('option','',label);o.value=v;return o;}));element.dataset.options=signature; }
  element.value=value;
}
function renderList(data) {
  $('run-count').textContent=data.runs.length;
  const filter=$('filter').value;
  const runs=data.runs.filter(r=>filter==='all'||(filter==='active'&&['running','queued'].includes(r.status))||(filter==='issues'&&['failed','timed_out','interrupted','invalid','insufficient'].includes(viewStatus(r)))||(filter==='done'&&viewStatus(r)==='completed'));
  const list=$('run-list'),scrollTop=list.scrollTop,scrollLeft=list.scrollLeft;list.replaceChildren();
  if(!runs.length)list.append(node('p','list-empty','没有符合条件的任务'));
  for(const run of runs){
    const button=node('button',`run-button${run.run_id===data.selected?.run_id?' selected':''}`);button.type='button';button.title=run.run_id;button.setAttribute('aria-pressed',String(run.run_id===data.selected?.run_id));
    button.append(node('span','run-id',run.run_id));const row=node('span','run-row');row.append(badge(viewStatus(run)),node('span','run-date',`attempt ${run.attempt}`));button.append(row);
    button.onclick=()=>{selection.run_id=run.run_id;selection.attempt='';selection.log='';selection.log_attempt='';selection.log_offset='';FlowView.reset();refresh();};list.append(button);
  }
  list.scrollTop=scrollTop;list.scrollLeft=scrollLeft;
}
function spark(id, history, key) {
  const values=history.map(s=>s[key]), valid=values.filter(v=>v!=null&&Number.isFinite(v));
  if(valid.length<2){$(id).setAttribute('points','');return;}
  const max=Math.max(...valid,1);
  // A null sample breaks continuity; only plot the most recent contiguous samples.
  let end=values.length-1;while(end>=0&&values[end]==null)end--;
  let start=end;while(start>=0&&values[start]!=null)start--;
  const tail=values.slice(start+1,end+1);if(tail.length<2){$(id).setAttribute('points','');return;}
  $(id).setAttribute('points',tail.map((v,i)=>`${i*240/(tail.length-1)},${34-v/max*29}`).join(' '));
}
function render(response) {
  latest=response;
  const connection=$('connection');connection.textContent=paused?'刷新已暂停':response.connected?'执行端已连接':'连接中断';connection.className=`connection ${paused?'waiting':response.connected?'':'offline'}`;
  $('connection-error').hidden=response.connected;
  $('connection-error').textContent=response.connected?'':`无法更新执行端状态。${response.data?'以下为上次成功读取的数据，不代表任务当前状态。':'等待连接恢复。'} ${response.error||''}`;
  const data=response.data;if(!data){$('detail').hidden=true;$('empty').hidden=false;$('empty-message').textContent='暂时没有可显示的数据，恢复连接后会自动更新。';return;}
  $('host').textContent=`${data.host.cpu_count??'—'} 个逻辑核 · 可用内存 ${data.host.available_memory_gib?.toFixed(1)??'—'} GiB`;
  $('last-refresh').textContent=`更新于 ${date(response.last_success_at)} · ${response.refresh_seconds}s / 次`;
  renderList(data);const run=data.selected;
  $('empty').hidden=!!run;$('detail').hidden=!run;
  if(!run){$('empty-message').textContent='当前运行目录还没有任务。通过执行器提交后会自动出现在这里。';return;}
  $('run-title').textContent=run.run_id;$('run-meta').textContent=`提交于 ${date(run.created_at)} · attempt ${run.attempt}`;
  const state=viewStatus(run);$('run-status').textContent=statusText[state]||state;$('run-status').className=`badge ${color(state)}`;
  syncSelect($('attempt'),[['','最新一次'],...run.attempts.map(n=>[String(n),`attempt ${n}`])],selection.attempt);
  const done=run.stages.filter(s=>s.status==='completed'&&s.validity==='valid'&&s.checkpoint_verified!==false).length;
  $('current-stage').textContent=run.current_stage||'等待启动';$('stage-progress').textContent=`${done} / ${run.stages.length} 个阶段通过检查`;
  const end=new Date(run.finished_at||data.sampled_at).getTime(),start=new Date(run.started_at||run.created_at).getTime();
  $('elapsed').textContent=duration((end-start)/1000);$('budget').textContent=`执行预算 ${duration(run.budget_seconds)}${run.started_at?'':' · 尚未开始执行'}`;
  const resources=run.resources;$('cpu').textContent=resources.cpu_percent==null?'—':`${resources.cpu_percent.toFixed(1)}%`;
  $('cpu-note').textContent=resources.process_count?`${resources.process_count} 个进程 · 100% = 1 核`:'当前无工具进程采样';
  const live=resources.rss_bytes!=null;$('memory').textContent=memory(live?resources.rss_bytes:run.peak_rss_bytes);
  $('memory-label').textContent=live?'工具内存 · RSS':'已完成阶段峰值 · RSS';
  $('memory-note').textContent='所属进程组，共享页可能重复计入';
  spark('cpu-chart',resources.history||[],'cpu_percent');spark('memory-chart',resources.history||[],'rss_bytes');
  FlowView.render(run);
  const reasons=[];if(run.reason)reasons.push(reasonText[run.reason]||run.reason);
  for(const s of run.stages)for(const reason of s.reasons)reasons.push(`${s.id}: ${reason}`);
  const unique=[...new Set(reasons)];$('reason-panel').hidden=!unique.length;$('reasons').replaceChildren(...unique.map(reason=>node('p','',reason)));
  const validity={valid:'声明的阶段检查已通过',invalid:'阶段结果无效',insufficient:'验收证据尚不完整'};
  $('validity').textContent=validity[run.result_validity]||'验收状态未知';$('qor').textContent=run.qor_comparable?'QoR manifest 已通过检查':'QoR 可比证据未齐备';
  syncSelect($('log-attempt'),[['','当前 attempt'],...run.attempts.map(n=>[String(n),`attempt ${n} 日志`])],selection.log_attempt);
  syncSelect($('log-select'),[['','自动选择日志'],...run.logs.map(name=>[name,name==='@worker'?'worker.log':name])],selection.log);
  const log=run.log;
  $('log-meta').textContent=`attempt ${run.log_attempt||run.attempt} · ${log.name==='@worker'?'worker.log':log.name||'暂无日志'} · ${log.total_bytes.toLocaleString()} bytes · ${log.at_tail===false?'已定位到消息上下文':'最新 64 KiB'}`;
  $('log-tail').hidden=log.at_tail!==false;
  const signature=`${run.log_attempt}:${log.name}:${log.window_offset}:${log.highlight_line}:${log.text}`;
  if($('log').dataset.signature!==signature){
    $('log').dataset.signature=signature;
    if(log.highlight_line!=null){
      $('log').replaceChildren(...log.text.split('\n').map((line,index)=>node('span',index===log.highlight_line?'log-focus-line':'',line+'\n')));
      const focus=$('log').querySelector('.log-focus-line');
      if(focus)$('log').scrollTop=focus.offsetTop-$('log').offsetTop-100;
    }else{
      $('log').textContent=log.text||'暂无日志输出。';if($('follow').checked)$('log').scrollTop=$('log').scrollHeight;
    }
  }
}
async function refresh() {
  if(busy){requestedRefresh=true;return;}clearTimeout(timer);busy=true;$('refresh').disabled=true;
  const query=new URLSearchParams();for(const [key,value] of Object.entries(selection))if(value)query.set(key,value);
  const signature=JSON.stringify(selection), controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),70000);
  try{
    const result=await fetch(`/api/snapshot?${query}`,{cache:'no-store',signal:controller.signal});
    if(!result.ok)throw new Error(`监控服务返回 HTTP ${result.status}`);
    const response=await result.json();if(signature===JSON.stringify(selection))render(response);
  }catch(error){if(signature===JSON.stringify(selection))render({connected:false,error:error.message,data:latest?.data||null,last_success_at:latest?.last_success_at||null,refresh_seconds:latest?.refresh_seconds||5});}
  finally{clearTimeout(timeout);busy=false;$('refresh').disabled=false;if(requestedRefresh){requestedRefresh=false;timer=setTimeout(refresh,0);}else if(!paused)timer=setTimeout(refresh,(latest?.refresh_seconds||5)*1000);}
}
$('refresh').onclick=refresh;
$('pause').onclick=()=>{paused=!paused;$('pause').textContent=paused?'恢复刷新':'暂停刷新';if(paused){clearTimeout(timer);if(latest)render(latest);}else refresh();};
$('filter').onchange=()=>{if(latest?.data)renderList(latest.data);};
$('attempt').onchange=()=>{selection.run_id=latest?.data?.selected?.run_id||selection.run_id;selection.attempt=$('attempt').value;selection.log='';selection.log_attempt='';selection.log_offset='';FlowView.reset();refresh();};
$('log-select').onchange=()=>{selection.run_id=latest?.data?.selected?.run_id||selection.run_id;selection.log=$('log-select').value;selection.log_offset='';refresh();};
$('log-attempt').onchange=()=>{selection.log_attempt=$('log-attempt').value;selection.log='';selection.log_offset='';refresh();};
$('log-tail').onclick=()=>{selection.log_offset='';$('follow').checked=true;refresh();};
$('copy-log').onclick=async()=>{try{await navigator.clipboard.writeText($('log').textContent);$('copy-log').textContent='已复制';}catch{$('copy-log').textContent='请选中日志复制';}setTimeout(()=>{$('copy-log').textContent='复制';},2000);};
FlowView.bind();
refresh();
