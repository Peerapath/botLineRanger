'use strict';
// Dump the plaintext of outgoing TLS writes that look like the rangers /login request.
// BoringSSL's SSL_write sees the bytes before encryption, so this catches the pinned,
// direct-dialled native call that mitmproxy can never see. We filter to /login and the
// X-LINEGAME headers so ordinary traffic stays out of the log.
function toText(buf, len) {
  const bytes = new Uint8Array(buf.readByteArray(len));
  let out = '';
  for (let i = 0; i < bytes.length; i++) {
    const c = bytes[i];
    out += (c >= 0x20 && c < 0x7f) || c === 0x0a || c === 0x0d ? String.fromCharCode(c) : '.';
  }
  return out;
}
function looksLikeLogin(text) {
  return text.indexOf('/v12.') !== -1 && text.indexOf('login') !== -1 &&
         text.indexOf('rangers-api') !== -1;
}
function hook(name) {
  const addr = Module.findExportByName(null, name);   // search every loaded module
  if (!addr) { console.log('[dump_login] ' + name + ' not found'); return false; }
  Interceptor.attach(addr, {
    onEnter(args) {
      const len = args[2].toInt32();
      if (len <= 0 || len > 65536) return;
      const text = toText(args[1], len);
      if (looksLikeLogin(text) || text.indexOf('X-LINEGAME-APPSECRET') !== -1) {
        console.log('=== ' + name + ' ' + len + ' bytes ===');
        console.log(text);
        console.log('=== end ===');
      }
    }
  });
  console.log('[dump_login] hooked ' + name + ' @ ' + addr);
  return true;
}
setImmediate(function () {
  const ok = hook('SSL_write');
  if (!ok) console.log('[dump_login] SSL_write missing - the app may statically link a renamed BoringSSL; list exports with Process.enumerateModules() and adjust.');
});
