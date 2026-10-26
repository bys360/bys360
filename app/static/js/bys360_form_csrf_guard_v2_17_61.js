(function(){
  'use strict';
  function metaToken(){
    var meta=document.querySelector('meta[name="csrf-token"],meta[name="csrf_token"]');
    return meta && meta.getAttribute('content') ? meta.getAttribute('content') : '';
  }
  function setMetaToken(token){
    if(!token) return;
    var meta=document.querySelector('meta[name="csrf-token"]');
    if(!meta){ meta=document.createElement('meta'); meta.setAttribute('name','csrf-token'); document.head.appendChild(meta); }
    meta.setAttribute('content', token);
  }
  function syncForms(token){
    token = token || metaToken();
    if(!token) return;
    document.querySelectorAll('form').forEach(function(form){
      var method=(form.getAttribute('method')||'').toLowerCase();
      if(method !== 'post') return;
      var input=form.querySelector('input[name="csrf_token"]');
      if(!input){ input=document.createElement('input'); input.type='hidden'; input.name='csrf_token'; form.appendChild(input); }
      if(!input.value) input.value=token;
    });
  }
  function refreshToken(){
    return fetch('/pwa/csrf-refresh',{credentials:'same-origin',headers:{'Accept':'application/json'}})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(data){
        var token = data && (data.csrf_token || data.token || data.csrf);
        if(token){ setMetaToken(token); syncForms(token); }
        return token || '';
      }).catch(function(){ return ''; });
  }
  document.addEventListener('DOMContentLoaded', function(){ syncForms(); refreshToken(); });
  document.addEventListener('submit', function(event){
    var form=event.target;
    if(!form || !form.matches || !form.matches('form')) return;
    if((form.getAttribute('method')||'').toLowerCase() !== 'post') return;
    syncForms();
  }, true);
  window.addEventListener('pageshow', function(){ refreshToken(); });

  /* BYS360 session activity (30-minute idle policy): tells the server the user is working on this
   * page. Sends POST {data-session-activity-url} only from keyboard, pointer, touch, wheel and
   * text-input events, at most once a minute and only while the page is visible. There is no timer:
   * polling and other background code never reach this request. event.isTrusted only filters events
   * that page scripts dispatch themselves; it is not proof of a human, and the server treats this
   * request as a rate-limited, CSRF-protected activity notice from the logged-in page. */
  (function sessionActivity(){
    var body=document.body;
    var url=body && body.getAttribute('data-session-activity-url');
    if(!url || typeof window.fetch !== 'function') return;
    var MIN_INTERVAL_MS = 60000;
    var last=Date.now();
    function notify(event){
      if(!event.isTrusted || document.visibilityState !== 'visible') return;
      var now=Date.now();
      if(now - last < MIN_INTERVAL_MS) return;
      var token=metaToken();
      if(!token) return;
      last=now;
      window.fetch(url,{
        method:'POST',
        credentials:'same-origin',
        keepalive:true,
        headers:{'X-CSRFToken':token,'X-Requested-With':'XMLHttpRequest'}
      }).catch(function(){});
    }
    ['keydown','pointerdown','touchstart','wheel','input'].forEach(function(type){
      document.addEventListener(type, notify, {capture:true, passive:true});
    });
  })();
})();
