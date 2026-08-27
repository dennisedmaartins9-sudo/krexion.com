"""
Krexion Fingerprint WIN pack (v2.7.20)
======================================
CreepJS / Pixelscan-class hardening layered on top of RUT stealth +
optional CloakBrowser C++ kernel (Krexion Stealth).

Goals (Browser Profiles + RUT):
  • Deep same-origin iframe inheritance (beyond webdriver)
  • OffscreenCanvas parity with main-thread canvas seed
  • Worker deeper navigator inheritance
  • Stable ClientRects (cached — CreepJS double-read safe)
  • Richer chrome.runtime / csi / loadTimes surface
  • Quiet mode when Cloak/`real` — no extra JS canvas noise
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional


def build_fingerprint_win_js(
    fp: Optional[Dict[str, Any]] = None,
    *,
    cloak_mode: bool = False,
    fp_hash: int = 0,
) -> str:
    """Return an init-script string. Additive — safe after RUT/v230 inject."""
    fp = fp or {}
    cfg = {
        "quiet": bool(cloak_mode),
        "platform": str(fp.get("platform") or "Win32"),
        "vendor": str(fp.get("vendor") or "Google Inc."),
        "hc": int(fp.get("hardware_concurrency") or 8),
        "dm": int(fp.get("device_memory") or 8),
        "wglV": str(fp.get("webgl_vendor") or "Google Inc. (Intel)"),
        "wglR": str(
            fp.get("webgl_renderer")
            or "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)"
        ),
        "cseed": int(fp.get("canvas_seed") or 0),
        "hash": int(fp_hash or abs(hash(str(fp.get("platform")) + str(fp.get("hardware_concurrency") or 8))) % (2**31)),
    }
    cfg_json = json.dumps(cfg, ensure_ascii=True)
    return (
        "(function(){\n"
        "if (window.__KRX_FP_WIN__) return;\n"
        "window.__KRX_FP_WIN__ = true;\n"
        f"var C = {cfg_json};\n"
        """
var makeRng = function(seed){
  var s = (seed >>> 0) || 1;
  return function(){
    s ^= s << 13; s >>>= 0;
    s ^= s >>> 17; s >>>= 0;
    s ^= s << 5; s >>>= 0;
    return (s >>> 0) / 4294967296;
  };
};
var nativeMap = new WeakMap();
var markNative = function(fn, name){
  try { nativeMap.set(fn, 'function ' + (name || fn.name || '') + '() { [native code] }'); } catch(e){}
  return fn;
};
try {
  var _ots = Function.prototype.toString;
  Function.prototype.toString = function(){
    if (nativeMap.has(this)) return nativeMap.get(this);
    return _ots.call(this);
  };
  markNative(Function.prototype.toString, 'toString');
} catch(e){}

var applyNav = function(nav){
  if (!nav) return;
  try { Object.defineProperty(nav, 'webdriver', { get: function(){ return undefined; }, configurable: true }); } catch(e){}
  try {
    Object.defineProperty(nav, 'platform', { get: function(){ return C.platform; }, configurable: true });
    Object.defineProperty(nav, 'vendor', { get: function(){ return C.vendor; }, configurable: true });
    Object.defineProperty(nav, 'hardwareConcurrency', { get: function(){ return C.hc; }, configurable: true });
    if ('deviceMemory' in nav) {
      Object.defineProperty(nav, 'deviceMemory', { get: function(){ return C.dm; }, configurable: true });
    }
  } catch(e){}
};

try {
  window.chrome = window.chrome || {};
  var rt = window.chrome.runtime || {};
  if (typeof rt.id === 'undefined') rt.id = undefined;
  if (!rt.OnInstalledReason) {
    rt.OnInstalledReason = { CHROME_UPDATE:'chrome_update', INSTALL:'install', SHARED_MODULE_UPDATE:'shared_module_update', UPDATE:'update' };
  }
  if (!rt.PlatformOs) {
    rt.PlatformOs = { ANDROID:'android', CROS:'cros', LINUX:'linux', MAC:'mac', OPENBSD:'openbsd', WIN:'win' };
  }
  if (typeof rt.connect !== 'function') {
    rt.connect = markNative(function connect(){
      return { name:'', onDisconnect:{ addListener:function(){}, removeListener:function(){} },
        onMessage:{ addListener:function(){}, removeListener:function(){} }, postMessage:function(){}, disconnect:function(){} };
    }, 'connect');
  }
  if (typeof rt.sendMessage !== 'function') {
    rt.sendMessage = markNative(function sendMessage(){
      var cb = arguments[arguments.length - 1];
      if (typeof cb === 'function') { try { cb(undefined); } catch(e){} }
    }, 'sendMessage');
  }
  window.chrome.runtime = rt;
  if (typeof window.chrome.csi !== 'function') {
    window.chrome.csi = markNative(function csi(){
      return { startE: Date.now(), onloadT: Date.now(), pageT: Math.random()*1000+200, tran: 15 };
    }, 'csi');
  }
  if (typeof window.chrome.loadTimes !== 'function') {
    window.chrome.loadTimes = markNative(function loadTimes(){
      var now = Date.now()/1000;
      return { requestTime: now-0.5, startLoadTime: now-0.4, commitLoadTime: now-0.3,
        finishDocumentLoadTime: now-0.2, finishLoadTime: now-0.1, firstPaintTime: now-0.15,
        firstPaintAfterLoadTime: 0, navigationType: 'Other', wasFetchedViaSpdy: true,
        wasNpnNegotiated: true, npnNegotiatedProtocol: 'h2', wasAlternateProtocolAvailable: false,
        connectionInfo: 'h2' };
    }, 'loadTimes');
  }
} catch(e){}

applyNav(navigator);

var patchWin = function(w){
  try {
    if (!w || w.__KRX_FP_WIN_IFRAME__) return;
    w.__KRX_FP_WIN_IFRAME__ = true;
    applyNav(w.navigator);
    try { w.chrome = w.chrome || window.chrome; } catch(e){}
  } catch(e){}
};
try {
  var desc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
  if (desc && desc.get) {
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
      get: function(){ var w = desc.get.call(this); patchWin(w); return w; },
      configurable: true
    });
  }
  var scan = function(){
    try {
      var ifrs = document.getElementsByTagName('iframe');
      for (var i=0;i<ifrs.length;i++){ try { patchWin(ifrs[i].contentWindow); } catch(e){} }
    } catch(e){}
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scan);
  else scan();
  setInterval(scan, 1500);
} catch(e){}

if (!C.quiet) {
  try {
    var cache = new WeakMap();
    var noiseFor = function(el){
      if (cache.has(el)) return cache.get(el);
      var rng = makeRng(C.hash ^ ((el && el.tagName) ? el.tagName.length * 9973 : 1));
      var n = { dx: (rng()-0.5)*0.02, dy: (rng()-0.5)*0.02 };
      cache.set(el, n);
      return n;
    };
    var patchRects = function(proto, method){
      var orig = proto[method];
      if (!orig) return;
      proto[method] = markNative(function(){
        var rects = orig.apply(this, arguments);
        try {
          var n = noiseFor(this);
          if (rects && typeof rects.length === 'number') {
            for (var i=0;i<rects.length;i++){
              var r = rects[i]; if (!r) continue;
              try {
                Object.defineProperty(r, 'x', { get: function(){ return this.left + n.dx; }.bind(r) });
                Object.defineProperty(r, 'y', { get: function(){ return this.top + n.dy; }.bind(r) });
              } catch(e){}
            }
          }
        } catch(e){}
        return rects;
      }, method);
    };
    patchRects(Element.prototype, 'getClientRects');
    patchRects(Element.prototype, 'getBoundingClientRect');
    patchRects(Range.prototype, 'getClientRects');
    patchRects(Range.prototype, 'getBoundingClientRect');
  } catch(e){}
}

if (!C.quiet && typeof OffscreenCanvas !== 'undefined' && C.cseed > 0) {
  try {
    var rng = makeRng(C.cseed ^ 0x0ff5c);
    var _getContext = OffscreenCanvas.prototype.getContext;
    OffscreenCanvas.prototype.getContext = markNative(function(type, attrs){
      var ctx = _getContext.call(this, type, attrs);
      if (!ctx) return ctx;
      if (type === '2d' && ctx.getImageData && !ctx.__krxPatched) {
        ctx.__krxPatched = true;
        var _gid = ctx.getImageData.bind(ctx);
        ctx.getImageData = markNative(function(){
          var img = _gid.apply(this, arguments);
          try {
            var d = img.data;
            for (var i=0;i<d.length;i+=97){ d[i] = d[i] ^ (rng() > 0.5 ? 1 : 0); }
          } catch(e){}
          return img;
        }, 'getImageData');
      }
      if ((type === 'webgl' || type === 'webgl2') && ctx.getParameter && !ctx.__krxWgl) {
        ctx.__krxWgl = true;
        var _gp = ctx.getParameter.bind(ctx);
        var dbg = ctx.getExtension && ctx.getExtension('WEBGL_debug_renderer_info');
        ctx.getParameter = markNative(function(p){
          if (dbg) {
            if (p === dbg.UNMASKED_VENDOR_WEBGL) return C.wglV;
            if (p === dbg.UNMASKED_RENDERER_WEBGL) return C.wglR;
          }
          return _gp(p);
        }, 'getParameter');
      }
      return ctx;
    }, 'getContext');
  } catch(e){}
}

try {
  var bootstrap = 'try{Object.defineProperty(self.navigator,\"webdriver\",{get:function(){return undefined}});'
    + 'Object.defineProperty(self.navigator,\"platform\",{get:function(){return '+JSON.stringify(C.platform)+'}});'
    + 'Object.defineProperty(self.navigator,\"hardwareConcurrency\",{get:function(){return '+C.hc+'}});'
    + 'if(\"deviceMemory\" in self.navigator){Object.defineProperty(self.navigator,\"deviceMemory\",{get:function(){return '+C.dm+'}});}'
    + '}catch(e){}';
  if (window.Worker) {
    var OrigWorker = window.Worker;
    window.Worker = function(url, opts){
      try {
        var u = String(url || '');
        if (u.indexOf('blob:') === 0 || u.indexOf('data:') === 0) return new OrigWorker(url, opts);
        var src = bootstrap + ';importScripts(' + JSON.stringify(u) + ');';
        var blobUrl = URL.createObjectURL(new Blob([src], { type: 'application/javascript' }));
        return new OrigWorker(blobUrl, opts);
      } catch(e) { return new OrigWorker(url, opts); }
    };
    try { window.Worker.prototype = OrigWorker.prototype; } catch(e){}
  }
} catch(e){}
})();
"""
    )


def should_use_quiet_mode(
    *,
    reduce_js_fingerprint_noise: bool = False,
    canvas_mode: str = "noise",
    webgl_mode: str = "noise",
    audio_mode: str = "noise",
    font_mode: str = "noise",
) -> bool:
    """Quiet = Cloak/C++ or modes avoid JS noise."""
    if reduce_js_fingerprint_noise:
        return True
    modes = {str(canvas_mode or ""), str(webgl_mode or ""), str(audio_mode or ""), str(font_mode or "")}
    return "noise" not in modes and modes <= {"real", "off", ""}
