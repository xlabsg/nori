const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../i18n.js'), 'utf8');
function setup({saved, query='', browser='en-US', blocked=false}={}) {
  const storage = new Map(saved ? [['nori-language', saved]] : []);
  const nodes = [{textContent:'  任务与提醒  ', parentElement:{tagName:'SPAN'}}];
  const attributes = new Map([['placeholder','交代一项工作，或让 Nori 继续跟进…']]);
  const field = {hasAttribute:key=>attributes.has(key),getAttribute:key=>attributes.get(key),setAttribute:(key,value)=>attributes.set(key,value)};
  const select = {};
  const document = {documentElement:{},body:{},title:'Nori · 对话工作区',
    createTreeWalker:()=>{let index=0;return {nextNode:()=>nodes[index++]};},
    querySelectorAll:()=>[field],getElementById:()=>select};
  const location = {search:query,href:'http://localhost/'+query,assign:url=>{location.assigned=String(url);}};
  const window = {};
  vm.runInNewContext(source,{window,document,location,navigator:{language:browser},
    URL,URLSearchParams,NodeFilter:{SHOW_TEXT:4},
    localStorage:{getItem:key=>{if(blocked)throw Error('blocked');return storage.get(key);},
      setItem:(key,value)=>{if(blocked)throw Error('blocked');storage.set(key,value);}}});
  return {window,document,nodes,attributes,select,storage,location};
}
test('English localizes static copy, accessibility attributes and dynamic states',()=>{
  const c=setup();
  assert.equal(c.document.documentElement.lang,'en');
  assert.equal(c.document.title,'Nori · Chat workspace');
  assert.equal(c.nodes[0].textContent,'  Tasks & reminders  ');
  assert.equal(c.attributes.get('placeholder'),'Describe a task, or ask Nori to follow up…');
  assert.equal(c.window.noriI18n.t('重试中'),'Retrying');
  assert.equal(c.window.noriI18n.t('这是用户自己的内容'),'这是用户自己的内容');
});
test('saved language wins over browser; explicit supported query wins over saved',()=>{
  assert.equal(setup({saved:'zh-CN'}).window.noriI18n.language,'zh-CN');
  assert.equal(setup({saved:'zh-CN',query:'?lang=en'}).window.noriI18n.language,'en');
  assert.equal(setup({query:'?lang=invalid',browser:'zh-TW'}).window.noriI18n.language,'zh-CN');
});
test('switch persists language and preserves other URL parameters',()=>{
  const c=setup({query:'?demo=1'});
  c.select.value='zh-CN';c.select.onchange();
  assert.equal(c.storage.get('nori-language'),'zh-CN');
  const url=new URL(c.location.assigned);
  assert.equal(url.searchParams.get('lang'),'zh-CN');
  assert.equal(url.searchParams.get('demo'),'1');
});
test('blocked browser storage does not break rendering or language switching',()=>{
  const c=setup({blocked:true});
  c.select.value='zh-CN';c.select.onchange();
  assert(c.location.assigned.includes('lang=zh-CN'));
});
