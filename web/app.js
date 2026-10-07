'use strict';
// Dates remain ISO strings in records; the picker never uses the OS locale.
const ArchiveDates = (() => {
  let input = null, year = 0, month = 0;
  const valid = value => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return false;
    const date = new Date(value + 'T12:00:00Z');
    return !Number.isNaN(date.getTime()) && date.toISOString().slice(0,10) === value;
  };
  function calendarDate(y,m,day) {
    const date = new Date(0); date.setUTCFullYear(y,m,day); return date;
  }
  function validate(field) {
    const error = field.value && !valid(field.value) ? t('请使用 YYYY-MM-DD 格式填写有效日期。') : '';
    field.setCustomValidity(error); field.setAttribute('aria-invalid', String(!!error));
    const hint = field.closest('.date-field').querySelector('.date-error');
    hint.textContent = error; hint.hidden = !error; return !error;
  }
  function render() {
    const first = calendarDate(year,month,1);
    $('#date-picker-title').textContent = new Intl.DateTimeFormat(language === 'en' ? 'en-GB' : 'zh-CN', {year:'numeric',month:'long',timeZone:'UTC'}).format(first);
    $('#date-prev').setAttribute('aria-label',t('上个月')); $('#date-next').setAttribute('aria-label',t('下个月'));
    $('#date-prev').disabled = year === 1 && month === 0; $('#date-next').disabled = year === 9999 && month === 11;
    $('#date-today').textContent = t('今天'); $('#date-clear').textContent = t('清空'); $('#date-close').textContent = t('取消');
    const weekdays = language === 'en' ? ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'] : ['一','二','三','四','五','六','日'];
    $('#date-weekdays').replaceChildren(...weekdays.map(day => {const span = document.createElement('span'); span.textContent = day; return span;}));
    const grid = $('#date-days'); grid.replaceChildren();
    for (let i = 0; i < (first.getUTCDay()+6)%7; i++) grid.append(document.createElement('span'));
    const count = calendarDate(year,month+1,0).getUTCDate();
    for (let day = 1; day <= count; day++) {
      const date = calendarDate(year,month,day), value = date.toISOString().slice(0,10), button = document.createElement('button');
      button.type = 'button'; button.textContent = day; button.dataset.day = value;
      button.setAttribute('aria-label', new Intl.DateTimeFormat(language === 'en' ? 'en-GB' : 'zh-CN', {dateStyle:'full',timeZone:'UTC'}).format(date));
      button.setAttribute('aria-pressed', String(value === input.value));
      if (value === today()) button.setAttribute('aria-current','date');
      button.onclick = () => choose(value); grid.append(button);
    }
  }
  function choose(value) {
    input.value = value; validate(input);
    input.dispatchEvent(new Event('input',{bubbles:true})); input.dispatchEvent(new Event('change',{bubbles:true}));
    $('#date-picker').close(); input.focus();
  }
  function open(field) {
    input = field;
    const date = new Date((valid(field.value) ? field.value : today())+'T12:00:00Z');
    year = date.getUTCFullYear(); month = date.getUTCMonth(); render(); $('#date-picker').showModal();
    ($('#date-days [aria-pressed="true"]') || $('#date-days [aria-current="date"]') || $('#date-days button')).focus();
  }
  function refresh() {
    document.querySelectorAll('[data-date]').forEach(field => {
      field.placeholder = language === 'en' ? 'YYYY-MM-DD' : '年-月-日';
      field.closest('.date-field').querySelector('.date-open').setAttribute('aria-label',t('选择日期')+' · '+(field.getAttribute('aria-label') || field.labels[0]?.querySelector('[data-i18n]')?.textContent.trim()));
      validate(field);
    });
    if ($('#date-picker').open) render();
  }
  function init() {
    document.querySelectorAll('[data-date]').forEach((field,index) => {
      const wrapper = document.createElement('span'); wrapper.className = 'date-field'; field.replaceWith(wrapper); wrapper.append(field);
      const control = document.createElement('span'); control.className = 'date-control'; wrapper.append(control); control.append(field);
      const button = document.createElement('button'); button.type = 'button'; button.className = 'date-open'; button.textContent = '▦'; button.setAttribute('aria-haspopup','dialog'); button.setAttribute('aria-controls','date-picker'); control.append(button);
      const hint = document.createElement('small'); hint.className = 'date-error'; hint.id = 'date-error-'+index; hint.hidden = true; hint.setAttribute('role','status'); wrapper.append(hint);
      field.setAttribute('aria-describedby',hint.id);
      button.onclick = event => {event.preventDefault(); open(field);};
      field.addEventListener('input',() => validate(field));
      field.addEventListener('keydown',event => {if (event.altKey && event.key === 'ArrowDown') {event.preventDefault(); open(field);}});
    });
    for (const [id,offset] of [['date-prev',-1],['date-next',1]]) $('#'+id).onclick = () => {const date = calendarDate(year,month+offset,1); year = date.getUTCFullYear(); month = date.getUTCMonth(); render();};
    $('#date-today').onclick = () => choose(today()); $('#date-clear').onclick = () => choose('');
    $('#date-close').onclick = () => {$('#date-picker').close(); input.focus();};
    $('#application-form').addEventListener('reset',() => queueMicrotask(refresh)); refresh();
  }
  return {valid,init,refresh};
})();

'use strict';
const $ = s => document.querySelector(s);
const token = $('meta[name=archive-token]').content;
// Persisted status values stay compatible with existing records and backups.
const statuses = ['待投递','已投递','初筛','笔试','面试','Offer','已拒绝','已撤回'];
const fields = ['company','title','url','jd','applied_date','status','notes'];
let apps = [], mails = [], selected = null, editing = null, mailSelected = null;
let nextPage = '', view = 'applications', desktop = false, language = 'zh-CN', translations = {};
let selectedRecord = null, detailRequest = 0, editorSnapshot = '', editorSession = 0, saving = false;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function t(key, values = {}) {
  const entry = translations[key];
  const phrase = entry ? (typeof entry === 'string' ? (language === 'en' ? entry : key) : entry[language]) : key;
  return phrase.replace(/\{(\w+)\}/g, (match, name) => String(values[name] ?? match));
}
const today = () => {const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
const stamp = s => s ? new Date(s).toLocaleString(language === 'en' ? 'en-GB' : 'zh-CN') : '';
function toast(message) {$('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('#toast').hidden = true, 6500);}
async function api(path, data) {
  let response;
  try {response = await fetch(path, {headers:{'X-Archive-Token':token,...(data === undefined ? {} : {'Content-Type':'application/json'})},...(data === undefined ? {} : {method:'POST',body:JSON.stringify(data)})});}
  catch {throw Error(t('无法连接本地服务，请重新打开应用。'));}
  const payload = await response.json();
  if (!response.ok) throw Error(t(payload.error || '请求失败'));
  return payload;
}
function action(el, fn) {el.addEventListener('click', async () => {el.disabled = true; try {await fn();} catch(e) {toast(e.message);} finally {el.disabled = false;}});}
function confirmAction(message, acceptLabel = '继续') {
  const dialog = $('#confirmation');
  $('#confirm-message').textContent = message;
  $('#confirm-cancel').textContent = t('取消');
  $('#confirm-ok').textContent = t(acceptLabel);
  $('#confirm-ok').classList.toggle('danger',acceptLabel === '确认删除');
  return new Promise(resolve => {
    const finish = answer => {dialog.close(); resolve(answer);};
    $('#confirm-cancel').onclick = () => finish(false);
    $('#confirm-ok').onclick = () => finish(true);
    dialog.oncancel = event => {event.preventDefault(); finish(false);};
    dialog.showModal(); $('#confirm-cancel').focus();
  });
}
function statusOptions(value) {return statuses.map(s => `<option value="${esc(s)}" ${s === value ? 'selected' : ''}>${esc(t(s))}</option>`).join('');}
function badge(status) {return `<span class="badge ${status === 'Offer' ? 'good' : status === '已拒绝' ? 'bad' : ''}">${esc(t(status))}</span>`;}
function translatePage() {
  document.documentElement.lang = language;
  document.title = t('职投档案');
  document.querySelectorAll('[data-i18n]').forEach(e => e.textContent = t(e.dataset.i18n));
  document.querySelectorAll('[data-placeholder]').forEach(e => e.placeholder = t(e.dataset.placeholder));
  document.querySelectorAll('[data-aria]').forEach(e => e.setAttribute('aria-label', t(e.dataset.aria)));
  ArchiveDates.refresh();
  const status = $('#status-filter').value, editorStatus = $('#application-form').elements.status.value || '已投递';
  $('#status-filter').innerHTML = `<option value="">${esc(t('全部状态'))}</option>` + statusOptions(status);
  $('#status-filter').value = status;
  $('#application-form').elements.status.innerHTML = statusOptions(editorStatus);
  $('#language').value = language;
  $('#page-title').textContent = t({applications:'投递档案',mail:'求职邮箱',settings:'备份与设置'}[view]);
  $('#eyebrow').textContent = t(desktop ? '你的本机求职工作台' : '你的求职工作台');
  $('#shutdown').textContent = t(desktop ? '关闭应用' : '停止本地服务');
  $('#close-hint').textContent = t(desktop ? '关闭应用窗口即停止服务，已保存的档案会保留在本机。' : '关闭网页不会停止本地服务。下次运行启动文件即可回到这里。');
  $('#editor-title').textContent = t(editing ? '编辑投递 / 新增提交材料' : '新建投递');
  renderStats(); renderList();
  if (selectedRecord && selectedRecord.id === selected) renderDetail(selectedRecord);
  renderMails();
  if (mailSelected) showMail(mailSelected); else emptyMail();
}
async function reload() {apps = await api('/api/applications'); renderStats(); renderList(); if (selected) await detail(selected);}
function renderStats() {
  const counts = [['全部机会',apps.length],['已投递',apps.filter(a => a.status !== '待投递').length],['进行中',apps.filter(a => ['初筛','笔试','面试'].includes(a.status)).length],['收获 Offer',apps.filter(a => a.status === 'Offer').length]];
  $('#stats').innerHTML = counts.map(([name,n]) => `<div class="stat"><span>${esc(t(name))}</span><strong>${n}</strong></div>`).join('');
}
function filtered() {
  const q = $('#search').value.trim().toLocaleLowerCase(), status = $('#status-filter').value, from = ArchiveDates.valid($('#date-from').value) ? $('#date-from').value : '', to = ArchiveDates.valid($('#date-to').value) ? $('#date-to').value : '', key = $('#sort').value;
  return apps.filter(a => (!q || ['company','title'].some(k => String(a[k] || '').toLocaleLowerCase().includes(q))) && (!status || a.status === status) && (!from || a.applied_date >= from) && (!to || (a.applied_date && a.applied_date <= to)))
    .sort((a,b) => key === 'company' ? a[key].localeCompare(b[key],language) : b[key].localeCompare(a[key]));
}
function emptyDetail() {$('#detail').innerHTML = `<div class="empty"><b>${esc(t('你的求职时间线'))}</b>${esc(t('选择一条投递，查看 JD、提交材料和状态历史。'))}<br>${esc(t('所有文件都保留独立版本。'))}</div>`;}
function renderList() {
  const rows = filtered();
  if (selected && !rows.some(a => a.id === selected)) {selected = null; selectedRecord = null; detailRequest++;}
  $('#result-count').textContent = t('显示 {count} / {total} 条投递', {count:rows.length,total:apps.length});
  $('#clear-filters').hidden = !['search','status-filter','date-from','date-to'].some(id => $('#'+id).value);
  $('#list').innerHTML = rows.length ? rows.map(a => `<button class="record ${selected === a.id ? 'selected' : ''}" data-id="${a.id}" aria-pressed="${selected === a.id}"><div class="record-top"><strong>${esc(a.company)}</strong>${badge(a.status)}</div><p>${esc(a.title)}</p><small>${esc(a.applied_date ? t('投递于 {date}',{date:a.applied_date}) : t('尚未填写投递日期'))}</small></button>`).join('') : `<div class="empty"><b>${esc(t(apps.length ? '没有匹配的投递' : '从第一份投递开始'))}</b>${esc(t(apps.length ? '试试调整搜索或筛选条件。' : '点击右上角「新建投递」，保存网页与实际提交的材料。'))}</div>`;
  $('#list').querySelectorAll('[data-id]').forEach(e => e.onclick = () => detail(e.dataset.id).catch(e => toast(e.message)));
  if (!selected) emptyDetail();
}
async function detail(id) {
  selected = id; selectedRecord = null; renderList();
  if (selected !== id) return;
  const request = ++detailRequest;
  $('#detail').innerHTML = `<p class="hint">${esc(t('正在读取档案…'))}</p>`;
  try {
    const record = await api('/api/applications/'+id);
    if (request !== detailRequest || selected !== id) return;
    selectedRecord = record; renderDetail(record);
  } catch(e) {if (request === detailRequest) {selected = null; renderList(); throw e;}}
}
function historyEvent(event) {
  if (language !== 'en') return event;
  const parts = event.split('；');
  const head = parts[0].startsWith('更新：') ? t('更新：') + parts[0].slice(3).split('、').map(s => t(s)).join(', ') : t(parts[0]);
  return head + parts.slice(1).map(s => {const match = s.match(/^归档 (\d+) 份新材料$/); return '; '+(match ? t('归档 {count} 份新材料',{count:match[1]}) : s);}).join('');
}
function renderDetail(a) {
  $('#detail').innerHTML = `<div class="detail-head"><div><small>${esc(a.company)}</small><h2>${esc(a.title)}</h2>${badge(a.status)}</div><button id="edit-record">${esc(t('编辑 / 归档材料'))}</button></div><div class="meta"><span>${esc(t('投递日期'))}: ${esc(a.applied_date || t('未填写'))}</span><span>${esc(t('更新'))}: ${stamp(a.updated_at)}</span></div><div class="quick-status"><label for="quick-status">${esc(t('当前状态'))}</label><select id="quick-status">${statusOptions(a.status)}</select><button id="save-status" disabled>${esc(t('更新状态'))}</button></div>${a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noreferrer">${esc(t('打开投递网页 ↗'))}</a>` : ''}<h3>${esc(t('职位描述'))}</h3><div class="prose">${esc(a.jd || t('暂无 JD，可编辑或从网页抓取。'))}</div>${a.notes ? `<h3>${esc(t('备注'))}</h3><div class="prose">${esc(a.notes)}</div>` : ''}<h3>${esc(t('实际提交材料 · {count} 份',{count:a.documents.length}))}</h3>${a.documents.map(d => `<div class="file"><div><a href="/files/${d.id}">${esc(d.name)} ↓</a><small>${esc(t(d.kind === 'cv' ? 'CV' : d.kind === 'letter' ? '动机信' : '其他'))} · ${esc(d.submitted_date || t('未填日期'))} · ${(d.size/1024).toFixed(1)} KB ${esc(d.label)}</small><small>${esc(t('归档'))}: ${stamp(d.created_at)}</small></div></div>`).join('') || `<p class="hint">${esc(t('尚未归档材料。编辑记录即可新增文件。'))}</p>`}<h3>${esc(t('关联邮件 · {count} 封',{count:a.mails.length}))}</h3>${a.mails.map(m => `<button class="record" data-mail="${m.id}"><strong>${esc(m.subject || t('（无主题）'))}</strong><small>${esc(m.sender)}</small></button>`).join('') || `<p class="hint">${esc(t('在求职邮箱中把邮件关联到这条投递。'))}</p>`}<h3>${esc(t('更新历史'))}</h3>${a.history.map(h => `<details class="history"><summary>${stamp(h.created_at)} · ${esc(historyEvent(h.event))}</summary><pre class="prose">${esc(historyText(h.snapshot))}</pre></details>`).join('')}`;
  $('#edit-record').onclick = () => openEditor(a);
  $('#quick-status').onchange = () => $('#save-status').disabled = $('#quick-status').value === a.status;
  action($('#save-status'), async () => {await api('/api/applications/'+a.id+'/status',{status:$('#quick-status').value}); await reload(); toast(t('投递状态已更新'));});
  $('#detail').querySelectorAll('[data-mail]').forEach(e => e.onclick = async () => {try {showView('mail'); await loadMails(); showMail(e.dataset.mail);} catch(error) {toast(error.message);}});
}
function historyText(raw) {
  try {const s = JSON.parse(raw); return [['状态',t(s.status)],['日期',s.applied_date],['公司',s.company],['职位',s.title],['网页',s.url],['备注',s.notes]].map(([label,value]) => `${t(label)}: ${value ?? ''}`).join('\n') + '\n\nJD:\n' + s.jd;}
  catch {return raw;}
}
function formSnapshot() {const f = $('#application-form'); return JSON.stringify([...fields,'submitted_date','document_label','new_letter'].map(k => f.elements[k].value).concat([...$('#cv-files').files,...$('#letter-files').files].map(f => [f.name,f.size,f.lastModified])));}
function dirtyEditor() {return $('#editor').open && formSnapshot() !== editorSnapshot;}
async function closeEditor() {if (saving) return; if (dirtyEditor() && !await confirmAction(t('有尚未保存的修改，确定放弃吗？'))) return; editorSession++; $('#editor').close();}
function openEditor(a = null) {
  editing = a?.id || null; editorSession++;
  const f = $('#application-form'); f.reset();
  for (const k of fields) f.elements[k].value = a?.[k] ?? (k === 'status' ? '已投递' : k === 'applied_date' ? today() : '');
  f.elements.submitted_date.value = a?.applied_date || today();
  $('#editor-title').textContent = t(a ? '编辑投递 / 新增提交材料' : '新建投递');
  $('#delete-record').hidden = !editing;
  $('#form-message').textContent = ''; $('#fetch-jd').disabled = false; editorSnapshot = formSnapshot(); $('#editor').showModal();
}
async function file64(file) {if (file.size > 25*1024*1024) throw Error(t('{name} 超过 25 MB',{name:file.name})); return new Promise((resolve,reject) => {const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = () => reject(Error(t('文件读取失败'))); reader.readAsDataURL(file);});}
$('#application-form').onsubmit = async e => {
  e.preventDefault(); if (saving) return;
  saving = true; $('#save').disabled = true; $('#close-editor').disabled = true; $('#delete-record').disabled = true; $('#form-message').textContent = t('正在归档，请稍候…');
  try {
    const f = e.target, payload = Object.fromEntries(fields.map(k => [k,f.elements[k].value]));
    payload.new_letter = f.elements.new_letter.value; payload.submitted_date = f.elements.submitted_date.value; payload.document_label = f.elements.document_label.value; payload.uploads = [];
    const files = [['#cv-files','cv'],['#letter-files','letter']].flatMap(([selector,kind]) => [...$(selector).files].map(file => ({file,kind})));
    if (files.length > 10) throw Error(t('一次最多归档 10 个文件'));
    for (const {file,kind} of files) payload.uploads.push({name:file.name,kind,data:await file64(file),submitted_date:payload.submitted_date,label:payload.document_label});
    const a = await api('/api/applications'+(editing ? '/'+editing : ''),payload);
    selected = a.id; editorSession++; $('#editor').close(); await reload(); toast(t('已保存，新增材料已独立归档'));
  } catch(error) {$('#form-message').textContent = error.message;}
  finally {saving = false; $('#save').disabled = false; $('#close-editor').disabled = false; $('#delete-record').disabled = false;}
};
async function deleteEditingRecord() {
  if (!editing || saving) return;
  const id = editing, record = apps.find(a => a.id === id);
  saving = true;
  for (const selector of ['#save','#close-editor','#delete-record','#fetch-jd']) $(selector).disabled = true;
  let deleted = false;
  try {
    const message = t('确认删除「{company} · {title}」？投递记录、归档材料和更新历史将被移除；关联邮件保留并解除关联。删除前会自动保存完整备份。未保存的修改将被放弃。',{company:record?.company || '',title:record?.title || ''});
    if (!await confirmAction(message,'确认删除')) return;
    editorSession++;
    $('#form-message').textContent = t('正在备份并删除…');
    const result = await api('/api/applications/'+id+'/delete',{confirm:'DELETE'});
    deleted = true;
    apps = apps.filter(a => a.id !== id);
    mails = mails.map(m => m.application_id === id ? {...m,application_id:null} : m);
    selected = null; selectedRecord = null; editing = null; detailRequest++;
    $('#editor').close(); renderStats(); renderList();
    await reload(); await loadMails();
    toast(result.warning || t('已删除。删除前备份保存在 data/backups/{name}',{name:result.safety_backup}));
  } catch(error) {
    if (deleted) toast(t('投递已删除，但刷新失败，请重新打开应用。'));
    else $('#form-message').textContent = error.message;
  } finally {
    saving = false;
    for (const selector of ['#save','#close-editor','#delete-record','#fetch-jd']) $(selector).disabled = false;
  }
}
$('#delete-record').onclick = deleteEditingRecord;
action($('#fetch-jd'), async () => {
  const f = $('#application-form'), session = editorSession;
  const previousJD = f.elements.jd.value;
  if (previousJD.trim() && !await confirmAction(t('抓取结果将替换当前 JD，是否继续？'))) return;
  $('#form-message').textContent = t('正在读取公开网页…');
  try {
    const p = await api('/api/fetch-jd',{url:f.elements.url.value});
    if (session !== editorSession || !$('#editor').open) return;
    if (f.elements.jd.value !== previousJD && !await confirmAction(t('抓取期间 JD 已被修改，是否用抓取结果替换？'))) return;
    f.elements.jd.value = p.jd;
    if (p.title && !f.elements.title.value.trim()) f.elements.title.value = p.title;
    if (p.company && !f.elements.company.value.trim()) f.elements.company.value = p.company;
    $('#form-message').textContent = p.warning || t('已抓取，请核对职位描述后保存。');
  } catch(error) {if (session === editorSession) $('#form-message').textContent = error.message + ' '+t('可手动粘贴 JD。');}
});
function showView(name) {
  view = name;
  for (const n of ['applications','mail','settings']) $('#'+n+'-view').hidden = n !== name;
  document.querySelectorAll('nav button').forEach(b => {b.classList.toggle('active',b.dataset.view === name); b.setAttribute('aria-current',b.dataset.view === name ? 'page' : 'false');});
  $('#page-title').textContent = t({applications:'投递档案',mail:'求职邮箱',settings:'备份与设置'}[name]);
  $('#add').hidden = name !== 'applications'; $('#stats').hidden = name !== 'applications';
  if (name === 'mail') {gmailStatus().catch(e => toast(e.message)); loadMails().catch(e => toast(e.message));}
}
async function gmailStatus() {
  const s = await api('/api/gmail');
  $('#gmail-state').textContent = s.connected ? t('已连接 {email} · 只读权限',{email:s.email}) : t(s.configured ? '配置已导入，点击连接 Gmail 完成授权。' : '尚未连接。首次使用请先导入 Google 桌面 OAuth 配置。');
  $('#gmail-connect').disabled = !s.configured; $('#gmail-sync').disabled = !s.connected; return s;
}
$('#google-config').onchange = async e => {try {const file = e.target.files[0]; if (!file) return; if (file.size > 100000) throw Error(t('配置文件过大')); if (mails.length && !await confirmAction(t('导入新配置会清除当前邮件缓存，投递与材料保留。继续？'))) return; await api('/api/gmail/configure',JSON.parse(await file.text())); nextPage = ''; $('#gmail-more').disabled = true; await gmailStatus(); await loadMails(); toast(t('配置已导入，请连接 Gmail'));} catch(error) {toast(error.message);} finally {e.target.value = '';}};
action($('#gmail-connect'), async () => {const p = await api('/api/gmail/connect',{}); const a = document.createElement('a'); a.href = p.url; a.target = '_blank'; a.rel = 'noreferrer'; a.click(); toast(t('请在 Google 页面完成授权，然后刷新连接状态'));});
action($('#gmail-status'),gmailStatus);
action($('#gmail-disconnect'), async () => {if (!await confirmAction(t('断开 Gmail 并删除本机已同步邮件？投递档案和附件保留。'))) return; const r = await api('/api/gmail/disconnect',{}); nextPage = ''; $('#gmail-more').disabled = true; await gmailStatus(); await loadMails(); toast(r.warning || t('已断开并清除邮件缓存'));});
async function sync(page = '') {const r = await api('/api/gmail/sync',{query:$('#gmail-query').value,page_token:page}); nextPage = r.next_page || ''; $('#gmail-more').disabled = !nextPage; await loadMails(); toast(t('已同步 {count} 封邮件',{count:r.count}) + (r.errors?.length ? ' '+t('部分读取失败')+': '+r.errors.join('; ') : ''));}
action($('#gmail-sync'), () => sync());
$('#gmail-query').oninput = () => {nextPage = ''; $('#gmail-more').disabled = true;};
$('#gmail-more').onclick = async () => {const b = $('#gmail-more'); b.disabled = true; try {await sync(nextPage);} catch(e) {toast(e.message);} finally {b.disabled = !nextPage;}};
function emptyMail() {$('#mail-detail').innerHTML = `<div class="empty"><b>${esc(t('邮件与投递放在一起'))}</b>${esc(t('同步后选择邮件，查看正文、关联职位并手动更新状态。'))}</div>`;}
async function loadMails() {mails = await api('/api/mails'); renderMails(); if (mailSelected && mails.some(m => m.id === mailSelected)) showMail(mailSelected); else {mailSelected = null; emptyMail();}}
function renderMails() {
  const q = $('#mail-search').value.toLowerCase(), rows = mails.filter(m => [m.sender,m.subject,m.body].some(s => s.toLowerCase().includes(q)));
  if (mailSelected && !rows.some(m => m.id === mailSelected)) {mailSelected = null; emptyMail();}
  $('#mail-list').innerHTML = rows.length ? rows.map(m => `<button class="record ${mailSelected === m.id ? 'selected' : ''}" data-id="${m.id}"><strong>${esc(m.subject || t('（无主题）'))}</strong><p>${esc(m.sender)}</p><small>${stamp(m.received_at)} ${m.application_id ? '· '+esc(t('已关联')) : ''}</small></button>`).join('') : `<div class="empty"><b>${esc(t('暂无邮件'))}</b>${esc(t('连接 Gmail 并点击同步，或调整搜索条件。'))}</div>`;
  $('#mail-list').querySelectorAll('[data-id]').forEach(e => e.onclick = () => showMail(e.dataset.id));
}
function suggestion(m) {const s = (m.subject+' '+m.body).toLowerCase(); if (/unfortunately|regret to|not selected|遗憾|拒绝|pas retenu/.test(s)) return '已拒绝'; if (/offer letter|offer of employment|录用通知|聘用|proposition d.embauche/.test(s)) return 'Offer'; if (/interview|面试|entretien/.test(s)) return '面试'; if (/assessment|笔试|coding test/.test(s)) return '笔试'; return '';}
function showMail(id) {
  mailSelected = id; const m = mails.find(m => m.id === id); if (!m) return; renderMails(); if (mailSelected !== id) return; const suggest = suggestion(m);
  $('#mail-detail').innerHTML = `<h2 class="mail-subject">${esc(m.subject || t('（无主题）'))}</h2><p class="hint">${esc(m.sender)}<br>${stamp(m.received_at)}</p><div class="link-controls"><select id="mail-app" aria-label="${esc(t('关联投递'))}"><option value="">${esc(t('不关联'))}</option>${apps.map(a => `<option value="${a.id}" ${a.id === m.application_id ? 'selected' : ''}>${esc(a.company+' · '+a.title)}</option>`).join('')}</select><button id="link-mail">${esc(t('保存关联'))}</button></div>${suggest ? `<p class="hint">${esc(t('关键词建议'))}: ${badge(suggest)}. ${esc(t('请核对正文，建议可能不准确。'))}</p>` : ''}<div class="link-controls"><select id="mail-status" aria-label="${esc(t('更新投递状态'))}">${statusOptions(suggest || '已投递')}</select><button id="update-from-mail">${esc(t('确认更新关联职位状态'))}</button></div><h3>${esc(t('邮件正文'))}</h3><div class="prose">${esc(m.body || m.snippet || t('暂无可读取的正文'))}</div>`;
  action($('#link-mail'), async () => {await api('/api/mails/link',{id:m.id,application_id:$('#mail-app').value}); await loadMails(); toast(t('邮件关联已保存'));});
  action($('#update-from-mail'), async () => {const aid = $('#mail-app').value; if (!aid) throw Error(t('请先选择关联职位')); const status = $('#mail-status').value; if (!await confirmAction(t('把所选投递更新为「{status}」？',{status:t(status)}))) return; await api('/api/applications/'+aid+'/status',{status}); await api('/api/mails/link',{id:m.id,application_id:aid}); await reload(); await loadMails(); toast(t('投递状态已更新'));});
}
async function nativeExport(kind,id = '') {if (!window.pywebview?.api?.export) throw Error(t('桌面窗口正在初始化，请稍后重试')); const r = await window.pywebview.api.export(token,kind,id); if (r.error) throw Error(t(r.error)); if (r.path) toast(t('已保存：{path}',{path:r.path}));}
async function download(path,name) {
  if (desktop) {await nativeExport(path === '/api/backup' ? 'backup' : 'csv'); return;}
  const r = await fetch(path,{headers:{'X-Archive-Token':token}}); if (!r.ok) throw Error((await r.json()).error);
  const url = URL.createObjectURL(await r.blob()), a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url),60000);
}
action($('#backup'), () => download('/api/backup','JobArchive_'+today()+'.zip'));
action($('#csv'), () => download('/api/csv','applications_'+today()+'.csv'));
$('#restore').onchange = async e => {const file = e.target.files[0]; try {if (!file) return; if (file.size > 400*1024*1024) throw Error(t('备份上限 400 MB')); if (!await confirmAction(t('这会替换当前全部档案与材料。软件会先保存恢复前备份。确定恢复？'))) return; toast(t('正在校验并恢复…')); const r = await fetch('/api/restore',{method:'POST',headers:{'X-Archive-Token':token,'X-Confirm':'RESTORE','Content-Type':'application/zip'},body:file}); const p = await r.json(); if (!r.ok) throw Error(p.error); selected = null; mailSelected = null; await reload(); await loadMails(); toast(t('恢复完成；恢复前备份保存在本机 data/backups 文件夹'));} catch(error) {toast(error.message);} finally {e.target.value = '';}};
action($('#shutdown'), async () => {if (!await confirmAction(t(desktop ? '确定关闭应用？已保存的档案会保留。' : '停止本地服务？重新运行启动文件可以再次打开。'))) return; await api('/api/shutdown',{}); document.body.innerHTML = `<main><h1>${esc(t('本地服务已停止'))}</h1><p>${esc(t('你的档案已经保存在本机。重新运行「启动职投档案」即可继续。'))}</p></main>`;});
$('#language').onchange = async e => {
  const select = e.target; select.disabled = true;
  try {const saved = await api('/api/preferences',{language:select.value}); language = saved.language; translatePage(); if (desktop && window.pywebview?.api?.set_language) await window.pywebview.api.set_language(token); toast(t('界面语言已保存'));}
  catch(error) {select.value = language; toast(error.message);} finally {select.disabled = false;}
};
$('#add').onclick = () => openEditor(); $('#close-editor').onclick = closeEditor;
$('#editor').addEventListener('cancel',e => {e.preventDefault(); closeEditor();});
window.addEventListener('beforeunload',e => {if (dirtyEditor() || saving) {e.preventDefault(); e.returnValue = '';}});
document.querySelectorAll('nav button').forEach(b => b.onclick = () => showView(b.dataset.view));
for (const id of ['search','status-filter','date-from','date-to','sort']) $('#'+id).addEventListener('input',renderList);
$('#clear-filters').onclick = () => {for (const id of ['search','status-filter','date-from','date-to']) $('#'+id).value = ''; ArchiveDates.refresh(); renderList(); $('#search').focus();};
$('#mail-search').oninput = renderMails;
document.addEventListener('keydown',e => {if (!(e.ctrlKey || e.metaKey) || e.altKey || $('#editor').open) return; if (e.key.toLowerCase() === 'k') {e.preventDefault(); showView('applications'); $('#search').focus(); $('#search').select();} if (e.key.toLowerCase() === 'n') {e.preventDefault(); showView('applications'); openEditor();}});
document.addEventListener('click',e => {const a = e.target.closest('a[href^="/files/"]'); if (desktop && a) {e.preventDefault(); nativeExport('document',a.getAttribute('href').split('/').pop()).catch(error => toast(error.message));}});
async function boot() {
  try {const [catalog,info] = await Promise.all([api('/translations.json'),api('/api/info')]); translations = catalog; language = info.language || 'zh-CN'; desktop = !!info.desktop; $('#data-path').textContent = info.data_dir; $('#app-version').textContent = 'v'+info.version; ArchiveDates.init(); translatePage(); await reload(); document.documentElement.dataset.ready = 'true';}
  catch(error) {toast(error.message);}
}
boot();
