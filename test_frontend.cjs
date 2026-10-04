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
    if (!nodes.has(selector)) nodes.set(selector,{value:selector === '#sort' ? 'updated_at' : '',content:'test-token',addEventListener(){},files:[],dataset:{}});
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
