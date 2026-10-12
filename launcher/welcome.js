/* Yukino 0.9 — 首启提示页脚本（纯原生 JS，无构建、无依赖）
 * 接口契约：
 *   GET  /api/status          → {name, version, python, data_dir, has_key, engine_running, engine_url}
 *   POST /api/key    {key}     → {ok:true, model} | {ok:false, error}
 *   POST /api/launch           → {ok:true, url}    | {ok:false, error}
 */
(function () {
  'use strict';

  var LAUNCHER_EXITED = '启动器已退出，请重新运行 启动 Yukino0.9.bat';
  var NETWORK_FAILED = '无法连接启动器服务，请重新运行 启动 Yukino0.9.bat';

  var el = {
    key: document.getElementById('api-key'),
    toggle: document.getElementById('toggle-key'),
    paste: document.getElementById('paste-key'),
    action: document.getElementById('action'),
    spinner: document.getElementById('spinner'),
    msg: document.getElementById('msg'),
    version: document.getElementById('version'),
    dataDir: document.getElementById('data-dir'),
    python: document.getElementById('python')
  };

  var state = {
    busy: false,
    statusReady: false,
    setupToken: '',
    hasKey: false,      // 服务端报告本机已保存密钥
    savedKey: '',       // 本次会话中校验通过的 Key（用于判断是否可以直接启动）
    engineRunning: false,
    engineUrl: ''
  };

  var LABEL_VERIFY = '保存并校验';
  var LABEL_LAUNCH = '启动游戏';

  /* ---------- 小工具 ---------- */

  function show(text, tone) {
    if (!el.msg) return;
    el.msg.textContent = String(text == null ? '' : text);
    if (tone) el.msg.setAttribute('data-tone', tone);
    else el.msg.removeAttribute('data-tone');
    el.msg.hidden = false;
  }

  function clearMsg() {
    if (!el.msg) return;
    el.msg.textContent = '';
    el.msg.removeAttribute('data-tone');
    el.msg.hidden = true;
  }

  function setBusy(busy, label) {
    state.busy = !!busy;
    if (el.key) el.key.disabled = state.busy;
    if (el.action) {
      el.action.disabled = state.busy;
      if (label) el.action.textContent = label;
    }
    if (el.toggle) el.toggle.disabled = state.busy;
    if (el.paste) el.paste.disabled = state.busy;
    if (el.spinner) el.spinner.hidden = !state.busy;
  }

  function setActionLabel(text) {
    if (el.action && !state.busy) el.action.textContent = text;
  }

  // 只替换已存在的元素；缺元素时静默跳过
  function setText(node, text) {
    if (node && text !== undefined && text !== null && text !== '') node.textContent = String(text);
  }

  // 替换文本里的 #{token} 占位符（服务端若已渲染过，这里就自然找不到占位符）
  function fillPlaceholders(map) {
    if (!document.body) return;
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    var nodes = [];
    var n;
    while ((n = walker.nextNode())) nodes.push(n);
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var text = node.nodeValue;
      if (!text || text.indexOf('#{') < 0) continue;
      var next = text;
      for (var token in map) {
        if (Object.prototype.hasOwnProperty.call(map, token) && map[token]) {
          next = next.split('#{' + token + '}').join(String(map[token]));
        }
      }
      if (next !== text) node.nodeValue = next;
    }
  }

  // 统一解析响应体：优先 JSON，失败则退回纯文本
  function readBody(res) {
    return res.text().then(function (raw) {
      var data = null;
      if (raw) {
        try { data = JSON.parse(raw); } catch (e) { data = null; }
      }
      if (data && typeof data === 'object') {
        data.__status = res.status;
        return data;
      }
      return { __status: res.status, __raw: String(raw || '').trim() };
    });
  }

  function request(path, options) {
    var opt = options || {};
    var init = { method: opt.method || 'GET', cache: 'no-store' };
    if (opt.body !== undefined) {
      init.method = 'POST';
      if (!state.setupToken) return Promise.reject(new Error('启动状态尚未就绪，请刷新本机启动页。'));
      init.headers = { 'Content-Type': 'application/json', 'X-Setup-Token': state.setupToken };
      init.body = JSON.stringify(opt.body);
    }
    if (typeof fetch !== 'function') {
      return Promise.reject(new Error('当前浏览器不支持 fetch，请改用新版 Edge / Chrome 打开本页'));
    }
    return fetch(path, init).then(readBody, function () {
      var err = new Error(NETWORK_FAILED);
      err.network = true;
      throw err;
    });
  }

  // 服务端给的 error 原样返回，不做任何改写
  function serverError(data, fallback) {
    if (data && typeof data.error === 'string' && data.error) return data.error;
    if (data && data.__raw) return data.__raw;
    if (data && data.__status) return fallback + '（HTTP ' + data.__status + '）';
    return fallback;
  }

  function currentKey() {
    return el.key && typeof el.key.value === 'string' ? el.key.value.trim() : '';
  }

  // 当前是否处于「可以直接启动」的状态：
  //   本机已有保存的密钥且输入框为空，或输入框里正是刚校验通过的那一串。
  function canLaunchDirectly() {
    var key = currentKey();
    if (key === '') return state.hasKey;
    return key === state.savedKey;
  }

  /* ---------- 状态填充 ---------- */

  function applyStatus(data) {
    if (!data || typeof data.setup_token !== 'string' || !data.setup_token) {
      throw new Error('启动状态无效，请重新打开本机启动页。');
    }
    state.setupToken = data.setup_token;
    state.statusReady = true;
    setBusy(false);
    var name = data && typeof data.name === 'string' && data.name ? data.name : 'Yukino 0.9';
    var version = data && data.version ? data.version : '';
    var dataDir = data && data.data_dir ? data.data_dir : '';
    var python = data && data.python ? data.python : '';
    var engineUrl = data && data.engine_url ? data.engine_url : '';

    document.title = version ? name + ' — ' + version : name + ' — 正式测试版';

    if (version) setText(el.version, version);
    if (dataDir) setText(el.dataDir, dataDir);
    if (python) setText(el.python, 'Python ' + python);
    fillPlaceholders({
      name: name,
      version: version,
      data_dir: dataDir,
      python: python ? 'Python ' + python : '',
      engine_url: engineUrl
    });

    state.engineRunning = !!(data && data.engine_running);
    state.engineUrl = engineUrl;
    state.hasKey = !!(data && data.has_key);

    if (state.hasKey) {
      setActionLabel(LABEL_LAUNCH);
      if (el.key) el.key.placeholder = 'sk-...（本机已保存密钥，留空即使用已保存的密钥）';
      show('已检测到本机已保存的密钥。可直接启动游戏；若要更换，请填入新的 Key 后点击下方按钮。', 'ok');
    } else {
      setActionLabel(LABEL_VERIFY);
      if (el.key) el.key.placeholder = 'sk-...';
    }
  }

  function statusFailed(err) {
    state.statusReady = false;
    setBusy(false);
    if (el.action) el.action.disabled = true;
    var text = err && err.message ? err.message : NETWORK_FAILED;
    show('未能读取启动器状态：' + text, 'err');
  }

  function loadStatus() {
    return request('/api/status').then(applyStatus).catch(statusFailed);
  }

  /* ---------- 交互 ---------- */

  function toggleVisibility() {
    if (!el.key) return;
    var showing = el.key.getAttribute('type') === 'text';
    el.key.setAttribute('type', showing ? 'password' : 'text');
    if (el.toggle) {
      el.toggle.textContent = showing ? '显示' : '隐藏';
      el.toggle.setAttribute('aria-pressed', showing ? 'false' : 'true');
    }
    if (!showing && typeof el.key.focus === 'function') el.key.focus();
  }

  function pasteKey() {
    if (!el.key) return;
    function accept(text) {
      var value = String(text == null ? '' : text).trim();
      if (!value) {
        show('剪贴板里没有可用的文本。', 'err');
        return;
      }
      el.key.value = value;
      setActionLabel(LABEL_VERIFY);
      show('已从剪贴板填入，请点击下方按钮继续。', 'info');
    }
    function manual() {
      show('浏览器未授权读取剪贴板，请手动粘贴（Ctrl+V）。', 'info');
      if (typeof el.key.focus === 'function') el.key.focus();
    }
    if (navigator.clipboard && navigator.clipboard.readText) {
      navigator.clipboard.readText().then(accept, manual);
    } else {
      manual();
    }
  }

  function verifyKey() {
    var key = currentKey();
    if (!key) {
      show('请先填入 API Key。', 'err');
      if (el.key && typeof el.key.focus === 'function') el.key.focus();
      return Promise.resolve();
    }
    if (key.indexOf('sk-') !== 0) {
      show('这串字符不是以 sk- 开头，请确认复制完整、没有带引号或空格。', 'err');
      return Promise.resolve();
    }

    setBusy(true, '校验中…');
    clearMsg();
    return request('/api/key', { body: { key: key } }).then(function (data) {
      if (!data || data.ok !== true) {
        state.savedKey = '';
        show(serverError(data, '保存失败'), 'err');
        return;
      }
      state.hasKey = true;
      state.savedKey = '';
      if (el.key) el.key.value = '';
      setBusy(false, LABEL_LAUNCH);
      var model = data.model ? String(data.model) : '';
      show(model
        ? '校验通过，当前模型：' + model + '。点击「启动游戏」继续。'
        : '校验通过，可以启动游戏了。', 'ok');
    }, function (err) {
      state.savedKey = '';
      show(err && err.message ? err.message : NETWORK_FAILED, 'err');
    }).then(function () {
      if (state.busy) setBusy(false, canLaunchDirectly() ? LABEL_LAUNCH : LABEL_VERIFY);
    });
  }

  function launch() {
    setBusy(true, '启动中…');
    clearMsg();
    return request('/api/launch', { body: {} }).then(function (data) {
      if (!data || data.ok !== true || !data.url) {
        show(serverError(data, '启动失败'), 'err');
        return;
      }
      show('正在打开游戏：' + data.url, 'ok');
      try {
        window.location.href = String(data.url);
      } catch (e) {
        show('启动成功，但无法自动跳转，请手动访问：' + data.url, 'err');
      }
    }, function (err) {
      show(err && err.message ? err.message : NETWORK_FAILED, 'err');
    }).then(function () {
      if (state.busy) setBusy(false, canLaunchDirectly() ? LABEL_LAUNCH : LABEL_VERIFY);
    });
  }

  function onSubmit() {
    if (state.busy || !state.statusReady) return;
    // 输入框为空且本机已有密钥 → 直接启动；否则先校验当前输入
    if (canLaunchDirectly()) launch();
    else verifyKey();
  }

  function bind() {
    if (el.action) el.action.addEventListener('click', onSubmit);
    if (el.toggle) el.toggle.addEventListener('click', toggleVisibility);
    if (el.paste) el.paste.addEventListener('click', pasteKey);

    if (el.key) {
      el.key.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
          event.preventDefault();
          onSubmit();
        }
      });
      // 输入内容改变后按钮语义回到「保存并校验」（除非这正是已校验通过的那一串）
      el.key.addEventListener('input', function () {
        setActionLabel(canLaunchDirectly() ? LABEL_LAUNCH : LABEL_VERIFY);
      });
    }
  }

  function init() {
    bind();
    setBusy(true, '读取启动状态…');
    loadStatus();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 便于手工调试
  window.YukinoWelcome = {
    reload: loadStatus,
    state: state
  };
})();
