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
      node('strong',{text:workflow.name}), node('span',{text:workflow.description}), node('small',{className:'workflow-meta',text:`${workflow.steps} actions · ${workflow.inputs} inputs · ${workflow.permissions}`})
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
    for(const [i,step] of wf.steps.entries()) body.append(node('div',{className:'step-line'},[node('b',{text:String(i+1).padStart(2,'0')}),node('span',{text:`${step.action}   ${step.selector || step.url || step.filename || ''}`})]));
    body.append(node('div',{className:'detail-note',text:'Selectors are inspectable and editable in the JSON tab. No AI guesses are made at runtime.'}));
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
  const approvalWrap=node('label',{className:'approve-label'});const approval=node('input',{type:'checkbox'});approvalWrap.append(approval,node('span',{text:'I approve this workflow to perform actions on the target site.'}));
  if(wf.permissions!=='write')approvalWrap.style.display='none';
  const runButton=node('button',{className:'button button-primary',type:'submit',text:'▶  Run now'});
  form.append(node('div',{className:'workflow-run-footer'},[approvalWrap,runButton]));
  const output=node('pre',{className:'run-output',text:'Ready. Run executes in an isolated Chromium context.'});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(wf.permissions==='write'&&!approval.checked){toast('Approve write actions before running.');return;}
    const args={}; for(const [key,{input,spec}] of Object.entries(inputRefs)){ if(spec.type==='boolean')args[key]=input.checked; else if(spec.type==='number')args[key]=Number(input.value); else if(input.value!=='')args[key]=input.value; }
    try {runButton.disabled=true;output.textContent='Launching Chromium and running steps...';const r=await api('/api/run/'+encodeURIComponent(wf.name),{method:'POST',body:JSON.stringify({inputs:args,approve:approval.checked})});
      let polls=0;const poll=async()=>{const status=await api('/api/runs/'+r.runId);if(status.state==='running' && polls++<240){setTimeout(poll,500);return;} output.textContent=JSON.stringify(status,null,2);runButton.disabled=false;};await poll();
    }catch(err){output.textContent='Error: '+err.message;runButton.disabled=false;}
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
