'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const token = document.querySelector('meta[name="h2a-token"]').content;
  const definitions = {
    browser: {navigate:{url:'https://example.org'},fill:{selector:'#field',value:'{{input_value}}'},click:{selector:'#button'},select:{selector:'#select',value:'{{input_value}}'},check:{selector:'#checkbox',checked:true},assert_text:{selector:'#result',text:'Expected result'},extract_text:{selector:'#result',as:'result'},wait:{selector:'#result'},wait_ms:{durationMs:500},screenshot:{filename:'result.png'},download:{selector:'#download',filename:'receipt.txt'},switch_tab:{index:0}},
    desktop: {ui_click:{windowTitle:'My application',automationId:'button'},ui_fill:{windowTitle:'My application',automationId:'field',value:'{{input_value}}'},ui_assert_text:{windowTitle:'My application',automationId:'status',text:'Saved'},ui_extract_text:{windowTitle:'My application',automationId:'status',as:'result'},click:{x:100,y:100},type_text:{value:'{{input_value}}'},hotkey:{keys:['ctrl','s']},wait_ms:{durationMs:500},screenshot:{filename:'desktop.png'}},
    android: {scroll_node:{selector:'com.example:id/list',by:'resource-id',direction:'forward'},tap_text:{selector:'com.example:id/button',by:'resource-id'},set_text:{selector:'com.example:id/field',by:'resource-id',value:'{{input_value}}'},tap:{x:100,y:100},swipe:{x:100,y:800,x2:100,y2:200,durationMs:300},input_text:{value:'{{input_value}}'},assert_text:{text:'Saved'},extract_text:{selector:'Status',as:'result'},keyevent:{key:'KEYCODE_BACK'},wait_ms:{durationMs:500},screenshot:{filename:'android.png'}}
  };
  Object.assign(definitions.browser,{press:{selector:'#field',key:'Enter'},hover:{selector:'#menu'},scroll:{selector:'#list',delta:3},drag:{selector:'#source',targetSelector:'#destination'}});
  Object.assign(definitions.desktop,{double_click:{x:100,y:100},move:{x:100,y:100},scroll:{delta:3},press:{key:'enter'},assert_image:{image:'expected.png'}});
  let wf = {schemaVersion:1,name:'new_workflow',description:'My inspectable automation',target:'browser',permissions:'write',startUrl:'https://example.org',networkPolicy:'strict',inputs:{},steps:[]};
  let selected = -1, revision = 'new', loadedName = null, dirty = false;
  function node(tag, text, cls) { const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n; }
  function message(text, error=false){$('issues').textContent=text;$('issues').classList.toggle('error',error);}
  async function api(path, opts={}){
    const res=await fetch(path,{...opts,headers:{'X-H2A-Token':token,'Content-Type':'application/json',...opts.headers}});
    const value=await res.json();if(!res.ok)throw Error(value.error||'Request failed');return value;
  }
  function collect(){wf.name=$('name').value;wf.description=$('description').value;wf.permissions=$('permission').value;
    if(wf.target==='browser'){wf.startUrl=$('url').value; if(wf.allowedHosts && !wf.allowedHosts.includes(new URL(wf.startUrl).hostname)) throw Error('Update allowedHosts in JSON for the new start URL.');}
    if(wf.target==='android'){const name=$('app-package').value.trim();if(name)wf.appPackage=name;else delete wf.appPackage;}
    return wf;
  }
  function jsonUpdate(){try{$('json').value=JSON.stringify(collect(),null,2);}catch(e){message(e.message,true);}}
  function mark(){dirty=true;jsonUpdate();}
  function render(){
    $('name').value=wf.name;$('target').value=wf.target||'browser';$('description').value=wf.description;$('permission').value=wf.permissions||'write';$('url').value=wf.startUrl||'';$('url-label').classList.toggle('hidden',wf.target!=='browser');$('app-package').value=wf.appPackage||'';$('package-label').classList.toggle('hidden',wf.target!=='android');
    $('palette').replaceChildren();for(const action of Object.keys(definitions[wf.target])){const b=node('button','+ '+action);b.onclick=()=>{wf.steps.push({action,...structuredClone(definitions[wf.target][action])});selected=wf.steps.length-1;dirty=true;autoInputs();render();};$('palette').append(b);}
    $('steps').replaceChildren();$('step-count').textContent=wf.steps.length;$('empty').hidden=wf.steps.length>0;
    wf.steps.forEach((step,index)=>{const card=node('div',undefined,'step'+(index===selected?' selected':''));card.draggable=true;card.tabIndex=0;card.setAttribute('role','button');card.setAttribute('aria-label','Step '+(index+1)+' '+step.action);card.onclick=()=>{selected=index;render();};card.onkeydown=e=>{if(e.key==='Enter'){selected=index;render();}};
      card.ondragstart=e=>e.dataTransfer.setData('text/plain',String(index));card.ondragover=e=>e.preventDefault();card.ondrop=e=>{e.preventDefault();const from=Number(e.dataTransfer.getData('text/plain'));if(Number.isInteger(from)&&from>=0&&from<wf.steps.length){wf.steps.splice(index,0,wf.steps.splice(from,1)[0]);selected=index;dirty=true;render();}};
      const info=node('div',undefined,'step-info');info.append(node('strong',step.action),node('small',step.selector||step.automationId||step.text||step.value||step.url||'Configured action'));
      card.append(node('span',String(index+1),'step-num'),info);
      for(const [label,delta] of [['Up',-1],['Down',1]]){const b=node('button',label);b.setAttribute('aria-label',label+' step '+(index+1));b.disabled=index+delta<0||index+delta>=wf.steps.length;b.onclick=e=>{e.stopPropagation();wf.steps.splice(index+delta,0,wf.steps.splice(index,1)[0]);selected=index+delta;dirty=true;render();};card.append(b);}
      const remove=node('button','Remove');remove.onclick=e=>{e.stopPropagation();wf.steps.splice(index,1);selected=Math.min(selected,wf.steps.length-1);dirty=true;render();};card.append(remove);$('steps').append(card);
    });
    $('fields').replaceChildren();$('selection').textContent=selected<0?'Choose a step to edit it.':'Step '+(selected+1)+' / '+wf.steps[selected]?.action;
    if(selected>=0&&wf.steps[selected])for(const [key,value] of Object.entries(wf.steps[selected])){if(key==='action')continue;const label=node('label',key),input=node('input');input.value=typeof value==='object'?JSON.stringify(value):String(value);input.dataset.field=key;input.onchange=()=>{try{wf.steps[selected][key]=typeof value==='number'?Number(input.value):typeof value==='boolean'?JSON.parse(input.value):typeof value==='object'?JSON.parse(input.value):input.value;autoInputs();dirty=true;render();}catch(e){message(e.message,true);}};label.append(input);$('fields').append(label);}
    drawInputs();jsonUpdate();
  }
  function autoInputs(){const matches=JSON.stringify(wf.steps).matchAll(/{{\s*([a-z][a-z0-9_]*)\s*}}/g);for(const match of matches)if(!wf.inputs[match[1]])wf.inputs[match[1]]={type:'string',required:true,secret:false};}
  function drawInputs(){$('inputs').replaceChildren();for(const [name,spec] of Object.entries(wf.inputs||{})){const row=node('div',undefined,'input-row'),title=node('strong',name),type=node('select');for(const t of ['string','number','boolean']){const option=node('option',t);option.value=t;type.append(option);}type.value=spec.type||'string';type.onchange=()=>{spec.type=type.value;mark();};const label=node('label','Secret (never store defaults)'),secret=node('input');secret.type='checkbox';secret.checked=!!spec.secret;secret.onchange=()=>{spec.secret=secret.checked;if(spec.secret)delete spec.default;mark();};label.prepend(secret);row.append(title,type,label);$('inputs').append(row);}}
  $('add-input').onclick=()=>{const name=prompt('Input name (lowercase and underscores)');if(name&&/^[a-z][a-z0-9_]{0,62}$/.test(name)){wf.inputs[name]={type:'string',required:true};dirty=true;render();}};
  for(const id of ['name','description','permission','url','app-package'])$(id).oninput=mark;
  $('target').onchange=()=>{if(wf.steps.length&&!confirm('Changing target clears the current steps. Continue?')){$('target').value=wf.target;return;}wf.target=$('target').value;wf.steps=[];selected=-1;delete wf.allowedHosts;delete wf.appPackage;delete wf.deviceSerial;delete wf.networkPolicy;if(wf.target==='browser'){wf.startUrl='https://example.org';wf.networkPolicy='strict';}else delete wf.startUrl;dirty=true;render();};
  $('validate').onclick=async()=>{try{const result=await api('/api/editor/validate',{method:'POST',body:JSON.stringify(collect())});message('Valid definition. '+result.stepCount+' steps. Nothing was executed.\n'+result.warnings.join('\n'));}catch(e){message(e.message,true);}};
  $('save').onclick=async()=>{try{const body=collect();const expected=loadedName===body.name?revision:'new';const result=await api('/api/editor/save/'+encodeURIComponent(body.name),{method:'POST',headers:{'If-Match':expected},body:JSON.stringify(body)});revision=result.revision;loadedName=body.name;dirty=false;message('Saved. Revision '+revision.slice(0,12));await refresh();}catch(e){message(e.message,true);}};
  $('apply-json').onclick=()=>{try{const value=JSON.parse($('json').value);if(!value||!Array.isArray(value.steps)||!definitions[value.target||'browser'])throw Error('Invalid workflow structure');wf=value;wf.target=wf.target||'browser';wf.inputs=wf.inputs||{};selected=-1;dirty=true;render();}catch(e){message(e.message,true);}};
  async function refresh(){try{const data=await api('/api/workflows');$('workflow-picker').replaceChildren(...data.workflows.map(w=>{const option=node('option',w.name);option.value=w.name;return option;}));if(loadedName)$('workflow-picker').value=loadedName;}catch(e){message(e.message,true);}}
  $('load').onclick=async()=>{if(dirty&&!confirm('Discard unsaved edits?'))return;try{const name=$('workflow-picker').value;const value=await api('/api/editor/workflows/'+encodeURIComponent(name));wf=value.workflow;wf.target=wf.target||'browser';wf.inputs=wf.inputs||{};revision=value.revision;loadedName=name;selected=-1;dirty=false;render();message('Loaded '+name);}catch(e){message(e.message,true);}};
  $('new').onclick=()=>{if(dirty&&!confirm('Discard unsaved edits?'))return;wf={schemaVersion:1,name:'new_workflow',description:'My inspectable automation',target:'browser',permissions:'write',networkPolicy:'strict',startUrl:'https://example.org',inputs:{},steps:[]};loadedName=null;revision='new';selected=-1;dirty=false;render();};
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});render();refresh();
})();
