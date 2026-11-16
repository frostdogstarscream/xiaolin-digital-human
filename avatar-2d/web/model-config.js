(() => {
  'use strict';
  const node = id => document.getElementById(id);
  const select = node('llm-provider');
  if (!select) return;
  let settings, busy = false;
  const result = (text, error = false) => {
    node('provider-result').textContent = text;
    node('provider-result').style.color = error ? '#ffb0a4' : '#a7d9cd';
  };
  function fill(name) {
    const profile = settings.profiles[name];
    select.value = name;
    node('base-url').value = profile.base_url;
    node('model').value = profile.model;
    node('api-key').value = '';
    node('api-key').placeholder = profile.configured ? '已保存；留空继续使用此地址的密钥' : '请输入此服务的 API Key';
    node('opencode-note').hidden = name !== 'opencode_go';
    node('big-model-note').hidden = !settings.big_model_configured;
  }
  async function load() {
    const response = await fetch('/api/provider', {cache: 'no-store'});
    if (!response.ok) throw Error('无法读取大模型配置，请检查本机服务。');
    settings = await response.json();
    fill(settings.provider);
    const name = node('provider-name');
    if (name) name.textContent = settings.label;
    const current = node('active-model');
    if (current) current.textContent = `${settings.label} / ${settings.model || '未配置'}`;
    const collaboration = settings.collaboration || {mode:'single'};
    const generation = options => {
      if (!options || options.thinking === 'default' && options.reasoning_effort === 'default') return '默认推理设置';
      const mode = options.thinking === 'disabled' || options.reasoning_effort === 'none' ? '关闭思考' : options.thinking === 'enabled' ? '开启思考' : '思考开关默认';
      const mapped = options.effective_reasoning_effort && options.effective_reasoning_effort !== options.reasoning_effort
        ? `（服务端映射 ${options.effective_reasoning_effort}）` : '';
      return `${mode}，effort=${options.reasoning_effort}${mapped}`;
    };
    const status = node('collaboration-status');
    if (status) status.textContent = collaboration.mode === 'dual'
      ? `协同已启用：主问答 ${collaboration.small_model}［${generation(collaboration.small_generation)}］；后台执行 ${collaboration.big_model}［${generation(collaboration.big_generation)}］。${collaboration.same_model_placeholder ? '两角色使用同款模型，配置分别生效。' : ''}`
      : `当前为单模型模式：${generation(collaboration.small_generation)}。`;
    if (node('disable-collaboration')) node('disable-collaboration').disabled = collaboration.mode !== 'dual';
  }
  select.onchange = () => { fill(select.value); result('已选择服务预设，保存后才会启用。'); };
  async function submit(test) {
    if (busy || !settings) return;
    busy = true;
    node('test-provider').disabled = node('save-provider').disabled = select.disabled = true;
    const body = {provider: select.value, model: node('model').value,
      base_url: node('base-url').value, api_key: node('api-key').value};
    result(test ? '正在测试文字流，最长等待 35 秒…' : '正在保存…');
    try {
      const response = await fetch(test ? '/api/provider-test' : '/api/provider', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Avatar-Client': '1'},
        body: JSON.stringify(body)
      });
      const text = await response.text();
      let value;
      try { value = JSON.parse(text); } catch { value = {message: text}; }
      if (!response.ok || !value.ok) throw Error(value.message || value.error || '配置操作失败');
      if (test) {
        result(`文字流测试成功：${value.reply}\n首字 ${value.first_text_ms} ms · 总耗时 ${value.total_ms} ms\n尚未保存；点击“保存并启用”后用于正式问答。`);
      } else {
        node('api-key').value = '';
        await load();
        result('已保存并启用，从下一次大模型请求生效。百炼 TTS 密钥和音色已独立保留。');
      }
    } catch (error) { result(error.message, true); }
    finally {
      // Keep the password after a successful draft test so Save can use it.
      body.api_key = '';
      busy = false;
      node('test-provider').disabled = node('save-provider').disabled = select.disabled = false;
    }
  }
  node('test-provider').onclick = () => submit(true);
  node('save-provider').onclick = () => submit(false);
  async function setCollaboration(mode) {
    if (busy || !settings) return;
    busy = true;
    try {
      const response = await fetch('/api/provider-collaboration', {method:'POST',
        headers:{'Content-Type':'application/json','X-Avatar-Client':'1'},body:JSON.stringify({mode})});
      const text = await response.text();
      if (!response.ok) throw Error(text);
      await load();
      result(mode === 'single' ? '已关闭协同，下一次请求按单模型模式处理。'
        : '已启用协同，后台模型使用已保存主模型的独立配置。从下一次请求生效。');
    } catch (error) {result(error.message, true);}
    finally {busy = false;}
  }
  if (node('enable-collaboration')) node('enable-collaboration').onclick = () => setCollaboration('dual_primary_placeholder');
  if (node('disable-collaboration')) node('disable-collaboration').onclick = () => setCollaboration('single');
  load().catch(error => result(error.message, true));
})();
