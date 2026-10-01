const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, '../desktop.js'), 'utf8');
function setup(token = '', api = async () => ({url:'/desktop/example/view'})) {
  const elements = new Map(), listeners = new Map();
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, {
      value:'', hidden:true, textContent:'', disabled:false, contentWindow:{},
      focus(){this.focused=true;}, showModal(){this.open=true;},
      removeAttribute(name){delete this[name];},
    });
    return elements.get(id);
  };
  const window = {
    async financeConnectWorkspace(){},
    addEventListener(name, listener){listeners.set(name, listener);},
    async financeEnsureConversation(){ $('conversation-select').value='example'; return 'example'; },
  };
  const context = {token, api, $, window, location:{origin:'http://localhost'}, sessionVersion:0};
  vm.runInNewContext(source, context);
  return {$, window, listeners, context};
}
test('reconnect works without credentials or an authorization dialog', async () => {
  let calls=0;
  const {$} = setup('', async () => {calls++; return {url:'/desktop/example/view'};});
  await $('desktop-reconnect').onclick();
  assert.equal(calls, 1);
  assert.equal($('desktop-frame').hidden, false);
  assert.equal($('auth-dialog').open, undefined);
});
test('first conversation creation and reconnect share one real connection request', async () => {
  let finish, calls=0;
  const {$, window, listeners} = setup('fixture', () => {
    calls++;
    return new Promise(resolve => {finish=resolve;});
  });
  window.financeEnsureConversation = async () => {
    $('conversation-select').value='example';
    listeners.get('finance-conversation')();
    return 'example';
  };
  const pending = $('desktop-reconnect').onclick();
  await new Promise(setImmediate);
  assert.equal($('desktop-reconnect').disabled, true);
  assert.match($('desktop-reconnect').textContent, /正在连接/);
  finish({url:'/desktop/example/view'});
  await pending;
  assert.equal(calls, 1);
  assert.equal($('desktop-frame').src, '/desktop/example/view');
  assert.equal($('desktop-frame').hidden, false);
  assert.equal($('desktop-reconnect').disabled, false);
  listeners.get('message')({origin:'http://localhost', source:$('desktop-frame').contentWindow, data:{type:'finance-desktop-connected'}});
  assert.equal($('environment-connection').textContent, '已连接');
});
test('failed connection restores a retryable button and displays the cause', async () => {
  const {$} = setup('fixture', async () => {throw new Error('Docker unavailable');});
  await $('desktop-reconnect').onclick();
  assert.equal($('desktop-reconnect').disabled, false);
  assert.equal($('container-status').textContent, 'Docker unavailable');
});
test('a disconnected workspace ignores a late connection response', async () => {
  let finish;
  const {$, listeners} = setup('fixture', () => new Promise(resolve => {finish=resolve;}));
  const pending = $('desktop-reconnect').onclick();
  await new Promise(setImmediate);
  listeners.get('finance-session-reset')();
  finish({url:'/desktop/example/view'});
  await pending;
  assert.equal($('desktop-frame').hidden, true);
  assert.equal($('desktop-frame').src, undefined);
});
test('opening and switching conversations only inspect desktops without starting them', async () => {
  const methods=[];
  const {$, window, listeners} = setup('', async (url, method) => {
    methods.push(method);
    return {connected:false};
  });
  let creates=0;
  window.financeEnsureConversation = async () => {creates++;};
  await listeners.get('finance-session-ready')();
  assert.equal(creates,0);
  assert.equal(methods.length,0);
  $('conversation-select').value='example';
  await listeners.get('finance-session-ready')();
  assert.deepEqual(methods,['GET']);
  assert.equal($('desktop-frame').src,undefined);
  assert.equal($('desktop-reconnect').textContent,'启动桌面');
});
