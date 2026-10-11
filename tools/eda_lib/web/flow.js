'use strict';
const FlowView = (() => {
  const labels = {synthesis:'DC 综合',route:'ICC2 布局布线',placement:'布局',cts:'时钟树',route_opt:'布线优化',timing:'PrimeTime 时序',sta_synthesized_netlist:'综合后时序检查'};
  const levelLabels = {fatal:'Fatal',error:'Error',warning:'Warning',info:'Information'};
  const svgNS = 'http://www.w3.org/2000/svg';
  const title = stage => labels[stage.id] || stage.id;
  const counts = stage => stage.diagnostics?.main?.counts;
  const number = (view, value) => value == null ? '—' : `${view.complete ? '' : '≥'}${value.toLocaleString()}`;

  function chooseStage(stage, severity) {
    $('issue-stage').value = stage;
    if (severity) $('issue-level').value = severity;
    $('issue-kind').value = 'main';
    render(latest.data.selected);
  }

  function countButton(stage, level, value) {
    const view = stage.diagnostics?.main || {};
    const button = node('button', `count-chip ${level}`, `${level === 'error' ? 'E' : 'W'} ${number(view,value)}`);
    button.type = 'button';
    button.title = `${level === 'error' ? 'Error + Fatal' : 'Warning'}：点击查看 ${stage.id} 的消息`;
    button.onclick = () => chooseStage(stage.id, level);
    return button;
  }

  function renderFlow(run) {
    const rail = $('stages');
    const scroll = rail.scrollLeft;
    rail.replaceChildren();
    run.stages.forEach((stage,index) => {
      if (index) {
        const blocked = stage.status === 'not_run';
        const edge = node('div', `flow-edge${blocked ? ' blocked' : ''}`);
        edge.append(node('span','edge-arrow','→'), node('span','edge-label',blocked ? '已阻断' : '下一阶段'));
        edge.setAttribute('aria-label',blocked ? '后续阶段未执行' : '阶段依赖');
        rail.append(edge);
      }
      const card = node('article',`flow-node ${color(stage.status)}${$('issue-stage').value === stage.id ? ' selected' : ''}`);
      const button = node('button','flow-node-head');
      button.type = 'button';
      button.onclick = () => chooseStage(stage.id);
      const top = node('span','stage-top');
      top.append(node('span','stage-num',String(index+1).padStart(2,'0')),badge(stage.status));
      button.append(top,node('span','stage-name',title(stage)),node('span','stage-tool',`${stage.tool} · ${stage.id}`));
      card.append(button);
      const values = counts(stage), chips = node('div','stage-counts');
      chips.append(countButton(stage,'error',values ? values.error+values.fatal : null),countButton(stage,'warning',values?.warning));
      card.append(chips);
      const checks = node('div','stage-checks');
      for (const [key,label] of [['drc_count','DRC'],['open_net_count','Open nets']]) {
        const check = stage.checks?.[key];
        if (!check) continue;
        const chip = node('span',`check-chip${check.value > 0 ? ' bad' : ''}`,`${label} ${check.value ?? '多项记录'}`);
        chip.title = check.evidence.map(e=>`${e.report}:${e.line} = ${e.value}`).join('\n');
        checks.append(chip);
      }
      if(stage.reasons.some(reason=>reason==='report_finding: invalid_parasitic_timing_evidence'))
        checks.append(node('span','check-chip bad','RC 未通过'));
      if (checks.childElementCount) card.append(checks);
      const notes = [];
      if (stage.wall_seconds != null) notes.push(duration(stage.wall_seconds));
      if (stage.attempt !== run.attempt) notes.push(`继承 attempt ${stage.attempt}`);
      if (stage.checkpoint_verified === true) notes.push('恢复点已验证');
      if (stage.checkpoint_verified === false) notes.push('恢复点验证失败');
      if (stage.exit_code) notes.push(`退出码 ${stage.exit_code}`);
      card.append(node('div','stage-bottom',notes.join(' · ') || '尚未执行'));
      const restore = stage.diagnostics?.restore;
      if (restore?.available) card.append(node('div','restore-note',`恢复校验：E ${number(restore,restore.counts.error+restore.counts.fatal)} / W ${number(restore,restore.counts.warning)}`));
      rail.append(card);
    });
    rail.scrollLeft = scroll;
  }

  function svgNode(name, attributes) {
    const element = document.createElementNS(svgNS,name);
    for (const [key,value] of Object.entries(attributes)) element.setAttribute(key,String(value));
    return element;
  }

  function renderChart(run) {
    const max = Math.max(1,...run.stages.flatMap(stage=>{const n=counts(stage);return n ? [n.error+n.fatal,n.warning] : [];}));
    $('message-chart').replaceChildren(...run.stages.map(stage => {
      const row = node('div',`chart-row${$('issue-stage').value===stage.id?' selected':''}`);
      const label = node('button','chart-label',title(stage));
      label.type='button';label.onclick=()=>chooseStage(stage.id);
      const svg=svgNode('svg',{viewBox:'0 0 400 38',preserveAspectRatio:'none','aria-hidden':'true'});
      const values=counts(stage),view=stage.diagnostics?.main||{};
      for (const x of [0,100,200,300,400]) svg.append(svgNode('line',{x1:x,x2:x,y1:0,y2:38,class:'chart-grid'}));
      if(values){
        svg.append(svgNode('rect',{x:0,y:4,width:(values.error+values.fatal)/max*396,height:12,rx:3,class:'error-bar'}));
        svg.append(svgNode('rect',{x:0,y:22,width:values.warning/max*396,height:12,rx:3,class:'warning-bar'}));
      }
      const totals=node('span','chart-values');
      totals.append(node('span','error-number',`E ${number(view,values?values.error+values.fatal:null)}`),node('span','warning-number',`W ${number(view,values?.warning)}`));
      row.append(label,svg,totals);
      if(!values)row.append(node('span','chart-unknown','未生成日志'));
      return row;
    }));
  }

  function openSample(group, sample) {
    selection.run_id=latest.data.selected.run_id;
    selection.log_attempt=String(group.attempt);
    selection.log=group.log;
    selection.log_offset=String(sample.offset);
    $('follow').checked=false;
    refresh().then(()=>$('log').scrollIntoView({block:'center',behavior:'smooth'}));
  }

  function renderIssues(run) {
    const stage=$('issue-stage').value, level=$('issue-level').value, kind=$('issue-kind').value;
    const query=$('issue-search').value.trim().toLowerCase();
    const groups=(run.diagnostics?.groups||[]).filter(group =>
      (!stage||group.stage===stage)&&(kind==='all'||group.kind===kind)&&
      (level==='all'||(level==='issues'&&group.severity!=='info')||(level==='error'&&['error','fatal'].includes(group.severity))||group.severity===level)&&
      (!query||`${group.code} ${group.message}`.toLowerCase().includes(query)));
    const priority={fatal:0,error:1,warning:2,info:3};
    groups.sort((a,b)=>priority[a.severity]-priority[b.severity]||b.count-a.count||a.stage.localeCompare(b.stage));
    const displayed=groups.slice(0,100);
    $('issue-summary').textContent=`${groups.length} 组消息 · ${groups.reduce((sum,g)=>sum+g.count,0).toLocaleString()} 次${groups.length>100?' · 展示前 100 组':''}${run.diagnostics?.groups_truncated?' · 超限分类已合并到 OTHER':''} · 同代码的重复出现合并展示`;
    const rows=displayed.map(group => {
      const row=node('tr');
      const severity=node('td'),tag=node('span',`badge ${group.severity==='warning'?'wait':group.severity==='info'?'active':'bad'}`,levelLabels[group.severity]);
      severity.append(tag,node('span','issue-stage-name',group.stage));
      const code=node('td','issue-code',group.code), count=node('td','issue-count',group.count.toLocaleString());
      const example=node('td','issue-message',group.message),source=node('td','issue-source');
      for(const sample of group.samples){
        const button=node('button','source-link',`${group.log}:${sample.line}`);button.type='button';button.onclick=()=>openSample(group,sample);source.append(button);
      }
      source.append(node('span','muted',`attempt ${group.attempt} · ${group.kind==='restore'?'恢复校验':'主流程'}`));
      row.append(severity,code,count,example,source);return row;
    });
    if(!rows.length){const row=node('tr'),cell=node('td','issues-empty',run.diagnostics?.complete?'当前筛选下没有已识别的消息。':'日志尚未统计完整；当前筛选下暂无已识别消息。');cell.colSpan=5;row.append(cell);rows.push(row);}
    $('issue-rows').replaceChildren(...rows);
  }

  function render(run) {
    syncSelect($('issue-stage'),[['','全部阶段'],...run.stages.map(stage=>[stage.id,title(stage)])],$('issue-stage').value);
    const summary=run.diagnostics||{}, total=summary.counts;
    $('error-count').textContent=number(summary,total?total.error+total.fatal:null);
    $('warning-count').textContent=number(summary,total?.warning);
    $('error-note').textContent=`主流程消息次数${total?` · 其中 Fatal ${total.fatal}`:''}；DRC 数单独展示`;
    $('warning-note').textContent=`${(summary.groups||[]).filter(g=>g.kind==='main'&&g.severity==='warning').length} 组 Warning${summary.groups_truncated?'（含合并项）':''} · 恢复校验另列`;
    const pending=run.stages.filter(s=>s.diagnostics?.main?.available&&!s.diagnostics.main.complete);
    const scanned=run.stages.reduce((sum,s)=>sum+(s.diagnostics?.main?.bytes_scanned||0),0);
    const bytes=run.stages.reduce((sum,s)=>sum+(s.diagnostics?.main?.bytes_total||0),0);
    $('scan-progress').textContent=summary.complete?`${summary.observed_stages} 个阶段日志已统计 · 含继承阶段`:`统计中 ${bytes?Math.floor(scanned/bytes*100):0}% · ${pending.length} 个日志待追平`;
    renderFlow(run);renderChart(run);renderIssues(run);
  }

  function reset() {
    $('issue-stage').value='';$('issue-level').value='issues';$('issue-kind').value='main';$('issue-search').value='';
  }

  function bind() {
    for(const id of ['issue-stage','issue-level','issue-kind'])$(id).onchange=()=>{if(latest?.data?.selected)render(latest.data.selected);};
    $('issue-search').oninput=()=>{if(latest?.data?.selected)renderIssues(latest.data.selected);};
    $('clear-issues').onclick=()=>{reset();if(latest?.data?.selected)render(latest.data.selected);};
  }
  return {render,reset,bind};
})();
