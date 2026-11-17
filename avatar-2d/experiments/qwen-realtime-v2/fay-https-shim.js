(function () {
  if (window.__xiaolinFayShimInstalled) return;
  window.__xiaolinFayShimInstalled = true;

  const origin = window.location.origin;
  const wsOrigin = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host;

  function rewriteHttpUrl(raw) {
    if (typeof raw !== 'string') return raw;
    let url = raw.replace(/^https?:\/\/[^/]+:(?:5000|5010)(?=\/|$)/i, origin);
    if (/^https?:\/\/[^/]+:5000\/?$/i.test(raw)) {
      return origin + '/fay/';
    }
    return url;
  }

  function rewriteWsUrl(raw) {
    if (typeof raw !== 'string') return raw;
    if (/^wss?:\/\/[^/]+:10003(\/|$)/i.test(raw)) {
      return wsOrigin + '/fay-ws';
    }
    return raw;
  }

  function isSyncTrigger(url, method) {
    const m = String(method || 'GET').toUpperCase();
    if (m === 'GET' || m === 'HEAD') return false;
    return /\/api\/(?:submit|start-live|stop-live|mcp\/)/.test(String(url || ''));
  }

  function notifyParent(url) {
    try {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: 'xiaolin_fay_updated', url: String(url || '') }, origin);
      }
    } catch (_) {}
  }

  const nativeFetch = window.fetch;
  if (typeof nativeFetch === 'function') {
    window.fetch = function (input, init) {
      let target = input;
      let urlStr = '';
      if (typeof input === 'string') {
        target = rewriteHttpUrl(input);
        urlStr = target;
      } else if (input && typeof input.url === 'string') {
        urlStr = rewriteHttpUrl(input.url);
        if (urlStr !== input.url) {
          target = new Request(urlStr, input);
        }
      }
      const method = (init && init.method) || (input && input.method) || 'GET';
      const req = nativeFetch.call(this, target, init);
      if (isSyncTrigger(urlStr, method)) {
        req.then(function (resp) {
          if (resp && resp.ok) notifyParent(urlStr);
        }).catch(function () {});
      }
      return req;
    };
  }

  if (window.XMLHttpRequest) {
    const origOpen = window.XMLHttpRequest.prototype.open;
    const origSend = window.XMLHttpRequest.prototype.send;
    window.XMLHttpRequest.prototype.open = function (method, url) {
      const rewritten = rewriteHttpUrl(String(url || ''));
      this.__xiaolinUrl = rewritten;
      this.__xiaolinMethod = method;
      const args = Array.prototype.slice.call(arguments);
      args[1] = rewritten;
      return origOpen.apply(this, args);
    };
    window.XMLHttpRequest.prototype.send = function () {
      if (isSyncTrigger(this.__xiaolinUrl, this.__xiaolinMethod)) {
        this.addEventListener('load', function () {
          if (this.status >= 200 && this.status < 300) notifyParent(this.__xiaolinUrl);
        });
      }
      return origSend.apply(this, arguments);
    };
  }

  if (window.WebSocket) {
    const NativeWS = window.WebSocket;
    window.WebSocket = function (url, protocols) {
      const nextUrl = rewriteWsUrl(String(url || ''));
      return protocols !== undefined ? new NativeWS(nextUrl, protocols) : new NativeWS(nextUrl);
    };
    window.WebSocket.prototype = NativeWS.prototype;
    Object.assign(window.WebSocket, NativeWS);
  }

  function mapMenuTarget(href) {
    if (!href) return null;
    try {
      const parsed = new URL(href, origin);
      if (parsed.port === '5000') {
        if (parsed.pathname === '/' || parsed.pathname === '') return '/fay/';
        if (parsed.pathname === '/setting') return '/fay/setting';
        return parsed.pathname + parsed.search;
      }
      if (parsed.port === '5010') {
        return parsed.pathname + parsed.search;
      }
      if (parsed.origin === origin) {
        if (parsed.pathname === '/') return '/fay/';
        if (parsed.pathname === '/setting') return '/fay/setting';
      }
    } catch (_) {}
    return null;
  }

  function patchMenuLinks() {
    document.querySelectorAll('.main_left_menu a').forEach(function (anchor) {
      const raw = anchor.getAttribute('href');
      const mapped = mapMenuTarget(raw);
      if (mapped && raw !== mapped) {
        anchor.setAttribute('href', mapped);
      }
    });
  }

  document.addEventListener('click', function (event) {
    const anchor = event.target && event.target.closest ? event.target.closest('.main_left_menu a') : null;
    if (!anchor) return;
    const mapped = mapMenuTarget(anchor.getAttribute('href') || anchor.href);
    if (mapped) {
      event.preventDefault();
      window.location.assign(mapped);
    }
  }, true);

  document.addEventListener('DOMContentLoaded', function () {
    patchMenuLinks();
    if (document.body && window.MutationObserver) {
      new MutationObserver(patchMenuLinks).observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['href'],
      });
    }
  });
})();
