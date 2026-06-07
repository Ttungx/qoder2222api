/* ── Qoder Proxy Frontend ───────────────────────────────────────────────── */

let DATA = null;

// ── Toast ───────────────────────────────────────────────────────────────

function toast(msg, type = 'info') {
  const container = document.getElementById('toastContainer');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  container.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 250);
  }, 3000);
}

// ── Modal ───────────────────────────────────────────────────────────────

function openModal(title, bodyHtml, actions) {
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalBody').innerHTML = bodyHtml;
  const actEl = document.getElementById('modalActions');
  actEl.innerHTML = '';
  actions.forEach(a => {
    const btn = document.createElement('button');
    btn.className = `btn ${a.primary ? 'btn-primary' : 'btn-ghost'}`;
    btn.textContent = a.label;
    btn.onclick = a.onClick;
    actEl.appendChild(btn);
  });
  document.getElementById('modalBackdrop').classList.add('open');
  document.getElementById('modal').classList.add('open');
}

function closeModal() {
  document.getElementById('modalBackdrop').classList.remove('open');
  document.getElementById('modal').classList.remove('open');
}

// ── API Helpers ─────────────────────────────────────────────────────────

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...opts.headers },
    ...opts,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// ── Fetch data ──────────────────────────────────────────────────────────

async function fetchData() {
  try {
    const res = await fetch('/api/dashboard');
    DATA = await res.json();
  } catch (e) {
    console.error('Failed to fetch dashboard data', e);
    DATA = null;
  }
}

// ── Account Actions ─────────────────────────────────────────────────────

function showAddAccountModal() {
  openModal('新增 PAT 账户', `
    <div class="modal-field">
      <label>显示名称</label>
      <input id="addAccName" placeholder="例如：我的账户" autocomplete="off">
    </div>
    <div class="modal-field">
      <label>PAT Token</label>
      <input id="addAccPat" type="password" placeholder="个人访问令牌" autocomplete="off">
    </div>
    <div class="modal-field">
      <label>或环境变量名</label>
      <input id="addAccPatEnv" placeholder="例如 QODER_PAT" autocomplete="off">
    </div>
  `, [
    { label: '取消', onClick: closeModal },
    { label: '添加', primary: true, onClick: submitAddAccount },
  ]);
  setTimeout(() => document.getElementById('addAccName').focus(), 100);
}

async function submitAddAccount() {
  const name = document.getElementById('addAccName').value.trim();
  const pat = document.getElementById('addAccPat').value.trim();
  const patEnv = document.getElementById('addAccPatEnv').value.trim();
  if (!name) { toast('请输入显示名称', 'error'); return; }
  if (!pat && !patEnv) { toast('请输入 PAT 或环境变量名', 'error'); return; }
  try {
    await api('/api/accounts', {
      method: 'POST',
      body: JSON.stringify({ display_name: name, pat: pat || null, pat_env: patEnv || null }),
    });
    closeModal();
    toast(`账户「${name}」已添加`, 'success');
    render();
  } catch (e) {
    toast('添加失败: ' + e.message, 'error');
  }
}

async function removeAccount(id, name) {
  openModal('确认删除', `
    <p style="color:var(--text-secondary);font-size:14px;line-height:1.6">
      确定要删除账户 <strong style="color:var(--text-primary)">${escapeHtml(name)}</strong>（${escapeHtml(id)}）吗？<br>
      此操作不可撤销。
    </p>
  `, [
    { label: '取消', onClick: closeModal },
    { label: '删除', primary: true, onClick: async () => {
      try {
        await api(`/api/accounts/${id}`, { method: 'DELETE' });
        closeModal();
        toast(`账户「${name}」已删除`, 'success');
        render();
      } catch (e) {
        toast('删除失败: ' + e.message, 'error');
      }
    }},
  ]);
}

async function toggleAccount(id, name, currentEnabled) {
  const action = currentEnabled ? '禁用' : '启用';
  try {
    await api(`/api/accounts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled: !currentEnabled }),
    });
    toast(`账户「${name}」已${action}`, 'success');
    render();
  } catch (e) {
    toast(`${action}失败: ` + e.message, 'error');
  }
}

async function resetHealth(id, name) {
  try {
    await api(`/api/accounts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ reset_health: true }),
    });
    toast(`账户「${name}」健康已重置`, 'success');
    render();
  } catch (e) {
    toast('重置失败: ' + e.message, 'error');
  }
}

async function importLocalAccounts() {
  try {
    const data = await api('/api/accounts/import-local', { method: 'POST' });
    if (data.imported > 0) {
      toast(`已导入 ${data.imported} 个本地账户`, 'success');
    } else {
      toast('未找到可导入的本地账户', 'info');
    }
    render();
  } catch (e) {
    toast('导入失败: ' + e.message, 'error');
  }
}

// ── OAuth Browser Login ─────────────────────────────────────────────────

let _oauthPollTimer = null;

function showOAuthModal() {
  openModal('浏览器授权登录', `
    <div id="oauthStep1">
      <p style="color:var(--text-secondary);font-size:14px;line-height:1.6;margin-bottom:16px">
        通过 Qoder 官网授权登录。点击下方按钮将在浏览器中打开授权页面。
      </p>
      <button class="btn btn-primary" onclick="startOAuth()" id="oauthStartBtn">
        <i data-lucide="external-link" style="width:14px;height:14px"></i> 开始授权
      </button>
    </div>
    <div id="oauthStep2" style="display:none">
      <p style="color:var(--text-secondary);font-size:14px;line-height:1.6;margin-bottom:12px">
        请在浏览器中完成登录授权。点击下方链接打开授权页面：
      </p>
      <a id="oauthLink" href="#" target="_blank" style="color:var(--primary);font-size:14px;word-break:break-all;display:block;padding:12px;background:var(--bg-surface-soft);border-radius:var(--radius-md);margin-bottom:12px">加载中…</a>
      <button class="btn btn-ghost" onclick="copyOAuthLink()" style="margin-bottom:16px">
        <i data-lucide="copy" style="width:14px;height:14px"></i> 复制链接
      </button>
      <div id="oauthStatus" style="color:var(--text-muted);font-size:13px">等待授权完成…</div>
    </div>
  `, [
    { label: '关闭', onClick: () => { stopOAuthPoll(); closeModal(); } },
  ]);
  lucide.createIcons();
}

async function startOAuth() {
  const btn = document.getElementById('oauthStartBtn');
  btn.disabled = true;
  btn.textContent = '正在初始化…';
  try {
    const data = await api('/api/oauth/start', { method: 'POST' });
    document.getElementById('oauthStep1').style.display = 'none';
    document.getElementById('oauthStep2').style.display = 'block';
    const link = document.getElementById('oauthLink');
    link.href = data.verification_uri;
    link.textContent = data.verification_uri;
    // Start polling
    _oauthPollLoginId = data.login_id;
    _oauthPollInterval = (data.interval || 2) * 1000;
    startOAuthPoll();
  } catch (e) {
    toast('初始化失败: ' + e.message, 'error');
    btn.disabled = false;
    btn.textContent = '开始授权';
  }
}

let _oauthPollLoginId = null;
let _oauthPollInterval = 1000;

function startOAuthPoll() {
  stopOAuthPoll();
  let pollCount = 0;
  _oauthPollTimer = setInterval(async () => {
    pollCount++;
    try {
      const data = await api(`/api/oauth/poll/${_oauthPollLoginId}`, { method: 'POST' });
      const statusEl = document.getElementById('oauthStatus');
      if (!statusEl) return;
      if (data.status === 'completed') {
        stopOAuthPoll();
        statusEl.textContent = '✅ 授权成功！正在添加账户…';
        statusEl.style.color = '#6ee7a0';
        setTimeout(() => {
          closeModal();
          toast('授权成功，账户已添加', 'success');
          render();
        }, 800);
      } else if (data.status === 'expired') {
        stopOAuthPoll();
        statusEl.textContent = '❌ 授权已过期，请重新发起';
        statusEl.style.color = '#fca5a5';
      } else {
        // pending - show animated status
        const dots = '.'.repeat((pollCount % 4));
        statusEl.textContent = `等待浏览器中完成授权${dots}（已等待 ${pollCount} 秒）`;
        statusEl.style.color = 'var(--text-muted)';
      }
    } catch (e) {
      // ignore transient poll errors
    }
  }, _oauthPollInterval);
}

function stopOAuthPoll() {
  if (_oauthPollTimer) { clearInterval(_oauthPollTimer); _oauthPollTimer = null; }
}

function copyOAuthLink() {
  const link = document.getElementById('oauthLink');
  if (link && link.href) {
    navigator.clipboard.writeText(link.href).then(() => toast('链接已复制', 'success'));
  }
}

// ── Model Management ───────────────────────────────────────────────────

function showAddModelModal() {
  openModal('新增模型别名', `
    <div class="modal-field">
      <label>模型别名（对外暴露名称）</label>
      <input id="addModelAlias" placeholder="例如 claude-4-sonnet" autocomplete="off">
    </div>
    <div class="modal-field">
      <label>Qoder 模型键（内部映射）</label>
      <input id="addModelKey" placeholder="例如 lite / pro / ultimate" autocomplete="off">
    </div>
    <div class="modal-field">
      <label>来源</label>
      <input id="addModelSource" value="system" autocomplete="off">
    </div>
    <div style="margin-top:8px;padding:12px;background:var(--bg-surface-soft);border-radius:var(--radius-md);font-size:12px;color:var(--text-muted);line-height:1.6">
      <strong style="color:var(--text-secondary)">Qoder 模型键参考：</strong><br>
      <code>lite</code> = Claude Sonnet 4.5（默认）&nbsp;
      <code>pro</code> = 性能模式&nbsp;
      <code>ultimate</code> = 终极模式<br>
      <code>auto</code> = 自动选择&nbsp;
      <code>efficient</code> = 高效&nbsp;
      <code>gmodel</code> = GPT 系列
    </div>
  `, [
    { label: '取消', onClick: closeModal },
    { label: '添加', primary: true, onClick: submitAddModel },
  ]);
  setTimeout(() => document.getElementById('addModelAlias').focus(), 100);
}

async function submitAddModel() {
  const alias = document.getElementById('addModelAlias').value.trim();
  const qoderKey = document.getElementById('addModelKey').value.trim();
  const qoderSource = document.getElementById('addModelSource').value.trim() || 'system';
  if (!alias) { toast('请输入模型别名', 'error'); return; }
  if (!qoderKey) { toast('请输入 Qoder 模型键', 'error'); return; }
  try {
    await api('/api/models', {
      method: 'POST',
      body: JSON.stringify({ alias, qoder_key: qoderKey, qoder_source: qoderSource }),
    });
    closeModal();
    toast(`模型「${alias}」已添加`, 'success');
    render();
  } catch (e) {
    toast('添加失败: ' + e.message, 'error');
  }
}

async function removeModel(alias) {
  openModal('确认删除', `
    <p style="color:var(--text-secondary);font-size:14px;line-height:1.6">
      确定要删除模型别名 <strong style="color:var(--text-primary)">${escapeHtml(alias)}</strong> 吗？<br>
      配置文件中的内置模型无法通过此方式删除。
    </p>
  `, [
    { label: '取消', onClick: closeModal },
    { label: '删除', primary: true, onClick: async () => {
      try {
        await api(`/api/models/${encodeURIComponent(alias)}`, { method: 'DELETE' });
        closeModal();
        toast(`模型「${alias}」已删除`, 'success');
        render();
      } catch (e) {
        toast('删除失败: ' + e.message, 'error');
      }
    }},
  ]);
}

// ── Routing ─────────────────────────────────────────────────────────────

let currentPage = 'dashboard';

function navigate(page) {
  currentPage = page;
  document.querySelectorAll('.sidebar-item').forEach(el => {
    el.classList.toggle('active', el.dataset.page === page);
  });
  render();
}

document.querySelectorAll('.sidebar-item').forEach(el => {
  el.addEventListener('click', (e) => {
    e.preventDefault();
    navigate(el.dataset.page);
  });
});

// ── Render ──────────────────────────────────────────────────────────────

async function render() {
  await fetchData();
  const app = document.getElementById('app');
  switch (currentPage) {
    case 'dashboard': app.innerHTML = renderDashboard(); break;
    case 'models': app.innerHTML = renderModels(); break;
    case 'accounts': app.innerHTML = renderAccounts(); break;
    case 'endpoints': app.innerHTML = renderEndpoints(); break;
    default: app.innerHTML = renderDashboard();
  }
  lucide.createIcons();
}

// ── Helpers ─────────────────────────────────────────────────────────────

function fmtUptime(sec) {
  if (!sec) return '—';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function healthBadge(health) {
  const map = {
    ok: ['badge-ok', '健康'],
    auth_failed: ['badge-error', '认证失败'],
    rate_limited: ['badge-warn', '已限流'],
    quota_exhausted: ['badge-error', '配额耗尽'],
    upstream_error: ['badge-warn', '上游错误'],
  };
  const [cls, label] = map[health] || ['badge-neutral', health || '未知'];
  return `<span class="badge ${cls}"><span class="badge-dot"></span>${label}</span>`;
}

function escapeHtml(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ── Dashboard Page ──────────────────────────────────────────────────────

function renderDashboard() {
  if (!DATA) return '<div class="empty-state">加载中…</div>';

  const { server, stats, accounts, models } = DATA;
  const successRate = stats.total_requests > 0
    ? Math.round((stats.total_success / stats.total_requests) * 100)
    : 0;

  return `
    <div class="main-header">
      <h1 class="main-title">仪表盘</h1>
      <p class="main-subtitle">Qoder Proxy 总览与状态</p>
    </div>

    <div class="cards-grid">
      <div class="card">
        <div class="card-label">服务器状态</div>
        <div class="card-value" style="display:flex;align-items:center;gap:10px">
          <span class="badge badge-ok"><span class="badge-dot"></span>运行中</span>
        </div>
        <div class="card-sub">${escapeHtml(server.host)}:${server.port} · 运行时间 ${fmtUptime(server.uptime_seconds)}</div>
      </div>
      <div class="card">
        <div class="card-label">总请求数</div>
        <div class="card-value">${stats.total_requests}</div>
        <div class="card-sub">${stats.total_success} 成功 · ${stats.total_error} 失败</div>
      </div>
      <div class="card">
        <div class="card-label">成功率</div>
        <div class="card-value">${successRate}%</div>
        <div class="card-sub">基于所有请求统计</div>
      </div>
      <div class="card">
        <div class="card-label">账户数</div>
        <div class="card-value">${accounts.length}</div>
        <div class="card-sub">${accounts.filter(a => a.enabled).length} 已启用 · ${accounts.filter(a => a.health === 'ok').length} 健康</div>
      </div>
      <div class="card">
        <div class="card-label">模型数</div>
        <div class="card-value">${models.length}</div>
        <div class="card-sub">已配置的别名</div>
      </div>
      <div class="card">
        <div class="card-label">执行模式</div>
        <div class="card-value" style="font-size:20px">${server.executor_mode}</div>
        <div class="card-sub">${server.api_keys_count > 0 ? server.api_keys_count + ' 个 API 密钥' : '无 API 密钥保护'}</div>
      </div>
    </div>

    ${accounts.length > 0 ? `
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">账户列表</span>
        <button class="panel-action" onclick="navigate('accounts')">查看全部 →</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>名称</th><th>来源</th><th>健康</th><th>失败次数</th></tr></thead>
          <tbody>
            ${accounts.slice(0, 5).map(a => `
              <tr>
                <td style="color:var(--text-primary);font-weight:500">${escapeHtml(a.display_name)}</td>
                <td><span class="badge badge-neutral">${a.source}</span></td>
                <td>${healthBadge(a.health)}</td>
                <td class="text-muted">${a.failure_count}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
    ` : `
    <div class="panel">
      <div class="panel-header"><span class="panel-title">账户</span></div>
      <div class="empty-state">暂无账户配置。<br><button class="btn btn-primary" style="margin-top:12px" onclick="showAddAccountModal()">添加账户</button></div>
    </div>
    `}

    ${Object.keys(stats.requests_by_model).length > 0 ? `
    <div class="panel">
      <div class="panel-header"><span class="panel-title">模型请求分布</span></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>模型</th><th>请求数</th></tr></thead>
          <tbody>
            ${Object.entries(stats.requests_by_model).map(([m, c]) => `
              <tr><td class="mono">${escapeHtml(m)}</td><td>${c}</td></tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
    ` : ''}
  `;
}

// ── Models Page ─────────────────────────────────────────────────────────

function renderModels() {
  if (!DATA) return '<div class="empty-state">加载中…</div>';
  const { models } = DATA;

  // Qoder key reference
  const keyRef = {
    lite: 'Claude Sonnet 4.5（默认）',
    pro: '性能模式',
    ultimate: '终极模式',
    auto: '自动选择',
    efficient: '高效模式',
    performance: '平衡模式',
    gmodel: 'GPT 系列',
    qmodel: 'Q 模型',
    q35model: 'Q3.5 模型',
    kmodel: 'Kimi 模型',
    mmodel: 'M 模型',
  };

  return `
    <div class="main-header">
      <h1 class="main-title">模型</h1>
      <p class="main-subtitle">配置模型别名与 Qoder 内部模型键的映射关系</p>
    </div>

    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">模型别名</span>
        <div style="display:flex;gap:8px;align-items:center">
          <span class="text-muted" style="font-size:13px">${models.length} 个已配置</span>
          <button class="btn btn-primary" onclick="showAddModelModal()">
            <i data-lucide="plus" style="width:14px;height:14px"></i> 新增模型
          </button>
        </div>
      </div>
      ${models.length > 0 ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>别名（对外）</th><th>Qoder 键（内部）</th><th>说明</th><th style="width:60px">操作</th></tr></thead>
          <tbody>
            ${models.map(m => {
              const key = m.id || m.alias || '';
              const qKey = m.qoder_key || key;
              const desc = keyRef[qKey] || '';
              const isConfig = m.is_config || false;
              return `
              <tr>
                <td class="mono" style="color:var(--text-primary);font-weight:500">${escapeHtml(key)}</td>
                <td><span class="badge badge-info">${escapeHtml(qKey)}</span></td>
                <td class="text-muted">${desc}</td>
                <td>
                  ${!isConfig ? `<button class="btn-icon danger" title="删除" onclick="removeModel('${escapeHtml(key)}')"><i data-lucide="trash-2"></i></button>` : '<span class="text-subtle" style="font-size:11px">内置</span>'}
                </td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
      ` : '<div class="empty-state">暂无模型别名配置。<br><button class="btn btn-primary" style="margin-top:12px" onclick="showAddModelModal()">添加模型</button></div>'}
    </div>
  `;
}

// ── Accounts Page ───────────────────────────────────────────────────────

function renderAccounts() {
  if (!DATA) return '<div class="empty-state">加载中…</div>';
  const { accounts } = DATA;

  return `
    <div class="main-header">
      <h1 class="main-title">账户</h1>
      <p class="main-subtitle">管理用于上游请求的 Qoder 账户</p>
    </div>

    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">所有账户</span>
        <div style="display:flex;gap:8px;align-items:center">
          <button class="btn btn-ghost" onclick="showOAuthModal()">
            <i data-lucide="globe" style="width:14px;height:14px"></i> 浏览器登录
          </button>
          <button class="btn btn-ghost" onclick="importLocalAccounts()">
            <i data-lucide="download" style="width:14px;height:14px"></i> 导入本地
          </button>
          <button class="btn btn-primary" onclick="showAddAccountModal()">
            <i data-lucide="plus" style="width:14px;height:14px"></i> 新增账户
          </button>
        </div>
      </div>
      ${accounts.length > 0 ? `
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>名称</th>
              <th>来源</th>
              <th>状态</th>
              <th>健康</th>
              <th>失败数</th>
              <th>冷却截止</th>
              <th style="width:120px">操作</th>
            </tr>
          </thead>
          <tbody>
            ${accounts.map(a => `
              <tr>
                <td class="mono text-muted" style="font-size:12px">${escapeHtml(a.id)}</td>
                <td style="color:var(--text-primary);font-weight:500">${escapeHtml(a.display_name)}</td>
                <td><span class="badge badge-neutral">${a.source}</span></td>
                <td>${a.enabled ? '<span class="badge badge-ok"><span class="badge-dot"></span>已启用</span>' : '<span class="badge badge-error"><span class="badge-dot"></span>已禁用</span>'}</td>
                <td>${healthBadge(a.health)}</td>
                <td class="text-muted">${a.failure_count}</td>
                <td class="text-muted" style="font-size:12px">${a.cooldown_until ? new Date(a.cooldown_until).toLocaleTimeString() : '—'}</td>
                <td>
                  <div style="display:flex;gap:2px">
                    <button class="btn-icon" title="${a.enabled ? '禁用' : '启用'}" onclick="toggleAccount('${a.id}','${escapeHtml(a.display_name)}',${a.enabled})">
                      <i data-lucide="${a.enabled ? 'toggle-right' : 'toggle-left'}"></i>
                    </button>
                    <button class="btn-icon" title="重置健康" onclick="resetHealth('${a.id}','${escapeHtml(a.display_name)}')">
                      <i data-lucide="refresh-cw"></i>
                    </button>
                    <button class="btn-icon danger" title="删除" onclick="removeAccount('${a.id}','${escapeHtml(a.display_name)}')">
                      <i data-lucide="trash-2"></i>
                    </button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
      ` : `
      <div class="empty-state">
        暂无账户配置。<br>
        <button class="btn btn-primary" style="margin-top:12px" onclick="showAddAccountModal()">添加账户</button>
      </div>
      `}
    </div>
  `;
}

// ── Endpoints Page ──────────────────────────────────────────────────────

function renderEndpoints() {
  if (!DATA) return '<div class="empty-state">加载中…</div>';
  const { server } = DATA;
  const base = `http://${server.host}:${server.port}`;

  const endpoints = [
    { method: 'GET', path: '/health', desc: '健康检查' },
    { method: 'GET', path: '/v1/models', desc: '列出可用模型别名' },
    { method: 'POST', path: '/v1/messages', desc: 'Anthropic Messages API（兼容）' },
    { method: 'POST', path: '/v1/chat/completions', desc: 'OpenAI Chat Completions API（兼容）' },
    { method: 'GET', path: '/api/dashboard', desc: '仪表盘数据（本 UI 使用）' },
    { method: 'GET', path: '/api/accounts', desc: '列出所有账户' },
    { method: 'POST', path: '/api/accounts', desc: '新增 PAT 账户' },
    { method: 'DELETE', path: '/api/accounts/{id}', desc: '删除账户' },
    { method: 'PATCH', path: '/api/accounts/{id}', desc: '更新账户（启用/禁用/重置健康）' },
    { method: 'POST', path: '/api/accounts/import-local', desc: '导入本地 Qoder 账户' },
    { method: 'GET', path: '/api/models', desc: '列出模型别名' },
    { method: 'POST', path: '/api/models', desc: '新增模型别名' },
    { method: 'DELETE', path: '/api/models/{alias}', desc: '删除模型别名' },
    { method: 'POST', path: '/api/oauth/start', desc: '启动浏览器 OAuth 授权' },
    { method: 'POST', path: '/api/oauth/poll/{login_id}', desc: '轮询 OAuth 授权结果' },
  ];

  return `
    <div class="main-header">
      <h1 class="main-title">接口</h1>
      <p class="main-subtitle">代理服务器提供的所有 API 端点</p>
    </div>

    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">API 端点</span>
        <span class="badge badge-neutral mono" style="font-size:12px">${base}</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>方法</th><th>路径</th><th>说明</th></tr></thead>
          <tbody>
            ${endpoints.map(ep => `
              <tr>
                <td><span class="badge ${ep.method === 'POST' ? 'badge-info' : ep.method === 'DELETE' ? 'badge-error' : ep.method === 'PATCH' ? 'badge-warn' : 'badge-ok'}">${ep.method}</span></td>
                <td class="mono" style="color:var(--text-primary)">${ep.path}</td>
                <td class="text-muted">${ep.desc}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>

    <div class="panel">
      <div class="panel-header"><span class="panel-title">快速测试</span></div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <button class="btn btn-ghost" onclick="testEndpoint('/health')">
          <i data-lucide="heart-pulse" style="width:14px;height:14px"></i> 健康检查
        </button>
        <button class="btn btn-ghost" onclick="testEndpoint('/v1/models')">
          <i data-lucide="boxes" style="width:14px;height:14px"></i> 列出模型
        </button>
        <button class="btn btn-ghost" onclick="testEndpoint('/api/accounts')">
          <i data-lucide="users" style="width:14px;height:14px"></i> 账户列表
        </button>
      </div>
      <pre id="testOutput" class="mono" style="margin-top:16px;padding:16px;background:var(--bg-surface-soft);border-radius:var(--radius-md);color:var(--text-secondary);font-size:12px;overflow-x:auto;min-height:48px;border:1px solid var(--border-soft);display:none"></pre>
    </div>
  `;
}

async function testEndpoint(path) {
  const pre = document.getElementById('testOutput');
  pre.style.display = 'block';
  pre.textContent = '加载中…';
  try {
    const res = await fetch(path);
    const data = await res.json();
    pre.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    pre.textContent = 'Error: ' + e.message;
  }
}

// ── Command Palette ─────────────────────────────────────────────────────

const CMD_ITEMS = [
  { label: '仪表盘', desc: '查看代理总览', icon: 'layout-dashboard', action: () => navigate('dashboard'), keys: ['G', 'D'] },
  { label: '模型', desc: '管理模型别名映射', icon: 'boxes', action: () => navigate('models'), keys: ['G', 'M'] },
  { label: '账户', desc: '管理 Qoder 账户', icon: 'users', action: () => navigate('accounts'), keys: ['G', 'A'] },
  { label: '接口', desc: '查看 API 端点', icon: 'plug', action: () => navigate('endpoints'), keys: ['G', 'E'] },
  { label: '新增账户', desc: '添加 PAT 账户', icon: 'user-plus', action: showAddAccountModal, keys: ['N'] },
  { label: '浏览器登录', desc: '通过 Qoder 官网 OAuth 授权', icon: 'globe', action: showOAuthModal },
  { label: '导入本地账户', desc: '从本地 Qoder 导入', icon: 'download', action: importLocalAccounts },
  { label: '新增模型', desc: '添加模型别名映射', icon: 'plus', action: showAddModelModal },
  { label: '健康检查', desc: '测试代理健康端点', icon: 'heart-pulse', action: () => { navigate('endpoints'); setTimeout(() => testEndpoint('/health'), 100); } },
  { label: '列出模型', desc: '测试模型列表端点', icon: 'list', action: () => { navigate('endpoints'); setTimeout(() => testEndpoint('/v1/models'), 100); } },
];

let cmdSelectedIdx = 0;
let cmdFiltered = [...CMD_ITEMS];

function openCmd() {
  document.getElementById('cmdBackdrop').classList.add('open');
  document.getElementById('cmdPalette').classList.add('open');
  const input = document.getElementById('cmdInput');
  input.value = '';
  input.focus();
  cmdFiltered = [...CMD_ITEMS];
  cmdSelectedIdx = 0;
  renderCmdResults();
}

function closeCmd() {
  document.getElementById('cmdBackdrop').classList.remove('open');
  document.getElementById('cmdPalette').classList.remove('open');
}

function renderCmdResults() {
  const container = document.getElementById('cmdResults');
  if (cmdFiltered.length === 0) {
    container.innerHTML = '<div class="empty-state">无匹配命令</div>';
    return;
  }
  container.innerHTML = `
    <div class="cmd-group-title">命令</div>
    ${cmdFiltered.map((item, i) => `
      <div class="cmd-item ${i === cmdSelectedIdx ? 'selected' : ''}" onclick="execCmd(${i})">
        <div class="cmd-item-icon"><i data-lucide="${item.icon}"></i></div>
        <div class="cmd-item-text">
          <div class="cmd-item-label">${item.label}</div>
          ${item.desc ? `<div class="cmd-item-desc">${item.desc}</div>` : ''}
        </div>
        ${item.keys ? `<div class="cmd-item-kbd">${item.keys.map(k => `<kbd>${k}</kbd>`).join('')}</div>` : ''}
      </div>
    `).join('')}
  `;
  lucide.createIcons();
}

function execCmd(idx) {
  const item = cmdFiltered[idx];
  if (item) {
    closeCmd();
    item.action();
  }
}

document.getElementById('cmdInput').addEventListener('input', (e) => {
  const q = e.target.value.toLowerCase();
  cmdFiltered = CMD_ITEMS.filter(item =>
    item.label.toLowerCase().includes(q) ||
    (item.desc && item.desc.toLowerCase().includes(q))
  );
  cmdSelectedIdx = 0;
  renderCmdResults();
});

document.getElementById('cmdInput').addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    cmdSelectedIdx = Math.min(cmdSelectedIdx + 1, cmdFiltered.length - 1);
    renderCmdResults();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    cmdSelectedIdx = Math.max(cmdSelectedIdx - 1, 0);
    renderCmdResults();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    execCmd(cmdSelectedIdx);
  } else if (e.key === 'Escape') {
    closeCmd();
  }
});

// Global shortcuts
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    document.getElementById('cmdPalette').classList.contains('open') ? closeCmd() : openCmd();
  }
  if (e.key === 'Escape') {
    if (document.getElementById('modal').classList.contains('open')) closeModal();
    else if (document.getElementById('cmdPalette').classList.contains('open')) closeCmd();
  }
});

// ── Init ────────────────────────────────────────────────────────────────

render();
setInterval(() => {
  if (!document.getElementById('cmdPalette').classList.contains('open')
    && !document.getElementById('modal').classList.contains('open')) render();
}, 10000);
