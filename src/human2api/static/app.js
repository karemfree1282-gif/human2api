'use strict';
const TOKEN = document.querySelector('meta[name="h2a-token"]').content;
const $ = (id) => document.getElementById(id);
const state = {workflows: [], selected: null, definition: null, tab: 'run'};
$('record-url').value = window.location.origin + '/demo';
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {'X-H2A-Token': TOKEN, ...(options.body ? {'Content-Type':'application/json'} : {}), ...(options.headers || {})}
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
let toastTimer;
function toast(message) { const node=$('toast'); node.textContent=message; node.classList.add('visible'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>node.classList.remove('visible'),3500); }
function node(tag, props={}, children=[]) { const element=document.createElement(tag); for(const [k,v] of Object.entries(props)) { if(k==='text') element.textContent=v; else if(k==='className') element.className=v; else if(k==='onclick') element.addEventListener('click',v); else element.setAttribute(k,v); } for(const child of children) element.append(child); return element; }
async function refresh() {
  try {
    const data=await api('/api/workflows');
    state.workflows=data.workflows;
    const picker=$('schedule-name');
    picker.replaceChildren(...data.workflows.map(w=>node('option',{value:w.name,text:w.name+' ('+w.permissions+')'})));
    $('metric-workflows').textContent=data.workflows.length;
    $('metric-actions').textContent=data.workflows.reduce((sum,x)=>sum+x.steps,0);
    $('nav-count').textContent=data.workflows.length;
    drawList();
    if(state.selected && data.workflows.some(x=>x.name===state.selected)) await selectWorkflow(state.selected);
    else if(data.workflows.length) await selectWorkflow(data.workflows[0].name);
    else { state.selected=null; $('details').replaceChildren(node('div',{className:'empty-detail'},[node('div',{className:'empty-icon',text:'{ }'}),node('h3',{text:'Create your first workflow'}),node('p',{text:'Click New recording to capture a task, or try the included demo.'})])); }
  } catch(err){toast('Cannot load workflows: '+err.message);}
}
function drawList() {
  const list=$('workflow-list'); list.replaceChildren();
  if(!state.workflows.length){list.append(node('p',{className:'empty-state',text:'No workflows found. Record one to get started.'}));return;}
  for(const workflow of state.workflows) {
    const entry=node('button',{className:'workflow-entry'+(state.selected===workflow.name?' selected':''),onclick:()=>selectWorkflow(workflow.name)});
    const icon=node('div',{className:'workflow-icon',text:'⌁'});
    const info=node('div',{className:'workflow-info'},[
      node('strong',{text:workflow.name}), node('span',{text:workflow.description}), node('small',{className:'workflow-meta',text:`${(workflow.target||'browser').toUpperCase()} · ${workflow.steps} actions · ${workflow.inputs} inputs · ${workflow.permissions}`})
    ]);
    entry.append(icon,info);list.append(entry);
  }
}
async function selectWorkflow(name) {
  try { state.definition=await api('/api/workflows/'+encodeURIComponent(name)); state.selected=name; state.tab='run'; drawList();drawDetails();}
  catch(err){toast(err.message);}
}
function drawDetails() {
  const wf=state.definition;if(!wf)return;
  const details=$('details');details.replaceChildren();
  const header=node('div',{className:'details-head'},[node('span',{className:'eyebrow eyebrow-small',text:'WORKFLOW DETAIL'}),node('span',{className:'tag'+(wf.permissions==='write'?' write':''),text:wf.permissions==='write'?'WRITE ACCESS':'READ ONLY'})]);
  details.append(header,node('h3',{text:wf.name}),node('p',{text:wf.description}));
  const tabs=node('div',{className:'detail-tabs'});
  for(const item of ['run','steps','json']) tabs.append(node('button',{className:state.tab===item?'current':'',onclick:()=>{state.tab=item;drawDetails();},text:item==='json'?'Edit JSON':item==='steps'?'Steps':'Run workflow'}));
  details.append(tabs);
  const body=node('div');details.append(body);
  if(state.tab==='steps') {
    for(const [i,step] of wf.steps.entries()) body.append(node('div',{className:'step-line'},[node('b',{text:String(i+1).padStart(2,'0')}),node('span',{text:`${step.action}   ${step.selector || step.url || step.filename || (Number.isInteger(step.x)?`(${step.x}, ${step.y})`: '')}`})]));
    body.append(node('div',{className:'detail-note',text:'All steps can be inspected and edited in JSON. AI healing is disabled by default and needs per-run consent.'}));
    return;
  }
  if(state.tab==='json') {
    const area=node('textarea',{className:'editor','aria-label':'Workflow JSON'});area.value=JSON.stringify(wf,null,2);
    const save=node('button',{className:'button button-primary',text:'Save workflow',onclick:async()=>{
      try {const parsed=JSON.parse(area.value);await api('/api/save/'+encodeURIComponent(wf.name),{method:'POST',body:JSON.stringify(parsed)});toast('Workflow saved');await selectWorkflow(wf.name);}catch(err){toast('Could not save: '+err.message);}
    }});
    body.append(area,node('div',{className:'workflow-run-footer'},[node('div',{className:'detail-note',text:'Workflow files contain actions, not recorded form values.'}),save]));return;
  }
  const form=node('form'); const fields=node('div',{className:'field-grid'});const inputRefs={};
  for(const [key,spec] of Object.entries(wf.inputs||{})) {
    const holder=node('div');const label=node('label',{text:key});
    const id='in-'+key;label.setAttribute('for',id);
    const input=node('input',{id,type:spec.secret?'password':spec.type==='number'?'number':spec.type==='boolean'?'checkbox':'text',placeholder:spec.description||key});
    if(spec.type==='number')input.step='any';
    if(spec.default!==undefined && spec.type!=='boolean')input.value=spec.default;
    if(spec.type==='boolean')input.checked=spec.default===true;
    if(spec.required!==false)input.required=true;
    inputRefs[key]={input,spec};holder.append(label,input);fields.append(holder);
  }
  if(!Object.keys(inputRefs).length) fields.append(node('div',{className:'detail-note',text:'This workflow needs no parameters.'}));
  form.append(fields);
  const approvalWrap=node('label',{className:'approve-label'});const approval=node('input',{type:'checkbox'});approvalWrap.append(approval,node('span',{text:'I approve this workflow to interact with the selected '+(wf.target||'browser')+' target.'}));
  if(wf.permissions!=='write')approvalWrap.style.display='none';
  const healWrap=node('label',{className:'approve-label'}), heal=node('input',{type:'checkbox'});
  healWrap.append(heal,node('span',{text:'Enable local semantic selector recovery (browser only)'}));
  const aiWrap=node('label',{className:'approve-label'}), ai=node('input',{type:'checkbox'});
  aiWrap.append(ai,node('span',{text:'Allow AI recovery: send sanitized UI element metadata to configured AI endpoint (browser only)'}));
  if((wf.target||'browser') !== 'browser'){healWrap.style.display='none';aiWrap.style.display='none';}
  ai.addEventListener('change',()=>{if(ai.checked)heal.checked=true;});
  const runButton=node('button',{className:'button button-primary',type:'submit',text:'▶  Run now'});
  const cancelButton=node('button',{className:'button button-soft',type:'button',text:'■  Cancel run'});
  cancelButton.disabled=true;
  let activeRunId=null;
  cancelButton.addEventListener('click',async()=>{
    if(!activeRunId)return;
    try { const result=await api('/api/runs/'+activeRunId+'/cancel',{method:'POST',body:'{}'});
      output.textContent='Cancellation requested. Waiting for the current action to finish safely…';
      cancelButton.disabled=true;
    } catch(err){toast('Could not cancel: '+err.message);}
  });
  form.append(healWrap,aiWrap,node('div',{className:'workflow-run-footer'},[approvalWrap,cancelButton,runButton]));
  const output=node('pre',{className:'run-output',text:'Ready. Runs locally on your '+(wf.target||'browser')+' engine. Check permissions before executing.'});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(wf.permissions==='write'&&!approval.checked){toast('Approve write actions before running.');return;}
    const args={}; for(const [key,{input,spec}] of Object.entries(inputRefs)){ if(spec.type==='boolean')args[key]=input.checked; else if(spec.type==='number')args[key]=Number(input.value); else if(input.value!=='')args[key]=input.value; }
    try {runButton.disabled=true;output.textContent='Executing '+(wf.target||'browser')+' workflow...';const r=await api('/api/run/'+encodeURIComponent(wf.name),{method:'POST',body:JSON.stringify({inputs:args,approve:approval.checked,healSelectors:heal.checked,aiHeal:ai.checked})});
      activeRunId=r.runId;cancelButton.disabled=false;
      let polls=0;const poll=async()=>{const status=await api('/api/runs/'+r.runId);
        if(['running','cancelling'].includes(status.state) && polls++<240){
          const current=status.lastStep;
          if(current)output.textContent=`${status.state} · step ${current.index}: ${current.action} (${current.state})`;
          setTimeout(poll,500);return;
        }
        activeRunId=null;cancelButton.disabled=true;
        output.textContent=JSON.stringify(status,null,2);runButton.disabled=false;showHistory();
      };await poll();
    }catch(err){output.textContent='Error: '+err.message;runButton.disabled=false;cancelButton.disabled=true;activeRunId=null;}
  });
  body.append(form,output);
}
$('new-record').addEventListener('click',()=>$('recorder-dialog').showModal());
for(const x of document.querySelectorAll('[data-close]'))x.addEventListener('click',()=>$('recorder-dialog').close());
$('recorder-form').addEventListener('submit',async event=>{
  event.preventDefault();const url=$('record-url').value;const name=$('record-name').value;
  try {const response=await api('/api/record',{method:'POST',body:JSON.stringify({url,name})});$('recorder-feedback').textContent=response.message;toast('Recorder launched');
    let attempts=0;
    const pollRecorder=async()=>{
      if(attempts++>120) return;
      try{const status=await api('/api/recorder');
        if(status.running){setTimeout(pollRecorder,1000);return;}
        if(status.exitCode===0){toast('Recording saved');$('recorder-dialog').close();await refresh();}
        else $('recorder-feedback').textContent='Recorder exited without saving. Try the CLI to see the error.';
      }catch(err){$('recorder-feedback').textContent=err.message;}
    };setTimeout(pollRecorder,1500);}
  catch(err){$('recorder-feedback').textContent=err.message;}
});
$('refresh').addEventListener('click',refresh);
$('spec-link').addEventListener('click', async (event) => {
  event.preventDefault();
  try {
    const spec=await api('/api/openapi.json');
    const url=URL.createObjectURL(new Blob([JSON.stringify(spec,null,2)],{type:'application/json'}));
    window.open(url,'_blank','noopener,noreferrer');
    setTimeout(()=>URL.revokeObjectURL(url),60000);
  }catch(err){toast('OpenAPI error: '+err.message);}
});
$('copy-cli').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('cli-code').textContent);toast('Copied to clipboard');}catch(err){toast('Clipboard unavailable');}});
refresh();

async function updateEngineStatus(){
  try{const p=await api('/api/platforms');
    if($('desktop-status')) $('desktop-status').textContent=p.desktop.dependencyAvailable?'Desktop dependencies detected':'Install: pip install "human2api[desktop]"';
    if($('android-status')) $('android-status').textContent=p.android.adbInstalled?'ADB installed. Connect an authorized phone':'Install Android platform-tools (ADB)';
  }catch(err){ /* status is informational */ }
}
async function showCatalog(remote=false){
  const destination=$('catalog-packages');if(!destination)return;
  destination.replaceChildren(node('p',{text:remote?'Fetching public workflow index…':'Inspecting local packages…'}));
  try{const catalog=await api(remote?'/api/catalog/remote':'/api/catalog');destination.replaceChildren();
    if(!catalog.packages.length){destination.append(node('p',{text:remote?'Public workflow index is empty.':'No local workflow packages yet. Use: h2a pack create_invoice --output catalog/create_invoice.h2a.zip'}));return;}
    for(const item of catalog.packages){
      const elements=[node('strong',{text:item.name}),node('small',{text:`${item.target} · ${item.publisher} · ${remote?'SHA-256 pinned':'checksum verified'}`}),node('span',{text:item.description})];
      if(remote)elements.push(node('code',{text:`h2a install-remote ${item.name} --approve`}));
      destination.append(node('article',{className:'catalog-entry'},elements));
    }
  }catch(err){destination.textContent='Could not load catalog: '+err.message;}
}
async function showHistory(){
  const destination=$('history-entries');if(!destination)return;
  try{const result=await api('/api/history');destination.replaceChildren();
    if(!result.history.length){destination.append(node('p',{text:'No executions yet. Start a local workflow to see metadata here.'}));return;}
    for(const record of result.history.slice(0,12)){
      const ts=new Date(record.createdAt*1000).toLocaleString();
      const duration=record.durationMs==null?'—':`${record.durationMs} ms`;
      destination.append(node('article',{className:'catalog-entry'},[node('strong',{text:record.workflow}),node('small',{text:`${record.target} · ${record.state}`}),node('span',{text:`${ts} · ${duration} · ${record.steps} steps`})]));
    }
  }catch(err){destination.textContent='Could not load run history: '+err.message;}
}
$('catalog-refresh')?.addEventListener('click',()=>showCatalog(false));
$('catalog-public')?.addEventListener('click',()=>showCatalog(true));
$('catalog-link')?.addEventListener('click',()=>showCatalog(false));
$('history-refresh')?.addEventListener('click',showHistory);
$('history-link')?.addEventListener('click',showHistory);
updateEngineStatus();
showCatalog(false);
showHistory();

async function showSchedules(){
  const host=$('scheduled-list');
  try{
    const data=await api('/api/schedules');host.replaceChildren();
    if(!data.schedules.length){host.append(node('p',{text:'No recurring tasks configured.'}));return;}
    for(const job of data.schedules){
      const row=node('div',{className:'schedule-row'});
      row.append(node('span',{text:`${job.name} · every ${job.everyMinutes} min · last: ${job.lastState||'never'} · next: ${new Date(job.nextRunAt*1000).toLocaleString()}`}));
      row.append(node('button',{className:'button button-soft',text:'Remove',onclick:async()=>{
        try{await api('/api/schedules/remove',{method:'POST',body:JSON.stringify({name:job.name})});
          toast('Schedule removed');showSchedules();}catch(err){toast(err.message);}
      }}));host.append(row);
    }
  }catch(err){host.replaceChildren(node('p',{text:'Schedules unavailable: '+err.message}));}
}
$('schedule-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const name=$('schedule-name').value;
  const interval=Number($('schedule-interval').value);
  const path=$('schedule-data').value.trim();
  try{await api('/api/schedules/add',{method:'POST',body:JSON.stringify({name,everyMinutes:interval,
      dataFile:path||null,approve:$('schedule-approval').checked})});
    toast('Schedule saved. Run h2a scheduler separately to start the worker.');showSchedules();
  }catch(err){toast('Schedule not saved: '+err.message);}
});
showSchedules();
