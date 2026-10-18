// Run with Node.js: node test_frontend.cjs (no packages required).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname,'web/translations.json'),'utf8'));
const code = fs.readFileSync(path.join(__dirname,'web/app.js'),'utf8').replace(/\bboot\(\);\s*$/,'');
function runtime() {
  const nodes = new Map();
  const element = selector => {
    if (!nodes.has(selector)) nodes.set(selector,{value:selector === '#sort' ? 'updated_at' : '',content:'test-token',addEventListener(){},close(){this.open=false;},files:[],dataset:{}});
    return nodes.get(selector);
  };
  const context = vm.createContext({document:{querySelector:element,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){}},setTimeout,clearTimeout});
  vm.runInContext(code,context);
  context.catalog = catalog;
  vm.runInContext('translations = catalog;',context);
  return {context,nodes,run:source=>vm.runInContext(source,context)};
}
test('search matches company/title only, ignoring case, JD, notes and URLs',()=>{
  const {run,nodes}=runtime();
  run(`apps = [
    {id:'one',company:'BIL Demo',title:'Analyst',jd:'',notes:'',url:'',status:'已投递',applied_date:'2026-10-02',updated_at:'2'},
    {id:'two',company:'Northwind',title:'Engineer',jd:'BIL',notes:'BIL',url:'https://bil.example',status:'面试',applied_date:'2026-10-03',updated_at:'3'},
    {id:'three',company:'Acme',title:'Bilingual Analyst',jd:'',notes:'',url:'',status:'待投递',applied_date:'',updated_at:'1'}
  ];`);
  nodes.get('#search').value='  bIl  ';
  assert.equal(run('filtered().map(a=>a.id).join()'),'one,three');
  nodes.get('#status-filter').value='待投递';
  assert.equal(run('filtered().map(a=>a.id).join()'),'three');
  nodes.get('#date-from').value='2026-10-01';
  assert.equal(run('filtered().length'),0);
});
test('English display keeps persisted Chinese statuses and historical content intact',()=>{
  const {run}=runtime(); run("language = 'en';");
  assert.equal(run("t('面试')"),'Interview');
  assert.match(run("statusOptions('面试')"), /value="面试" selected>Interview/);
  assert.equal(run("historyEvent('更新：状态、备注；归档 2 份新材料')"),'Updated: Status, Notes; Archived 2 new documents');
  assert.equal(run("t('显示 {count} / {total} 条投递',{count:1,total:3})"),'Showing 1 of 3 applications');
  run("language = 'zh-CN';");
  assert.equal(run("t('面试')"),'面试');
});
test('every static interface label has both language variants',()=>{
  const html=fs.readFileSync(path.join(__dirname,'web/index.html'),'utf8');
  for(const [,key] of html.matchAll(/data-(?:i18n|placeholder|aria)="([^"]+)"/g)) {
    assert.ok(catalog[key],`Missing translation: ${key}`);
    if(typeof catalog[key]==='object') {assert.ok(catalog[key].en);assert.ok(catalog[key]['zh-CN']);}
  }
});
test('English language settings contain no mixed-language heading',()=>{
  const {run}=runtime(); run("language = 'en';");
  assert.equal(run("t('界面语言')"),'Language');
  run("language = 'zh-CN';");
  assert.equal(run("t('界面语言')"),'界面语言');
});
test('dates validate Gregorian days without timezone or OS-locale dependencies',()=>{
  const {run}=runtime();
  for (const value of ['2024-02-29','2026-10-04','2000-02-29','0001-01-01','9999-12-31']) {
    assert.equal(run(`ArchiveDates.valid('${value}')`),true,value);
  }
  for (const value of ['2026-02-29','1900-02-29','2026-04-31','2026-13-01','2026-1-1','0000-01-01','', '2026/10/04']) {
    assert.equal(run(`ArchiveDates.valid('${value}')`),false,value);
  }
  const html=fs.readFileSync(path.join(__dirname,'web/index.html'),'utf8');
  assert.equal((html.match(/ data-date/g)||[]).length,4);
  assert.ok(!html.includes('type="date"'));
});
test('CV dropdown keeps a valid selection, escapes names and clears removed choices',()=>{
  const {run,nodes}=runtime();
  run("library = [{id:'cv1',label:'English <CV>',name:'CV & profile.txt',created_at:'2026-10-18T12:00:00Z'}];");
  run("$('#cv-library-select').value = 'cv1';");
  run('renderLibraryOptions()');
  assert.equal(nodes.get('#cv-library-select').value,'cv1');
  assert.match(nodes.get('#cv-library-select').innerHTML,/English &lt;CV&gt;/);
  assert.match(nodes.get('#cv-library-select').innerHTML,/CV &amp; profile.txt/);
  run('library = []; renderLibraryOptions()');
  assert.equal(nodes.get('#cv-library-select').value,'');
});
test('saving with a library CV sends its ID without requiring a new file selection',async()=>{
  const {run,context}=runtime();
  context.testElements=Object.fromEntries(['company','title','url','jd','applied_date','status','notes','new_letter','submitted_date','document_label','cv_library_id'].map(k=>[k,{value:k==='cv_library_id'?'cv1':k==='company'?'Acme':k==='title'?'Analyst':''}]));
  run("globalThis.captured = null; api = async(path,payload)=>{globalThis.captured={path,payload};return {id:'app1'};}; reload = async()=>{};");
  await run("$('#application-form').onsubmit({preventDefault(){},target:{elements:testElements}})");
  assert.equal(context.captured.payload.cv_library_id,'cv1');
  assert.equal(context.captured.payload.uploads.length,0);
  assert.equal(context.captured.path,'/api/applications');
});

function uploadRuntime(names) {
  const state=runtime();
  state.context.selectedFiles=names.map(name=>({name,size:10}));
  state.run(`$('#library-file').files=selectedFiles;
    $('#library-editor').open=true; $('#editor').open=true;
    $('#cv-library-select').value='existing';
    library=[{id:'existing',label:'Previous',name:'Previous.pdf',created_at:'2026-10-18'}];
    renderLibrary=()=>renderLibraryOptions(); toast=message=>globalThis.notice=message;
    file64=async file=>'test-base64';
    globalThis.calls=[];
    api=async(path,payload)=>{calls.push({path,payload});return {id:payload.name,label:payload.label,name:payload.name,created_at:'2026-10-18'};};
    $('#library-file').onchange();`);
  return state;
}
const submitUploads=state=>state.run("$('#library-upload-form').onsubmit({preventDefault(){}})");

test('CV library multi-select uploads every file with its own label and preserves application choice',async()=>{
  const state=uploadRuntime(['English.pdf','Chinese.docx']);
  state.run("$('#library-upload-list').oninput({target:{dataset:{cvLabel:'1'},value:'中文版 · 数据岗'}});");
  await submitUploads(state);
  assert.deepEqual(Array.from(state.context.calls,c=>c.payload.name),['English.pdf','Chinese.docx']);
  assert.equal(state.context.calls[1].payload.label,'中文版 · 数据岗');
  assert.equal(state.nodes.get('#cv-library-select').value,'existing');
  assert.equal(state.nodes.get('#library-editor').open,false);
  assert.match(state.context.notice,/2/);
  const html=fs.readFileSync(path.join(__dirname,'web/index.html'),'utf8');
  assert.match(html,/<input id="library-file"[^>]* multiple/);
});

test('partial failure continues remaining uploads and retries only failed files',async()=>{
  const state=uploadRuntime(['first.pdf','failed.pdf','third.pdf']);
  state.run(`let failOnce=true;
    api=async(path,payload)=>{calls.push({path,payload});
      if(payload.name==='failed.pdf' && failOnce){failOnce=false;throw Error('Temporary failure');}
      return {id:payload.name,label:payload.label,name:payload.name,created_at:'2026-10-18'};
    };`);
  await submitUploads(state);
  assert.equal(state.context.calls.length,3);
  assert.equal(state.nodes.get('#library-editor').open,true);
  assert.match(state.nodes.get('#library-upload-message').textContent,/已保存 2 份，失败 1 份/);
  assert.match(state.nodes.get('#library-upload-list').innerHTML,/Temporary failure/);
  assert.equal(state.nodes.get('#save-library-cv').textContent,'重试失败项');
  assert.equal(state.nodes.get('#library-file').disabled,false);
  await submitUploads(state);
  assert.deepEqual(Array.from(state.context.calls,c=>c.payload.name),['first.pdf','failed.pdf','third.pdf','failed.pdf']);
  assert.equal(state.run('library.length'),4);
  assert.equal(state.nodes.get('#library-editor').open,false);
  assert.equal(state.nodes.get('#cv-library-select').value,'existing');
});

test('one library upload still selects the saved CV automatically and escapes queue content',async()=>{
  const state=uploadRuntime(['CV <English>.pdf']);
  assert.match(state.nodes.get('#library-upload-list').innerHTML,/CV &lt;English&gt;.pdf/);
  state.run("language='en'; renderLibraryUploads();");
  assert.match(state.nodes.get('#library-upload-list').innerHTML,/Waiting to upload/);
  await submitUploads(state);
  assert.equal(state.nodes.get('#cv-library-select').value,'CV <English>.pdf');
  assert.match(state.context.notice,/Added 1 CVs/);
});

test('batch upload blocks duplicate submits and file changes until it completes',async()=>{
  const state=uploadRuntime(['one.pdf','two.pdf']);
  state.run("file64=()=>new Promise(resolve=>globalThis.finishRead=resolve);");
  const upload=submitUploads(state);
  assert.equal(state.nodes.get('#library-file').disabled,true);
  assert.equal(state.nodes.get('#close-library-editor').disabled,true);
  await submitUploads(state);
  assert.equal(state.context.calls.length,0);
  // Let the second file read normally, then finish the first pending read.
  state.run("file64=async()=>'test-base64'; finishRead('test-base64');");
  await upload;
  assert.equal(state.context.calls.length,2);
  assert.equal(state.nodes.get('#library-file').disabled,false);
  assert.equal(state.nodes.get('#close-library-editor').disabled,false);
});
