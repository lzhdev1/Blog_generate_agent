// From front_L: npm run build, then PLAYWRIGHT_MODULE=<installed playwright> node tests/revision.browser.cjs.
// BROWSER_EXECUTABLE is optional. Docker must have the project's backend image locally.
const assert = require('node:assert/strict')
const { execFileSync, spawn } = require('node:child_process')
const { randomBytes } = require('node:crypto')
const { once } = require('node:events')
const net = require('node:net')
const path = require('node:path')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')

const frontend = path.resolve(__dirname, '..')
const backend = path.resolve(frontend, '../backend_L')
const name = 'folio-browser-' + randomBytes(8).toString('hex')
const docker = args => execFileSync('docker', args, { windowsHide:true, encoding:'utf8' })
const mount = (source, target) => ['--mount', `type=bind,source=${source},target=${target},readonly`]
// Forward browser TCP to the container loopback. The app, worker and mock model have no network interface to the outside.
const bridge = `import socket, sys, threading
s = socket.create_connection(('127.0.0.1', 8181))
def upload():
    while chunk := sys.stdin.buffer.read1(65536):
        s.sendall(chunk)
    s.shutdown(socket.SHUT_WR)
threading.Thread(target=upload, daemon=True).start()
while chunk := s.recv(65536):
    sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()`

async function run() {
  const peers = new Set()
  let relay, browser, started = false
  try {
    docker(['run','--rm','--pull','never','--detach','--name',name,'--network','none','-w','/tmp/folio-browser','--tmpfs','/tmp/folio-browser',
      ...mount(path.join(backend,'src'),'/app/src'), ...mount(path.join(backend,'config'),'/app/config'),
      ...mount(path.join(frontend,'dist'),'/app/dist'), ...mount(path.join(__dirname,'fixtures'),'/fixtures'),
      '-e','APP_ENV=test','-e','PYTHONPATH=/app','-e','PYTHONDONTWRITEBYTECODE=1',
      '-e','DB_URL=sqlite:////tmp/folio-browser/case.db','-e','IMAGE_SAVE_DIR=/tmp/folio-browser/images',
      '-e','LLM_API_KEY=offline','-e','LLM_MODEL=offline','-e','LLM_BASE_URL=http://127.0.0.1:17871/v1',
      '-e','JWT_SECRET=offline-browser-only','-e','AGENT_MAX_WORKERS=1','-e','AGENT_QUEUE_POLL_SECONDS=0.2',
      process.env.BACKEND_IMAGE || 'blog-agent-l-backendl:latest','python','/fixtures/revision_app.py'])
    started = true
    for (let i=0; i<45; i++) {
      const waiting=docker(['exec',name,'python','-c',"import socket; print(socket.socket().connect_ex(('127.0.0.1',8181)))"]).trim()
      if (waiting==='0') break
      if (i === 44) throw Error('Fixture did not start')
      await new Promise(resolve=>setTimeout(resolve,500))
    }
    relay = net.createServer(socket=>{
      const tunnel=spawn('docker',['exec','-i',name,'python','-u','-c',bridge],{ windowsHide:true,stdio:['pipe','pipe','ignore'] })
      peers.add(tunnel)
      tunnel.stdin.on('error',()=>socket.destroy())
      tunnel.on('exit',()=>{ peers.delete(tunnel); socket.destroy() })
      socket.on('error',()=>tunnel.kill())
      socket.on('close',()=>tunnel.kill())
      socket.pipe(tunnel.stdin); tunnel.stdout.pipe(socket)
    })
    relay.listen(0,'127.0.0.1')
    await once(relay,'listening')
    const origin='http://127.0.0.1:' + relay.address().port
    browser=await chromium.launch({headless:true, executablePath:process.env.BROWSER_EXECUTABLE || undefined})
    const context=await browser.newContext({locale:'zh-CN'})
    const login=await context.request.post(origin+'/api/v1/auth/login',{data:{account:'WriterDemo',password:'WriterDemo1!'}})
    assert.equal(login.status(),200)
    const session=await login.json()
    await context.addInitScript(session=>{
      localStorage.setItem('blog-agent-token',session.access_token)
      localStorage.setItem('blog-agent-user',JSON.stringify(session.user))
      localStorage.setItem('blog-agent-lang','zh')
    },session)
    const page=await context.newPage()
    const errors=[]
    page.on('pageerror',error=>errors.push(error.message))
    page.on('dialog',dialog=>dialog.accept())
    page.setDefaultTimeout(45000)
    const button=(name)=>page.getByRole('button',{name,exact:true})
    await page.goto(origin+'/blog/1')
    await page.getByRole('button',{name:/发布设置/}).click()
    await page.getByRole('dialog').locator('.el-switch').first().click()
    const firstPublish=page.waitForResponse(r=>r.url().endsWith('/visibility') && r.request().method()==='PUT')
    await page.getByRole('dialog').getByRole('button',{name:'保存'}).click()
    const refused=await firstPublish
    assert.equal(refused.status(),409)
    assert.equal((await refused.json()).detail.code,'review_required')
    await page.getByRole('link',{name:'去核对正文并送审'}).click()
    const text=await page.getByLabel('Markdown 原文').inputValue()
    // A legacy author may submit the unchanged original for its first policy-compliant review.
    await page.getByLabel('补查资料（选填）').fill('巷口石板路')
    const saved=page.waitForResponse(r=>r.url().endsWith('/revision') && r.request().method()==='PUT')
    await button('保存草稿').click()
    const draft=await (await saved).json()
    assert.equal(draft.content,text); assert.equal(draft.source_query,'巷口石板路')
    assert.match(draft.base_revision,/^[a-f0-9]{64}$/)
    // The creative essay can be reviewed without outside evidence. No search provider is configured in this fixture.
    await page.getByLabel('补查资料（选填）').fill('')
    await button('保存草稿').click()
    await page.getByText('已保存 · 修订 2').waitFor()
    // One failed progress read must recover automatically without a second chargeable submission.
    let interrupted=0
    await page.route('**/api/v1/task/1/revision',route=>{
      if (route.request().method()==='GET' && interrupted++===0) return route.fulfill({status:503,json:{detail:'temporary disconnect'}})
      return route.continue()
    })
    const submitted=page.waitForResponse(r=>r.url().endsWith('/revision/review'))
    await button('提交审核（1 点）').click()
    const request=await submitted
    assert.equal(request.status(),200); assert.equal(request.request().headers()['idempotency-key'].length,32)
    await page.getByText('进度连接中断，正在自动重试。').waitFor()
    await button('将修订设为当前正文').click({timeout:75000})
    assert.ok(interrupted >= 2)
    await page.getByRole('button',{name:/发布设置/}).click()
    await page.getByRole('dialog').locator('.el-switch').first().click()
    const final=page.waitForResponse(r=>r.url().endsWith('/visibility') && r.request().method()==='PUT')
    await page.getByRole('dialog').getByRole('button',{name:'保存'}).click()
    const published=await final
    assert.equal(published.status(),200)
    assert.equal((await published.json()).is_public,true)
    const headers={Authorization:'Bearer '+session.access_token}
    const remaining=await context.request.get(origin+'/api/v1/auth/quota',{headers})
    const budget=await remaining.json()
    assert.equal(budget.daily_limit-budget.remaining,1)
    const publicRead=await context.request.get(origin+'/api/v1/articles/1')
    assert.equal(publicRead.status(),200); assert.equal((await publicRead.json()).content,text)
    assert.deepEqual(errors,[])
    console.log('PASS: legacy review gate, unchanged private draft, source query, real queue/worker, simulated model, automatic reconnect, apply, publish, public read, exactly one credit.')
  } finally {
    await browser?.close()
    relay?.close()
    for (const peer of peers) peer.kill()
    if (started) docker(['rm','-f',name])
  }
}
run().catch(error=>{console.error(error);process.exitCode=1})
