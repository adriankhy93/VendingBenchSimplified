import {randomUUID} from 'node:crypto';
import {Controller} from './vending-controller.mjs';

/** One HTTP request per invocation; a retry is a subsequent invocation. */
export class VendingClient {
  constructor({baseUrl, saved, persist = () => {}, fetchImpl = fetch, timeoutMs = 15000}) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.controller = new Controller(saved);
    this.persist = persist; this.fetch = fetchImpl; this.timeoutMs = timeoutMs;
    this.queue = Promise.resolve();
  }
  execute(action, payload = {}, signal) {
    const task = this.queue.then(() => this.perform(action, payload, signal));
    this.queue = task.catch(() => {});
    return task;
  }
  async save() { await this.persist(this.controller.snapshot()); }
  async perform(action, payload, signal) {
    const c = this.controller, s = c.state;
    try { c.validate(action, payload); }
    catch (error) { return {blocked: true, message: error.message, controller: c.view()}; }
    let pending = s.pending;
    if (pending && (action !== pending.action || Object.keys(payload).length !== Object.keys(pending.payload).length ||
        Object.entries(pending.payload).some(([key, value]) => payload[key] !== value))) {
      return {blocked: true, message: 'Retry exactly the pending request.', controller: c.view()};
    }
    if (!pending) pending = s.pending = {action, payload: structuredClone(payload), key: randomUUID(), attempts: 0, phase: s.phase};
    pending.attempts += 1;
    if (action === 'create') s.phase = 'creating';
    // Save the key before sending: recovery never invents a replacement request.
    await this.save();
    const method = action === 'create' ? 'POST' : ['status','result'].includes(action) ? 'GET' : action === 'delete' ? 'DELETE' : 'POST';
    const path = action === 'create' ? '/env' : `/env/${s.envId}${action === 'delete' ? '' : `/${action}`}`;
    const request = {action, payload: structuredClone(payload), env_id: s.envId, idempotency_key: pending.key};
    let response, status;
    try {
      const res = await this.fetch(this.baseUrl + path, {
        method, headers: {'Content-Type': 'application/json', 'Idempotency-Key': pending.key},
        ...(method === 'POST' ? {body: JSON.stringify(payload)} : {}),
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(this.timeoutMs)]) : AbortSignal.timeout(this.timeoutMs),
      });
      status = res.status;
      response = status === 204 ? {} : await res.json();
      if (!response || typeof response !== 'object' || Array.isArray(response)) throw new Error('Invalid API response');
      if (status < 300 && action === 'create' && !/^env_[a-f0-9]+$/.test(response.env_id || '')) throw new Error('Missing environment ID');
      if (status < 300 && !['create','status','result','delete'].includes(action) && !response.action_id) throw new Error('Missing action result');
    } catch (error) {
      s.phase = action === 'create' || pending.attempts >= 2 ? 'halted' : 'retry';
      s.uncertain = true;
      await this.save();
      return {request, transport_error: String(error.message), controller: c.view(),
        message: s.phase === 'retry' ? 'Outcome uncertain. Retry the exact permitted request once with its saved idempotency key.' : 'Outcome uncertain; halted without issuing a replacement request.'};
    }
    s.pending = null; s.uncertain = false; s.phase = pending.phase;
    c.apply(action, payload, response, status);
    if (status >= 500 && s.phase !== 'terminal') s.phase = 'resume_status';
    await this.save();
    return {request, response, http_status: status, controller: c.view()};
  }
}
