import assert from 'node:assert/strict'
import test from 'node:test'
import { createGenerationJournal, admissionWasRejected, hasReceipt } from '../src/utils/generationJournal.js'
import { taskPath } from '../src/utils/taskWorkflow.js'

test('restore the original key and parameters only for the same author and draft', () => {
  const stored = new Map()
  const storage = () => ({
    getItem: key => stored.get(key), setItem: (key,value) => stored.set(key,value),
    removeItem: key => stored.delete(key)
  })
  const journal = createGenerationJournal(new Map(), storage)
  const record = { id:'attempt-1', endpoint:'submit-title-config', data:{title:'标题',need_image:true} }
  journal.save(7, 18, record)
  const afterReload = createGenerationJournal(new Map(), storage)
  assert.deepEqual(afterReload.read(7,18), record)
  assert.equal(afterReload.read(8,18), null)
  assert.equal(afterReload.read(7,19), null)
  afterReload.save(7,18,null)
  assert.equal(createGenerationJournal(new Map(), storage).read(7,18), null)
})

test('retain uncertain deliveries through connection, gateway and database errors', () => {
  for (const status of [undefined,408,500,502,503,504]) {
    assert.equal(admissionWasRejected({response:{status}}), false)
  }
  for (const status of [400,401,403,409,422,429]) {
    assert.equal(admissionWasRejected({response:{status}}), true)
  }
  assert.equal(admissionWasRejected({response:{status:503,data:{detail:{code:'queue_full'}}}}), true)
  assert.equal(admissionWasRejected({response:{status:503,data:{detail:{code:'site_daily_limit'}}}}), true)
})

test('state changes from another tab never acknowledge this request', () => {
  const record = {id:'original-key'}
  assert.equal(hasReceipt(record,{status:'completed',updated_at:'newer'}), false)
  assert.equal(hasReceipt(record,{accepted_request_key:'different-key'}), false)
  assert.equal(hasReceipt(record,{accepted_request_key:record.id}), true)
})

test('failure links use the reported stage and support older drafts without job metadata', () => {
  const failed = {id:3,status:'failed',selected_title:'之前的标题',outline_confirmed:true}
  for (const [stage, suffix] of [['title','titles'],['outline','outline'],['content','generating']]) {
    assert.equal(taskPath({...failed,job:{stage}}),'/task/3/'+suffix)
  }
  assert.equal(taskPath(failed),'/task/3/generating')
  assert.equal(taskPath({...failed,outline_confirmed:false}),'/task/3/outline')
  assert.equal(taskPath({id:3,status:'failed'}),'/task/3/generating')
})
