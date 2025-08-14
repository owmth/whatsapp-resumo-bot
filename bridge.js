// bridge.js
import dotenv from 'dotenv'; dotenv.config();

import express from 'express';
import qrcode from 'qrcode-terminal';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = path.dirname(__filename);

// -------- Baileys dynamic loader (compat ESM/CJS/variações) --------
async function loadBaileys() {
  const m = await import('@whiskeysockets/baileys');
  const makeWASocket = m.makeWASocket || m.default?.makeWASocket || m.default;
  return {
    makeWASocket,
    useMultiFileAuthState: m.useMultiFileAuthState || m.default?.useMultiFileAuthState,
    fetchLatestBaileysVersion: m.fetchLatestBaileysVersion || m.default?.fetchLatestBaileysVersion,
    Browsers: m.Browsers || m.default?.Browsers,
    fetchMessagesFromWA: m.fetchMessagesFromWA || m.default?.fetchMessagesFromWA, // <- função de backfill
    _raw: m,
  };
}

// -------- App / ENV --------
const HOST = '127.0.0.1';
const app  = express();
app.use(express.json());

const WEBHOOK_URL  = process.env.WEBHOOK_URL || 'http://127.0.0.1:8000/webhook';
const PORT         = Number(process.env.PORT || 3000);
const PAIR_CODE    = (process.env.PAIR_CODE || '').trim(); // ex: 5511999999999
const ACCESS_TOKEN = (process.env.ACCESS_TOKEN || '').trim();

// -------- Rate limit (token bucket) --------
const buckets = {
  '/to-webhook': { cap: 5, tok: 5, refillMs: 1000, last: Date.now() }, // 5 req/s ao Python
  '/send':       { cap: 2, tok: 2, refillMs: 1000, last: Date.now() }, // 2 msgs/s ao WA
};
function take(key) {
  const b = buckets[key];
  const now = Date.now();
  const elapsed = now - b.last;
  if (elapsed >= b.refillMs) {
    const add = Math.floor(elapsed / b.refillMs) * b.cap;
    b.tok = Math.min(b.cap, (b.tok ?? b.cap) + add);
    b.last = now;
  }
  if (b.tok > 0) { b.tok -= 1; return true; }
  return false;
}

// -------- WA socket --------
let sock;                 // conexão
let fetchMessagesFromWA;  // função de backfill (do módulo)

async function start() {
  const loaded = await loadBaileys();
  console.log('Baileys exports:', Object.keys(loaded._raw));
  console.log('Baileys default:', loaded._raw.default ? Object.keys(loaded._raw.default) : null);
  const { makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, Browsers } = loaded;
  fetchMessagesFromWA = loaded.fetchMessagesFromWA;

  if (typeof makeWASocket !== 'function') {
    console.error('Baileys exports:', Object.keys(loaded._raw), 'default:', loaded._raw.default ? Object.keys(loaded._raw.default) : null);
    throw new Error('makeWASocket não é função (mismatch de import).');
  }

  const { state, saveCreds } = await useMultiFileAuthState(path.join(__dirname, 'auth'));
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    syncFullHistory: false,
    browser: Browsers.ubuntu('Chrome'),
    markOnlineOnConnect: false,
  });

  sock.ev.on('creds.update', saveCreds);

  // Pairing por código (opcional)
  if (PAIR_CODE) {
    try {
      const code = await sock.requestPairingCode(PAIR_CODE);
      console.clear(); console.log('📟 Pairing code:', code);
    } catch (e) { console.error('pairing code error:', e?.message || e); }
  }

  sock.ev.on('connection.update', async ({ qr, connection, lastDisconnect }) => {
    if (qr && !PAIR_CODE) {
      console.clear();
      console.log('📱 Escaneie o QR (WhatsApp > Aparelhos conectados > Conectar um aparelho)');
      qrcode.generate(qr, { small: true });
    }
    if (connection === 'open') {
      console.log(`✅ Conectado. Bridge HTTP em http://${HOST}:${PORT}`);
    }
    if (connection === 'close') {
      const err = lastDisconnect?.error;
      const status = err?.output?.statusCode || err?.data?.statusCode;
      const removed = err?.message?.includes('device_removed') || status === 401;
      console.log('🔌 Conexão fechada. status:', status || '-');

      if (removed) {
        try {
          fs.rmSync(path.join(__dirname, 'auth'), { recursive: true, force: true });
          console.log('🧹 Sessão limpa; rode `node bridge.js` e pareie novamente.');
          process.exit(0);
        } catch (e) { console.error('Erro limpando sessão:', e); }
        return;
      }
      await new Promise(r => setTimeout(r, 2000));
      start().catch(e => {
        console.error('Reinício falhou; tentando em 5s:', e?.message || e);
        setTimeout(() => start().catch(console.error), 5000);
      });
    }
  });

  // Só repassa ao Python quando for COMANDO (!resumo / !status) de QUALQUER grupo
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const m of messages) {
      if (!m.message) continue;
      const chatId = m.key.remoteJid;
      if (!chatId?.endsWith('@g.us')) continue; // grupos apenas

      const text =
        m.message.conversation ||
        m.message.extendedTextMessage?.text ||
        m.message.imageMessage?.caption ||
        m.message.videoMessage?.caption || '';
      if (!text?.trim()) continue;

      const t = text.trim().toLowerCase();
      if (!(t.startsWith('!resumo') || t.startsWith('/resumo') || t.startsWith('!status') || t.startsWith('/status'))) continue;

      let chatName = '';
      try { chatName = (await sock.groupMetadata(chatId))?.subject || ''; } catch {}

      if (!take('/to-webhook')) continue;
      try {
        await fetch(WEBHOOK_URL, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(ACCESS_TOKEN ? { 'x-access-token': ACCESS_TOKEN } : {}),
          },
          body: JSON.stringify({ at: new Date().toISOString(), author: m.pushName || 'alguém', text: text.trim(), chatId, chatName }),
        });
      } catch (e) { console.error('Falha ao chamar webhook:', e?.message || e); }
    }
  });
}

// -------- HTTP API --------

// Enviar mensagem para um grupo específico
app.post('/send', async (req, res) => {
  try {
    if (ACCESS_TOKEN && req.headers['x-access-token'] !== ACCESS_TOKEN)
      return res.status(401).json({ ok: false });
    if (!take('/send')) return res.status(429).json({ ok:false, error:'rate_limited' });

    const chatId = (req.body?.chatId || '').toString();
    const text   = (req.body?.text   || '').toString();
    if (!chatId.endsWith('@g.us')) return res.status(400).json({ ok:false, error:'chatId inválido' });
    if (!text) return res.status(400).json({ ok:false, error:'texto vazio' });

    await sock.sendMessage(chatId, { text });
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ ok:false, error:String(e) }); }
});

// Util
function isoToMs(iso) { return Number(new Date(iso)); }

// Buscar histórico do dia (00:00 → agora) sob demanda
// GET /fetch_today?chatId=...&since=ISO_00:00:00Z&limit=800
app.get('/fetch_today', async (req, res) => {
  try {
    if (ACCESS_TOKEN && req.headers['x-access-token'] !== ACCESS_TOKEN)
      return res.status(401).json({ ok:false });

    const chatId = (req.query.chatId || '').toString();
    const since  = (req.query.since  || '').toString();
    const limit  = Math.min(parseInt(req.query.limit || '800', 10), 3000);
    if (!chatId.endsWith('@g.us')) return res.status(400).json({ ok:false, error:'chatId inválido' });
    if (!since) return res.status(400).json({ ok:false, error:'since obrigatório (ISO)' });

    const sinceMs = isoToMs(since);
    if (typeof fetchMessagesFromWA !== 'function') {
      console.log('Backfill não suportado: fetchMessagesFromWA ausente no módulo.');
      return res.status(501).json({ ok:false, error:'backfill_not_supported' });
    }

    let cursor; let pulled = 0; const out = [];
    while (pulled < limit) {
      // função do módulo: (sock, jid, count, cursor?)
      const batch = await fetchMessagesFromWA(sock, chatId, 50, cursor);
      if (!batch?.length) break;
      pulled += batch.length;

      for (const m of batch) {
        const t =
          m.message?.conversation ||
          m.message?.extendedTextMessage?.text ||
          m.message?.imageMessage?.caption ||
          m.message?.videoMessage?.caption || '';
        const tsMs = (Number(m.messageTimestamp) || 0) * 1000;
        if (!t || !tsMs || tsMs < sinceMs) continue;
        out.push({
          at: new Date(tsMs).toISOString(),
          author: m.pushName || 'alguém',
          text: t.trim(),
          chatId,
          chatName: ''
        });
      }

      // preparar cursor para a "página" anterior
      const oldest = batch[0];
      cursor = { before: { id: oldest.key.id, fromMe: oldest.key.fromMe, participant: oldest.key.participant } };
    }

    // ordem cronológica
    out.sort((a,b)=> new Date(a.at) - new Date(b.at));
    res.json({ ok:true, count: out.length, items: out });
  } catch (e) {
    res.status(500).json({ ok:false, error:String(e) });
  }
});

app.listen(PORT, HOST, () => console.log(`Bridge HTTP on http://${HOST}:${PORT}`));
start().catch(console.error);
