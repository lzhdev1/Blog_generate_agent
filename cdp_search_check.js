// CDP 验证：搜索下拉在真实像素中的显示
const http = require('http');
const fs = require('fs');

function getJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => resolve(JSON.parse(d)));
    }).on('error', reject);
  });
}

async function main() {
  const targets = await getJson('http://127.0.0.1:9224/json');
  const page = targets.find(t => t.type === 'page');
  if (!page) { console.log('NO_PAGE_TARGET'); return; }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const mid = ++id;
      pending.set(mid, { resolve, reject });
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
  }
  ws.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
    }
  };
  await new Promise(r => ws.onopen = r);

  await send('Page.navigate', { url: 'http://localhost:5173/' });
  await new Promise(r => setTimeout(r, 4000));

  // 模拟输入：设置 value + 触发 input 事件
  const setVal = `(() => {
    const inp = document.querySelector('.search-input');
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(inp, '和平');
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    return 'input set';
  })()`;
  await send('Runtime.evaluate', { expression: setVal });
  await new Promise(r => setTimeout(r, 1500));

  // 检查下拉状态
  const check = await send('Runtime.evaluate', {
    expression: `(() => {
      const dd = document.querySelector('.search-dropdown');
      if (!dd) return {dd: false};
      const r = dd.getBoundingClientRect();
      return { dd: true, rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}, items: document.querySelectorAll('.search-result-item').length };
    })()`,
    returnByValue: true
  });
  console.log('CHECK:', JSON.stringify(check.result.value));

  // 真实截图
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync('D:/AMySpace/AMe/Blog_generate_agent/search_cdp.png', Buffer.from(shot.data, 'base64'));
  console.log('screenshot saved');
  ws.close();
}

main().catch(e => { console.error('ERR', e.message); process.exit(1); });
