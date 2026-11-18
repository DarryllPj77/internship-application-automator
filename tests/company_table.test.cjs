// Offline behavior tests for the table's Streamlit bridge and navigation.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../ui/company_table/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];

function setup() {
  class Element {
    constructor(tag='div') {this.tag=tag;this.children=[];this.listeners={};this.value='';this.checked=false;this.disabled=false;this.classes=new Set();this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name)}}
    append(...children) {this.children.push(...children)}
    replaceChildren(...children) {this.children=children}
    setAttribute(name,value) {this[name]=value}
    addEventListener(name,callback) {this.listeners[name]=callback}
    fire(name) {this.listeners[name]?.()}
  }
  const elements=Object.fromEntries(['search','selection','rows','range','previous','next','select-page','page-size'].map(id=>[id,new Element()]));
  const messages=[],listeners={};
  const parent={postMessage:message=>messages.push(message)};
  const document={getElementById:id=>elements[id],createElement:tag=>new Element(tag),createTextNode:text=>({text}),body:{getBoundingClientRect:()=>({height:420})},fonts:{ready:Promise.resolve()}};
  const window={parent,addEventListener:(name,fn)=>listeners[name]=fn};
  vm.runInNewContext(script,{window,document,requestAnimationFrame:fn=>fn()});
  const rows=Array.from({length:25},(_,i)=>({id:String(i),company_name:`Company ${i}`,hr_email:`hr${i}@acme.com`,contact_person:'HR',relevant_skills:'Python',status:i===0?'sent':'pending'}));
  function render(selected_ids=[],disabled=false) {listeners.message({source:parent,data:{type:'streamlit:render',args:{rows,selected_ids,disabled,revision:'v1'}}})}
  const lastValue=()=>messages.filter(m=>m.type==='streamlit:setComponentValue').at(-1)?.value;
  return {elements,messages,listeners,render,lastValue,rows};
}

test('sent rows begin unchecked; explicit selection survives pagination and search',()=>{
  const table=setup();table.render();
  const checkbox=table.elements.rows.children[0].children[0].children[0].children[0];
  assert.equal(checkbox.checked,false);checkbox.checked=true;checkbox.fire('change');
  assert.deepEqual([...table.lastValue().selected_ids],['0']);
  table.elements.next.fire('click');assert.equal(table.elements.range.textContent,'11–20 of 25');
  table.elements.search.value='Company 24';table.elements.search.fire('input');
  assert.equal(table.elements.range.textContent,'1–1 of 1');
  assert.equal(table.elements.selection.textContent,'1 selected');
});

test('select visible page affects only its rows',()=>{
  const table=setup();table.render();table.elements.next.fire('click');
  table.elements['select-page'].checked=true;table.elements['select-page'].fire('change');
  assert.equal(table.lastValue().selected_ids.length,10);
  assert.equal(table.lastValue().selected_ids[0],'10');
  assert.equal(table.lastValue().selected_ids[9],'19');
});

test('inline edits emit the revision and edited field for Python validation',()=>{
  const table=setup();table.render();
  const field=table.elements.rows.children[0].children[2].children[0];
  field.value='new@acme.com';field.fire('change');
  assert.equal(table.lastValue().revision,'v1');
  assert.equal(table.lastValue().rows[0].hr_email,'new@acme.com');
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
});
