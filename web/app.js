(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let token = '', guide = [], current = 0, state = null, settings = null, shownRun = null;
  let toastTimer, simBusy = false, chatBusy = false;
  const read = new Set();
  const phases = {ready:'就绪',configured:'已配置模拟器',sampling:'模拟采样中',complete:'模拟完成',stopped:'已停止',error:'操作失败'};
  const eventNames = {simulation_configured:'模拟参数设置并回读',simulation_saved:'模拟证据已保存',stop:'停止本地任务',user_reset:'用户手动恢复演示',api_failed:'外部 API 失败，未重试',api_reply:'外部模型已回复',model_tool:'模型调用本地工具',model_tool_denied:'控制层拒绝工具请求',offline_reply:'离线教程已回复',settings_updated:'本次模型设置已更新',hardware_probe:'真实连接只读检查'};

  function toast(text) {
    clearTimeout(toastTimer); $('toast').textContent = text; $('toast').hidden = false;
    toastTimer = setTimeout(() => { $('toast').hidden = true; }, 8500);
  }
  async function api(path, body) {
    const headers = {'X-Copilot-Token':token};
    const options = {headers};
    if (body !== undefined) { options.method = 'POST'; headers['Content-Type']='application/json'; options.body=JSON.stringify(body); }
    let response;
    try { response = await fetch(path, options); } catch { throw new Error('本地服务未连接，请确认程序仍在运行后刷新页面。'); }
    let result;
    try { result = await response.json(); } catch { throw new Error('本地服务返回无效响应。'); }
    if (!response.ok) throw new Error(result.error || '操作失败');
    return result;
  }
  function element(tag, className, text) {
    const e = document.createElement(tag); if (className) e.className=className; if (text !== undefined) e.textContent=text; return e;
  }
  function renderGuide() {
    const nav = $('steps'); nav.replaceChildren();
    guide.forEach((step,index) => {
      const b=element('button', 'step'+(current===index?' selected':'')+(read.has(index)?' done':''));
      b.append(element('span','step-num',read.has(index)?'✓':String(index+1).padStart(2,'0')),element('span','',step.title));
      if(index===current)b.setAttribute('aria-current','step');
      b.addEventListener('click',()=>{current=index;renderGuide();}); nav.append(b);
    });
    $('step-label').textContent=String(current+1).padStart(2,'0')+' / 接线指导';
    $('guide-title').textContent=guide[current].title; $('guide-text').textContent=guide[current].text;
    $('step-read').checked=read.has(current); $('previous').disabled=current===0; $('next').disabled=current===guide.length-1;
  }
  function truth(summary) {
    const rows=summary?.rows || [{a:0,b:0,expected:0,count:0,errors:0},{a:0,b:1,expected:0,count:0,errors:0},{a:1,b:0,expected:0,count:0,errors:0},{a:1,b:1,expected:1,count:0,errors:0}];
    $('truth-body').replaceChildren(...rows.map(row=>{
      const tr=element('tr',row.errors?'error':'');
      [row.a,row.b,row.expected,row.count.toLocaleString(),!summary?'等待采样':!row.count?'未覆盖':row.errors?`${row.errors.toLocaleString()} 点不符`:'符合与逻辑'].forEach(x=>tr.append(element('td','',x)));
      return tr;
    }));
  }
  function svg(tag, attrs, text) {
    const e=document.createElementNS('http://www.w3.org/2000/svg',tag);
    Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v)); if(text!==undefined)e.textContent=text;return e;
  }
  function waveform(data) {
    const root=$('waveform');root.replaceChildren(); const n=data.points, width=682, left=53;
    const duration=n/data.sample_rate*1000;
    for(let i=0;i<=5;i++) {
      const x=left+width*i/5;
      root.append(svg('line',{x1:x,x2:x,y1:15,y2:167,stroke:'#e1e8da','stroke-dasharray':'3 4'}));
      root.append(svg('text',{x,y:190,fill:'#8b9a85','font-size':10,'text-anchor':'middle','font-family':'Consolas,monospace'},`${(duration*i/5).toFixed(duration<5?2:0)} ms`));
    }
    [['A','a','#497f69'],['B','b','#a68b45'],['Y','y','#367c98']].forEach(([label,key,color],index)=>{
      const baseline=49+index*53, high=baseline-22;
      root.append(svg('text',{x:11,y:baseline-6,fill:color,'font-size':15,'font-family':'Georgia,serif'},label));
      root.append(svg('text',{x:30,y:high+4,fill:'#a6b39d','font-size':8},'1'));
      root.append(svg('text',{x:30,y:baseline+4,fill:'#a6b39d','font-size':8},'0'));
      const points=data[key];let y=points[0]?high:baseline;let d=`M ${left} ${y}`;
      for(let i=1;i<n;i++)if(points[i]!==points[i-1]){const x=left+width*i/n;d+=` H ${x} V ${points[i]?high:baseline}`;}
      d+=` H ${left+width}`;
      root.append(svg('path',{d,stroke:color,'stroke-width':1.7,fill:'none','stroke-linejoin':'round'}));
    });
  }
  function renderResult(run) {
    if (!run || run.id===shownRun) return; shownRun=run.id;
    const s=run.summary; const labels={PASS:'符合与逻辑',FAIL:'逻辑不符',INCOMPLETE:'覆盖不足'};
    $('verdict').textContent=labels[s.verdict]||s.verdict; $('verdict').className=s.verdict==='FAIL'?'failed':s.verdict==='INCOMPLETE'?'incomplete':'';
    $('coverage').replaceChildren(document.createTextNode(String(s.coverage)+' '),element('small','','/ 4'));
    $('errors').replaceChildren(document.createTextNode(s.errors.toLocaleString()+' '),element('small','','点'));
    $('result-source').textContent='模拟证据 · 未验证硬件';
    $('config-readback').textContent=`模拟回读一致 · ${run.readback.frequency} Hz / ${(run.readback.sample_rate/1000).toLocaleString()} kS/s / ${run.readback.samples.toLocaleString()} 点 · 输出已结束`;
    $('result-details').textContent=`共 ${s.samples.toLocaleString()} 点 / ${(s.duration_s*1000).toFixed(1)} ms；有效稳态 ${s.stable_samples.toLocaleString()} 点；输入边沿前后各 ${s.guard_samples} 点排除，共 ${s.excluded_edges} 点。不据此评估毛刺或延迟。`;
    truth(s); if(run.preview){waveform(run.preview);$('wave').hidden=false;$('wave-empty').hidden=true;}
    $('downloads').hidden=false;
  }
  function renderHardware(hardware) {
    $('hardware-badge').textContent=hardware.connected?'只读已接通':'连接未建立';
    $('hardware-message').textContent=hardware.message+(hardware.time?` 检查于 ${new Date(hardware.time).toLocaleTimeString('zh-CN')}`:'');
    const labels={vplus_enabled:'V+ 使能',vplus_setting:'V+ 设定值 (V)',vminus_enabled:'V− 使能',dio_running:'Digital I/O 运行',dio2_direction:'DIO2 方向（原始值）',dio2_input:'DIO2 输入',logic_sample_rate:'逻辑采样率 (S/s)',logic_buffer_size:'逻辑缓冲点数'};
    $('hardware-values').replaceChildren(...Object.entries(hardware.snapshot||{}).map(([key,value])=>{
      const e=element('div');e.append(element('dt','',labels[key]||key),element('dd','',value));return e;
    }));
  }
  function renderState(s) {
    state=s; $('stopped-banner').hidden=!s.stopped;
    $('run').disabled=simBusy||s.stopped; $('send').disabled=chatBusy||s.stopped;
    $('log-count').textContent=s.events.length;
    $('events').replaceChildren(...s.events.slice(-30).reverse().map(item=>element('li','',`${new Date(item.time).toLocaleTimeString('zh-CN')} · ${eventNames[item.event]||item.event}${item.verdict?' · '+item.verdict:''}${item.name?' · '+item.name:''}`)));
    renderResult(s.last);renderHardware(s.hardware);
    document.title=`模电实验 Copilot · ${phases[s.phase]||s.phase}`;
  }
  async function refresh() { if(token)renderState(await api('/api/state')); }
  function message(text,type='assistant',source='本地助手') {
    const m=element('article',`message ${type}`);m.append(element('span','message-source',source),element('p','',text));
    $('chat-messages').append(m);$('chat-messages').scrollTop=$('chat-messages').scrollHeight;
  }
  async function send(text) {
    if(chatBusy||!text.trim())return;chatBusy=true;$('send').disabled=true;
    message(text,'user','你');$('chat-input').value='';
    const pending=element('p','muted small','正在处理…');$('chat-messages').append(pending);
    try {
      const r=await api('/api/chat',{text,mode:$('chat-mode').value});
      message(r.text,'assistant',r.source==='external_llm'?`外部模型 · ${r.model}`:r.source==='offline_rules'?'本地助手 · 固定教程':'本地控制层');
      await refresh();
    }catch(e){message(e.message,'assistant error','操作未完成');}
    finally{pending.remove();chatBusy=false;$('send').disabled=Boolean(state?.stopped);}
  }
  function modelLabel() {
    const external=$('chat-mode').value==='api';
    $('assistant-model').textContent=external?`${settings.model} · ${settings.has_key?'已设置本次密钥':'尚未设置密钥'}`:'离线教程 · 无需 API Key';
    $('chat-note').textContent=external?'对话与必要摘要会发送到所设 API':'离线模式提供固定教程与演示';
  }
  function showSettings() {
    $('base-url').value=settings.base_url;$('model-name').value=settings.model;$('api-key').value='';
    $('key-state').textContent=settings.has_key?'· 已配置，留空保留':'· 未配置';$('settings-error').textContent='';$('settings-dialog').showModal();
  }
  $('previous').addEventListener('click',()=>{if(current>0){current--;renderGuide();}});
  $('next').addEventListener('click',()=>{if(current<guide.length-1){current++;renderGuide();}});
  $('step-read').addEventListener('change',()=>{$('step-read').checked?read.add(current):read.delete(current);renderGuide();});
  $('simulation-form').addEventListener('submit',async event=>{
    event.preventDefault();if(simBusy)return;simBusy=true;$('run').disabled=true;$('run').textContent='模拟采样中…';
    try {
      const r=await api('/api/simulate',{config:{frequency:$('frequency').value,sample_rate:$('sample-rate').value,samples:Number($('samples').value)},fault:$('fault').value});
      renderResult(r);await refresh();toast('模拟完成，原始数据与判读已保存到本机。');
    }catch(e){toast(e.message);$('config-readback').textContent='未应用本次配置 · '+e.message;}
    finally{simBusy=false;$('run').disabled=Boolean(state?.stopped);$('run').textContent='▶ 运行模拟并判读';}
  });
  $('stop').addEventListener('click',async()=>{try{const r=await api('/api/stop',{});toast(r.message);await refresh();}catch(e){toast(e.message);}});
  $('reset').addEventListener('click',async()=>{try{const r=await api('/api/reset',{});toast(r.message);await refresh();}catch(e){toast(e.message);}});
  $('probe').addEventListener('click',async()=>{
    $('probe').disabled=true;$('probe').textContent='只读检查中…';
    try{await api('/api/probe',{});await refresh();}catch(e){toast(e.message);}
    finally{$('probe').disabled=false;$('probe').textContent='检查真实连接（只读）';}
  });
  $('chat-form').addEventListener('submit',e=>{e.preventDefault();send($('chat-input').value);});
  $('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();send($('chat-input').value);}});
  document.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>send(b.dataset.prompt)));
  $('chat-mode').addEventListener('change',modelLabel);
  $('settings-open').addEventListener('click',showSettings);
  $('settings-close').addEventListener('click',()=>{$('api-key').value='';$('settings-dialog').close();});
  $('settings-dialog').addEventListener('close',()=>{$('api-key').value='';});
  $('settings-form').addEventListener('submit',async e=>{
    e.preventDefault();const values={base_url:$('base-url').value,model:$('model-name').value,api_key:$('api-key').value};$('api-key').value='';
    try{settings=await api('/api/settings',values);values.api_key='';modelLabel();$('settings-dialog').close();toast('本次模型设置已保存。可在对话方式中选择外部 API。');}
    catch(error){values.api_key='';$('settings-error').textContent=error.message;}
  });
  $('clear-key').addEventListener('click',async()=>{try{settings=await api('/api/settings',{clear_key:true});$('api-key').value='';$('key-state').textContent='· 已清除';modelLabel();toast('本次密钥已从后端设置中清除。');}catch(e){$('settings-error').textContent=e.message;}});
  document.querySelectorAll('[data-file]').forEach(b=>b.addEventListener('click',async()=>{
    if(!shownRun)return;
    try{const r=await fetch(`/api/files/${shownRun}/${b.dataset.file}`,{headers:{'X-Copilot-Token':token}});if(!r.ok)throw new Error('证据下载失败');const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=`simulated_${shownRun.slice(0,8)}_${b.dataset.file}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){toast(e.message);}
  }));
  $('run').disabled=true;$('send').disabled=true;$('settings-open').disabled=true;
  truth(null);
  api('/api/bootstrap').then(boot=>{token=boot.token;guide=boot.guide;settings=boot.settings;renderGuide();renderState(boot.state);modelLabel();$('settings-open').disabled=false;})
    .catch(e=>toast(e.message));
  setInterval(()=>{if(token&&!document.hidden)refresh().catch(()=>{});},3000);
})();
