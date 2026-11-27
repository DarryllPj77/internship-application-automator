// Offline behavior tests for the table's Streamlit bridge and navigation.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];

test('General Masterlist filter excludes active and shared contacts and needs a saved active list',()=>{
  const table=setup();
  table.rows[0].general_masterlist=true;table.rows[0].active_partner=true;
  table.rows[1].general_masterlist=true;table.rows[1].active_partner=false;
  table.rows[2].general_masterlist=false;table.rows[2].active_partner=true;
  table.render([],false,true);
  table.elements['partner-filter'].value='general';table.elements['partner-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'1–1 of 1');
  assert.equal(table.elements['partner-filter-hint'].hidden,true);
  table.elements['status-filter'].value='pending';table.elements['status-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'1–1 of 1');
  table.render([],false,false);
  assert.equal(table.elements.range.textContent,'0 companies');
  assert.equal(table.elements['partner-filter-hint'].hidden,false);
  const restored=setup(false,table.storage);restored.rows[0].general_masterlist=true;
  restored.render();assert.equal(restored.elements['partner-filter'].value,'general');
});

test('company search ignores punctuation and finds imported directory aliases',()=>{
  const table=setup();
  table.rows[0].company_name='ABS-CBN Film Productions, Inc. (AFPI)';
  table.rows[0].directory_names=['ABS CBN Film Productions'];
  table.rows[0].active_partner=true;
  table.render([],false,true);
  table.elements['partner-filter'].value='active';
  table.elements.search.value='ABS CBN Film Productions';
  table.elements.search.fire('input');
  assert.equal(table.elements.range.textContent,'1–1 of 1');
  table.elements.search.value='abs-cbn film';table.elements.search.fire('input');
  assert.equal(table.elements.range.textContent,'1–1 of 1');
});

function setup(standalone=false, storage=new Map()) {
  class Element {
    constructor(tag='div') {this.tag=tag;this.children=[];this.listeners={};this.value='';this.checked=false;this.disabled=false;this.classes=new Set();this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name)}}
    append(...children) {this.children.push(...children)}
    replaceChildren(...children) {this.children=children}
    setAttribute(name,value) {this[name]=value}
    addEventListener(name,callback) {this.listeners[name]=callback}
    fire(name) {return this.listeners[name]?.({stopPropagation(){},preventDefault(){}})}
    showModal() {this.open=true}
    close() {this.open=false}
  }
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
  const elements=Object.fromEntries(ids.map(id=>[id,new Element()]));
  const messages=[],listeners={},requests=[];
  const parent={postMessage:message=>messages.push(message)};
  const document={getElementById:id=>elements[id],createElement:tag=>new Element(tag),createTextNode:text=>({text}),body:{getBoundingClientRect:()=>({height:420})},fonts:{ready:Promise.resolve()}};
  const window={parent,addEventListener:(name,fn)=>listeners[name]=fn,
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)}};
  if(standalone) {window.parent=window;window.postMessage=message=>messages.push(message)}
  const rows=Array.from({length:25},(_,i)=>({id:String(i),company_name:`Company ${i}`,hr_email:`hr${i}@acme.com`,contact_person:'HR',relevant_skills:'Python',status:i===0?'sent':'pending'}));
  let persisted=structuredClone(rows);
  const fetch=async(url,options={})=>{
    requests.push({url,...options});let data;
    if(url.startsWith('/api/preview/'))data={to:'current@company.com',subject:'Subject',body:'Body'};
    else {
      if(options.method==='PUT') {const id=url.split('/').at(-1);persisted=persisted.map(row=>row.id===id?{...row,...JSON.parse(options.body)}:row)}
      if(options.method==='DELETE')persisted=persisted.filter(row=>row.id!==url.split('/').at(-1));
      if(options.method==='POST')persisted=persisted.filter(row=>!JSON.parse(options.body).ids.includes(row.id));
      data=structuredClone(persisted);
    }
    return {ok:true,json:async()=>data};
  };
  vm.runInNewContext(script,{window,document,fetch,requestAnimationFrame:fn=>fn()});
  function render(selected_ids=[],disabled=false,active_available=false) {listeners.message({source:parent,data:{type:'streamlit:render',args:{rows,selected_ids,disabled,active_available,revision:'v1'}}})}
  const lastValue=()=>messages.filter(m=>m.type==='streamlit:setComponentValue').at(-1)?.value;
  return {elements,messages,listeners,render,lastValue,rows,requests,storage};
}

test('queue filter search and pagination survive frame recreation',()=>{
  const table=setup();table.render();
  table.elements['status-filter'].value='pending';table.elements['status-filter'].fire('change');
  table.elements.search.value='Company';table.elements.search.fire('input');
  table.elements.next.fire('click');
  const restored=setup(false,table.storage);restored.render(['12']);
  assert.equal(restored.elements['status-filter'].value,'pending');
  assert.equal(restored.elements.search.value,'Company');
  assert.equal(restored.elements.range.textContent,'11–20 of 24');
  assert.equal(restored.elements.selection.textContent,'1 selected');
  restored.elements['page-size'].value='20';restored.elements['page-size'].fire('change');
  const resized=setup(false,table.storage);resized.render();
  assert.equal(resized.elements['page-size'].value,'20');
  assert.equal(resized.elements.range.textContent,'1–20 of 24');
});

test('active-list filter combines with status, safely handles missing source, and persists',()=>{
  const table=setup();table.rows.forEach((row,i)=>row.active_partner=i<2);
  table.render();
  table.elements['partner-filter'].value='active';table.elements['partner-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'0 companies');
  assert.equal(table.elements['partner-filter-hint'].hidden,false);
  table.render([],false,true);
  assert.equal(table.elements.range.textContent,'1–2 of 2');
  table.elements['status-filter'].value='pending';table.elements['status-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'1–1 of 1');
  table.elements['select-pending'].fire('click');
  assert.deepEqual([...table.lastValue().selected_ids],['1']);
  table.elements['partner-filter'].value='unmatched';table.elements['partner-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'1–10 of 23');
  assert.equal(table.elements['selection-hint'].hidden,false);
  const restored=setup(false,table.storage);restored.rows.forEach((row,i)=>row.active_partner=i<2);
  restored.render([],false,true);
  assert.equal(restored.elements['partner-filter'].value,'unmatched');
  assert.equal(restored.elements.range.textContent,'1–10 of 23');
});

test('repeated-name review groups spelling variants without merging related legal entities',()=>{
  const table=setup();
  table.rows[0].company_name='Acme, Inc.';
  table.rows[1].company_name='ACME Corporation';
  table.rows[2].company_name='Chevron Holdings, Inc.';
  table.rows[3].company_name='Chevron Philippines, Inc.';
  table.render();
  table.elements['company-name-filter'].value='repeated';table.elements['company-name-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'1–2 of 2');
  table.elements['status-filter'].value='pending';table.elements['status-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'1–1 of 1');
  table.elements['select-pending'].fire('click');
  assert.deepEqual([...table.lastValue().selected_ids],['1']);
  table.elements['company-name-filter'].value='all';table.elements['company-name-filter'].fire('change');
  table.elements.search.value='Chevron';table.elements.search.fire('input');
  assert.equal(table.elements.range.textContent,'1–2 of 2');
  table.elements['company-name-filter'].value='repeated';table.elements['company-name-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'0 companies');
  table.elements['company-name-filter'].value='unique';table.elements['company-name-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'1–2 of 2');
  const restored=setup(false,table.storage);restored.rows[2].company_name='Chevron Holdings, Inc.';restored.rows[3].company_name='Chevron Philippines, Inc.';restored.render();
  assert.equal(restored.elements['company-name-filter'].value,'unique');
  assert.equal(table.rows.length,25);
  assert.equal(table.rows[0].status,'sent');
});

test('sent rows cannot be selected directly, from stale state, or through select page',()=>{
  const table=setup();table.render(['0']);
  const checkbox=table.elements.rows.children[0].children[0].children[0].children[0];
  assert.equal(checkbox.disabled,true);assert.equal(checkbox.checked,false);
  checkbox.checked=true;checkbox.fire('change');assert.equal(checkbox.checked,false);
  assert.equal(table.elements.selection.textContent,'0 selected');
  table.elements['select-page'].checked=true;table.elements['select-page'].fire('change');
  assert.equal(table.lastValue().selected_ids.includes('0'),false);
  assert.equal(table.lastValue().selected_ids.length,9);
  table.elements['status-filter'].value='sent';table.elements['status-filter'].fire('change');
  assert.equal(table.elements['select-page'].disabled,true);
});

test('select visible page affects only its rows',()=>{
  const table=setup();table.render();table.elements.next.fire('click');
  table.elements['select-page'].checked=true;table.elements['select-page'].fire('change');
  assert.equal(table.lastValue().selected_ids.length,10);
  assert.equal(table.lastValue().selected_ids[0],'10');
  assert.equal(table.lastValue().selected_ids[9],'19');
});

test('rapid checkbox clicks retain highlights through stale renders and acknowledgements',()=>{
  const table=setup();table.rows[0].status='pending';table.render();
  const first=table.elements.rows.children[0],second=table.elements.rows.children[1];
  const firstCheck=first.children[0].children[0].children[0];
  const secondCheck=second.children[0].children[0].children[0];
  firstCheck.checked=true;firstCheck.fire('change');
  secondCheck.checked=true;secondCheck.fire('change');
  table.render(['0']); // acknowledgement of the earlier click
  assert.equal(table.elements.selection.textContent,'2 selected');
  assert.equal(first.classes.has('selected'),true);
  assert.equal(second.classes.has('selected'),true);
  assert.equal(table.elements.rows.children[1],second);
  table.render(['0','1']);
  assert.equal(table.elements.rows.children[0],first);
  secondCheck.checked=false;secondCheck.fire('change');
  assert.equal(second.classes.has('selected'),false);
  assert.equal(table.elements.selection.textContent,'1 selected');
  table.render(['0','1','2']); // late server render must not undo unchecking
  assert.equal(table.elements.selection.textContent,'1 selected');
  table.render(['0']); // latest selection acknowledged
  table.render([]); // later authoritative clear is respected
  assert.equal(table.elements.selection.textContent,'0 selected');
});

test('delivery failure reason appears beneath the status as plain text',()=>{
  const table=setup();table.rows[0].status='failed';table.rows[0].status_reason='Recipient inbox is full.';
  table.render();
  const state=table.elements.rows.children[0].children[4];
  assert.equal(state.children[1].textContent,'Recipient inbox is full.');
  assert.equal(state.children[1].className,'status-reason');
});

test('inline edits emit the revision and edited field for Python validation',()=>{
  const table=setup();table.render();
  const field=table.elements.rows.children[0].children[2].children[0];
  field.value='new@acme.com';field.fire('change');
  assert.equal(table.lastValue().revision,'v1');
  assert.equal(table.lastValue().rows[0].hr_email,'new@acme.com');
});

test('status filter combines with text search and selects only matching visible rows',()=>{
  const table=setup();
  table.rows[2].status='drafted';table.rows[3].status='failed';
  table.render();table.elements.next.fire('click');
  table.elements['status-filter'].value='drafted';table.elements['status-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'1–1 of 1');
  assert.equal(table.elements.rows.children[0].children[1].children[0].value,'Company 2');
  table.elements['select-page'].checked=true;table.elements['select-page'].fire('change');
  assert.deepEqual([...table.lastValue().selected_ids],['2']);
  table.elements['status-filter'].value='sent';table.elements['status-filter'].fire('change');
  assert.equal(table.elements.rows.children[0].children[1].children[0].value,'Company 0');
  assert.equal(table.elements['select-pending'].disabled,true);
  table.elements.search.value='No match';table.elements.search.fire('input');
  assert.equal(table.elements.range.textContent,'0 companies');
  table.elements.search.value='';table.elements.search.fire('input');
  table.elements['status-filter'].value='failed';table.elements['status-filter'].fire('change');
  assert.equal(table.elements.rows.children[0].children[1].children[0].value,'Company 3');
  table.elements['status-filter'].value='all';table.elements['status-filter'].fire('change');
  assert.equal(table.elements.range.textContent,'1–10 of 25');
  assert.equal(table.elements.selection.textContent,'1 selected');
});

test('frame resize is stable and foreign window messages are ignored',()=>{
  const table=setup();table.render();
  const count=table.messages.filter(m=>m.type==='streamlit:setFrameHeight').length;
  for(let i=0;i<10;i++)table.listeners.resize();
  assert.equal(table.messages.filter(m=>m.type==='streamlit:setFrameHeight').length,count);
  table.listeners.message({source:{},data:{type:'streamlit:render',args:{}}});
  assert.equal(table.elements.rows.children.length,10);
});

test('batch lock disables editable fields and recipient checkboxes',()=>{
  const table=setup();table.render([],true);
  const row=table.elements.rows.children[0];
  assert.equal(row.children[0].children[0].children[0].disabled,true);
  assert.equal(row.children[1].children[0].disabled,true);
  assert.equal(table.elements['select-page'].disabled,true);
  assert.equal(table.elements['select-pending'].disabled,true);
});

test('select all pending uses the shared toolbar and never auto-selects sent rows',()=>{
  const table=setup();table.rows[1].needs_review=true;table.render();
  table.elements['select-pending'].fire('click');
  assert.equal(table.lastValue().selected_ids.length,23);
  assert.equal(table.lastValue().selected_ids.includes('0'),false);
  assert.equal(table.lastValue().selected_ids.includes('1'),false);
  assert.equal(table.elements['bulk-delete'].hidden,false);
});

test('clear selection undoes select all pending across pages and filters',()=>{
  const table=setup();table.render();
  table.elements['select-pending'].fire('click');
  assert.equal(table.lastValue().selected_ids.length,24);
  assert.equal(table.elements['clear-selection'].hidden,false);
  table.elements.next.fire('click');
  table.elements.search.value='Company 24';table.elements.search.fire('input');
  table.elements['clear-selection'].fire('click');
  assert.equal(table.lastValue().selected_ids.length,0);
  assert.equal(table.elements.selection.textContent,'0 selected');
  assert.equal(table.elements['bulk-delete'].hidden,true);
  assert.equal(table.elements['clear-selection'].hidden,true);
  assert.equal(table.elements.rows.children[0].classes.has('selected'),false);
  table.render([],true);
  assert.equal(table.elements['clear-selection'].disabled,true);
});

test('edit modal is prefilled; cancel does not change data or selection',()=>{
  const table=setup();table.render(['2']);
  table.elements.rows.children[0].children[5].children[0].children[0].fire('click');
  assert.equal(table.elements['edit-modal'].open,true);
  assert.equal(table.elements['edit-name'].value,'Company 0');
  assert.equal(table.elements['edit-status'].value,'sent');
  table.elements['edit-cancel'].fire('click');
  assert.equal(table.elements['edit-modal'].open,false);
  assert.equal(table.lastValue(),undefined);
  assert.equal(table.elements.selection.textContent,'1 selected');
});

test('edit submission emits all editable fields and preserves selected recipients',()=>{
  const table=setup();table.render(['2']);
  table.elements.rows.children[0].children[5].children[0].children[0].fire('click');
  table.elements['edit-name'].value='New Name';table.elements['edit-status'].value='pending';
  table.elements['edit-form'].fire('submit');
  const event=table.lastValue();assert.equal(event.action.type,'edit');assert.equal(event.action.id,'0');
  assert.equal(event.action.changes.company_name,'New Name');assert.equal(event.action.changes.status,'pending');
  assert.deepEqual([...event.selected_ids],['2']);
});

test('single and bulk deletion emit no destructive action until confirmed',()=>{
  const table=setup();table.render(['2','18']);
  table.elements.rows.children[0].children[5].children[0].children[1].fire('click');
  assert.equal(table.lastValue(),undefined);assert.match(table.elements['delete-description'].textContent,/Company 0/);
  table.elements['delete-cancel'].fire('click');assert.equal(table.lastValue(),undefined);
  table.elements['bulk-delete'].fire('click');assert.match(table.elements['delete-description'].textContent,/2 selected/);
  table.elements['delete-confirm'].fire('click');
  assert.equal(table.lastValue().action.type,'delete');assert.deepEqual([...table.lastValue().action.ids],['2','18']);
  assert.equal(table.lastValue().action.bulk,true);
});

test('standalone queue sends PUT, DELETE and bulk POST to the requested API routes',async()=>{
  const table=setup(true);const flush=()=>new Promise(setImmediate);await flush();
  assert.equal(table.elements.rows.children.length,10);
  table.elements.rows.children[0].children[5].children[0].children[0].fire('click');
  table.elements['edit-name'].value='API Updated';table.elements['edit-form'].fire('submit');await flush();
  const update=table.requests.find(r=>r.method==='PUT');assert.equal(update.url,'/api/companies/0');assert.equal(JSON.parse(update.body).company_name,'API Updated');
  table.elements.rows.children[0].children[5].children[0].children[1].fire('click');
  assert.equal(table.requests.filter(r=>r.method==='DELETE').length,0);
  table.elements['delete-confirm'].fire('click');await flush();
  assert.equal(table.requests.find(r=>r.method==='DELETE').url,'/api/companies/0');
  const checkbox=table.elements.rows.children[0].children[0].children[0].children[0];checkbox.checked=true;checkbox.fire('change');
  table.elements['bulk-delete'].fire('click');table.elements['delete-confirm'].fire('click');await flush();
  const bulk=table.requests.find(r=>r.method==='POST');assert.equal(bulk.url,'/api/companies/bulk-delete');assert.deepEqual(JSON.parse(bulk.body),{ids:['1']});
  assert.equal(table.elements.selection.textContent,'0 selected');
});
