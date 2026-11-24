/* Watchtower 面板逻辑。
   为什么全用 textContent：读数里的 device_id 来自采集端，属于外部输入，
   拼进 innerHTML 就是 XSS 入口。阶段 1 防的是 SQL 注入，这里防的是 XSS。 */
const REFRESH_MS = 5000;
const el = (id) => document.getElementById(id);

function fmtTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '--';
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}

function setConn(state, text) {
  const node = el('conn');
  node.className = 'conn conn--' + state;
  node.textContent = text;
}

function showError(msg) {
  const box = el('error');
  box.textContent = msg;
  box.hidden = false;
}

function clearError() {
  el('error').hidden = true;
}

function appendCell(tr, text, cls) {
  const td = document.createElement('td');
  td.textContent = text;
  if (cls) td.className = cls;
  tr.appendChild(td);
  return td;
}

function renderAlerts(alerts, threshold) {
  const ul = el('alerts');
  ul.replaceChildren();
  if (!alerts.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = '暂无告警（阈值 ' + threshold + ' °C）';
    ul.appendChild(li);
    return;
  }
  for (const a of alerts) {
    const li = document.createElement('li');
    const t = document.createElement('span');
    t.className = 'alert-temp';
    t.textContent = Number(a.temperature).toFixed(1) + ' °C';
    const meta = document.createElement('span');
    meta.className = 'alert-meta';
    meta.textContent = a.device_id + ' · ' + fmtTime(a.created_at);
    li.appendChild(t);
    li.appendChild(meta);
    ul.appendChild(li);
  }
}

function renderRows(rows, threshold) {
  const tbody = el('rows');
  tbody.replaceChildren();
  if (!rows.length) {
    const tr = document.createElement('tr');
    appendCell(tr, '等待数据').colSpan = 4;
    tbody.appendChild(tr);
    return;
  }
  for (const r of rows) {
    const tr = document.createElement('tr');
    const temp = Number(r.temperature);
    appendCell(tr, fmtTime(r.created_at));
    appendCell(tr, r.device_id);
    appendCell(tr, temp.toFixed(1) + ' °C', temp >= threshold ? 'hot' : '');
    appendCell(tr, Number(r.humidity).toFixed(1) + ' %');
    tbody.appendChild(tr);
  }
}

function render(status, rows) {
  el('threshold').textContent = status.threshold;
  el('offline').textContent = status.offline_after;
  el('alert-count').textContent = String(status.alert_count);
  el('updated').textContent = '最后刷新 ' + fmtTime(new Date().toISOString());

  setConn(status.online ? 'up' : 'down', status.online ? '设备在线' : '设备离线');

  if (status.latest) {
    const temp = Number(status.latest.temperature);
    el('temp').textContent = temp.toFixed(1);
    el('temp').classList.toggle('hot', temp >= status.threshold);
    el('humid').textContent = Number(status.latest.humidity).toFixed(1);
    el('last').textContent = fmtTime(status.latest.created_at);
    el('last').title = status.latest.created_at;
  }
  renderAlerts(status.alerts, status.threshold);
  renderRows(rows, status.threshold);
}

async function refresh() {
  try {
    const [s, r] = await Promise.all([
      fetch('/api/status', { cache: 'no-store' }),
      fetch('/api/readings?limit=12', { cache: 'no-store' }),
    ]);
    if (!s.ok || !r.ok) throw new Error('HTTP ' + s.status + ' / ' + r.status);
    const status = await s.json();
    const rows = await r.json();
    clearError();
    render(status, rows);
  } catch (err) {
    setConn('down', '服务未连接');
    showError('连不上服务：' + err.message + '。确认 start.bat 窗口还开着。');
  }
}

refresh();
setInterval(refresh, REFRESH_MS);
