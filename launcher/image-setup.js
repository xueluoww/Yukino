/* Image actions are separate from the text key and never submit a test image. */
(function () {
  'use strict';
  var token = '', ready = false, pending = false, timer = null, populated = false;
  var buttons = Array.from(document.querySelectorAll('[data-image-action]'));
  var message = document.getElementById('image-setup-msg');
  function show(text, error) {
    message.textContent = text;
    message.hidden = false;
    message.setAttribute('data-tone', error ? 'err' : 'ok');
  }
  function disable(busy) {
    buttons.forEach(function (button) { button.disabled = busy || !ready; });
  }
  function request(path, body) {
    var args = { cache: 'no-store' };
    if (body !== undefined) {
      if (!token) return Promise.reject(new Error('启动状态未就绪，请刷新启动页。'));
      args.method = 'POST';
      args.headers = { 'Content-Type': 'application/json', 'X-Setup-Token': token };
      args.body = JSON.stringify(body);
    }
    return fetch(path, args).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || data.ok === false) throw new Error(data.error || '操作未完成');
        return data;
      });
    });
  }
  function update(data) {
    var config = data.config || {}, codex = data.codex || {}, kling = data.kling || {};
    var labels = { off: '仅使用已有图片', codex: 'Codex 原生生图', api: '独立图片 API' };
    document.getElementById('image-provider-status').textContent = '下次启动方式：' + (labels[config.provider] || '未配置') + '（启用后可能消耗对应服务额度）';
    document.getElementById('codex-image-status').textContent = codex.message || (codex.installed ? '发现 Codex CLI；登录与生图服务尚未检测' : '尚未找到 Codex CLI');
    document.getElementById('kling-image-status').textContent = kling.message || '尚未连接';
    if (!populated && config.provider === 'api') {
      document.getElementById('image-api-base').value = config.base_url || '';
      document.getElementById('image-api-model').value = config.model || '';
      document.getElementById('image-reference-mode').value = config.reference_mode || 'edits';
      document.getElementById('image-api-background').value = config.background || 'auto';
      document.getElementById('image-local-no-key').checked = !!config.local_no_key;
    }
    populated = true;
    var operation = data.operation || {};
    if (operation.busy) {
      pending = true;
      disable(true);
      show(operation.message || '正在配置或等待浏览器授权…');
      timer = window.setTimeout(poll, 1200);
    } else {
      if (pending) show(operation.message || '操作已完成', operation.ok === false);
      pending = false;
      disable(false);
    }
  }
  function poll() {
    if (timer) window.clearTimeout(timer);
    return request('/api/image/status').then(update).catch(function (error) {
      pending = false;
      disable(false);
      show(error.message || '无法连接启动器，请重新打开启动页。', true);
    });
  }
  function choose(action) {
    if (!ready || pending) return;
    pending = true;
    disable(true);
    var routes = {
      'codex-check': '/api/image/codex/check', 'codex-install': '/api/image/codex/install',
      'codex-login': '/api/image/codex/login', 'kling-install': '/api/image/kling/install',
      'codex-test': '/api/image/codex/test',
      'kling-connect': '/api/image/kling/connect'
    };
    var route = routes[action] || '/api/image/config';
    var body = {};
    if (action === 'off') body.provider = 'off';
    if (action === 'codex-save') body.provider = 'codex';
    if (action === 'api-save') {
      body = { provider: 'api', base_url: document.getElementById('image-api-base').value.trim(),
        model: document.getElementById('image-api-model').value.trim(), key: document.getElementById('image-api-key').value.trim(),
        reference_mode: document.getElementById('image-reference-mode').value,
        background: document.getElementById('image-api-background').value,
        local_no_key: document.getElementById('image-local-no-key').checked };
    }
    show(action === 'codex-test' ? '正在提交一张测试图片，会使用图片额度；请等待完成。' : '正在处理；不会提交试画任务。');
    request(route, body).then(function (result) {
      show(result.message || '操作已开始');
      if (action === 'api-save') document.getElementById('image-api-key').value = '';
      pending = !!result.started;
      return poll();
    }).catch(function (error) {
      pending = false;
      disable(false);
      show(error.message || '操作未完成', true);
    });
  }
  disable(true);
  buttons.forEach(function (button) { button.addEventListener('click', function () { choose(button.dataset.imageAction); }); });
  request('/api/status').then(function (status) {
    if (!status.setup_token) throw new Error('无法读取本机启动令牌');
    token = status.setup_token;
    ready = true;
    return poll();
  }).catch(function (error) { show(error.message, true); });
}());
