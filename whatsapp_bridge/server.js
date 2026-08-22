/**
 * Athena WhatsApp bridge — Baileys on 127.0.0.1 only.
 * Auth + QR under memory/whatsapp_baileys/ (passed via AUTH_DIR).
 */
"use strict";

const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawnSync } = require("child_process");
const express = require("express");
const QRCode = require("qrcode");
const pino = require("pino");

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  jidNormalizedUser,
} = require("@whiskeysockets/baileys");

const HOST = "127.0.0.1";
const PORT = Number(process.env.WA_BRIDGE_PORT || 8765);
const AUTH_DIR =
  process.env.AUTH_DIR ||
  path.join(__dirname, "..", "memory", "whatsapp_baileys");
const QR_PATH = path.join(AUTH_DIR, "qr.png");
const EVENT_TTL_MS = 5 * 60 * 1000;
const EVENT_MAX = 100;
const MSG_PER_CHAT = 40;
const MEDIA_MAX_BYTES = 64 * 1024 * 1024;
const INDEX_FILE = path.join(AUTH_DIR, "name_index.json");
const RANK_FILE = path.join(AUTH_DIR, "name_rank.json");
const BOOT_ID = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

fs.mkdirSync(AUTH_DIR, { recursive: true });

const log = pino({ level: process.env.WA_LOG_LEVEL || "warn" });

let sock = null;
let state = "disconnected"; // qr | connecting | connected | disconnected
let lastQrAt = 0;
let lastQrPng = ""; // base64 PNG so the HUD never has to lock qr.png
let sockGen = 0;
let pairing = false;
let eventSeq = 0;
const events = []; // {seq, id, jid, lid, pn, name, text, isGroup, ts, source}
const nameIndex = new Map(); // jid -> display name
const nameRank = new Map(); // jid -> 3 book/contact, 2 chat, 1 pushName
const jidAliases = new Map(); // lid <-> phone jid
const messagesByChat = new Map(); // jid -> last messages
const chatsIndex = new Map(); // jid -> {jid, name, unreadCount, preview, lastTs}

function loadNameIndex() {
  try {
    if (!fs.existsSync(INDEX_FILE)) return;
    const raw = JSON.parse(fs.readFileSync(INDEX_FILE, "utf8"));
    for (const [jid, name] of Object.entries(raw || {})) {
      if (jid && name) nameIndex.set(jid, String(name));
    }
  } catch {}
  try {
    if (!fs.existsSync(RANK_FILE)) return;
    const raw = JSON.parse(fs.readFileSync(RANK_FILE, "utf8"));
    for (const [jid, rank] of Object.entries(raw || {})) {
      if (jid) nameRank.set(jid, Number(rank) || 1);
    }
  } catch {}
}

function saveNameIndex() {
  try {
    const obj = Object.fromEntries(nameIndex.entries());
    fs.writeFileSync(INDEX_FILE, JSON.stringify(obj, null, 2));
  } catch {}
  try {
    const obj = Object.fromEntries(nameRank.entries());
    fs.writeFileSync(RANK_FILE, JSON.stringify(obj, null, 2));
  } catch {}
}

loadNameIndex();
setInterval(saveNameIndex, 20_000);

function pushEvent(ev) {
  eventSeq += 1;
  const row = { seq: eventSeq, source: "baileys", ...ev };
  events.push(row);
  const cutoff = Date.now() - EVENT_TTL_MS;
  while (events.length > EVENT_MAX || (events[0] && events[0].ts * 1000 < cutoff)) {
    if (!events.length) break;
    if (events.length > EVENT_MAX || events[0].ts * 1000 < cutoff) events.shift();
    else break;
  }
  return row;
}

function extractText(msg) {
  if (!msg) return "";
  const m = msg.message || {};
  if (m.conversation) return m.conversation;
  if (m.extendedTextMessage?.text) return m.extendedTextMessage.text;
  if (m.imageMessage?.caption) return m.imageMessage.caption;
  if (m.videoMessage?.caption) return m.videoMessage.caption;
  if (m.documentMessage?.caption) return m.documentMessage.caption;
  if (m.audioMessage) return m.audioMessage.ptt ? "[voice note]" : "[audio]";
  if (m.stickerMessage) return "[sticker]";
  if (m.buttonsResponseMessage?.selectedDisplayText)
    return m.buttonsResponseMessage.selectedDisplayText;
  if (m.listResponseMessage?.title) return m.listResponseMessage.title;
  if (m.templateButtonReplyMessage?.selectedDisplayText)
    return m.templateButtonReplyMessage.selectedDisplayText;
  return "";
}

function scoreName(query, candidate) {
  const a = String(query || "")
    .toLowerCase()
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const b = String(candidate || "")
    .toLowerCase()
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!a || !b) return 0;
  if (a === b) return 1;
  if (b.includes(a) || a.includes(b)) return 0.9;
  const ta = new Set(a.split(" ").filter((t) => t.length > 1));
  const tb = new Set(b.split(" ").filter((t) => t.length > 1));
  if (!ta.size || !tb.size) return 0;
  let inter = 0;
  for (const t of ta) if (tb.has(t)) inter += 1;
  const union = ta.size + tb.size - inter;
  return union ? inter / union : 0;
}

function storeKey(jid) {
  if (!jid) return "";
  if (String(jid).endsWith("@g.us") || String(jid).endsWith("@lid")) return String(jid);
  try {
    return jidNormalizedUser(jid);
  } catch {
    return String(jid);
  }
}

function sendJid(jid) {
  if (!jid) return jid;
  if (String(jid).endsWith("@g.us") || String(jid).endsWith("@lid")) {
    return String(jid);
  }
  return jidNormalizedUser(jid);
}

function rememberAlias(a, b) {
  if (!a || !b || a === b) return;
  const ka = storeKey(a);
  const kb = storeKey(b);
  if (!ka || !kb || ka === kb) return;
  jidAliases.set(ka, kb);
  jidAliases.set(kb, ka);
}

function isJunkName(name) {
  const s = String(name || "").trim();
  if (!s) return true;
  if (/^[.\-_~*,]+$/.test(s)) return true;
  if (/^you$/i.test(s)) return true;
  return false;
}

function rememberName(jid, name, rank) {
  if (!jid || !name) return;
  const label = String(name).trim();
  if (!label || isJunkName(label)) return;
  const k = storeKey(jid);
  const prev = nameRank.get(k) || 0;
  if (rank < prev) return;
  if (rank === prev && nameIndex.has(k)) return;
  nameIndex.set(k, label);
  nameRank.set(k, rank);
}

function lookupName(jid, fallback) {
  const k = storeKey(jid);
  return (
    nameIndex.get(k) ||
    nameIndex.get(jidAliases.get(k) || "") ||
    fallback ||
    (jid ? String(jid).split("@")[0] : "") ||
    "Unknown"
  );
}

function splitLidPn(msg) {
  const remote = String(msg?.key?.remoteJid || "");
  const alt = String(msg?.key?.remoteJidAlt || "");
  let lid = "";
  let pn = "";
  for (const v of [remote, alt]) {
    if (v.endsWith("@lid") && !lid) lid = v;
    if (v.includes("@s.whatsapp.net") && !pn) pn = v;
  }
  const jid = pn || remote || alt;
  if (lid && pn) rememberAlias(lid, pn);
  return { jid, lid, pn, remote };
}

function chatKeys(jid) {
  const k = storeKey(jid);
  const keys = new Set();
  if (k) keys.add(k);
  if (jid && jid !== k) keys.add(String(jid));
  const alt = jidAliases.get(k);
  if (alt) keys.add(storeKey(alt));
  return keys;
}

function storeChatMessage(jid, row) {
  const k = storeKey(jid);
  if (!k) return;
  let arr = messagesByChat.get(k) || [];
  if (row.id && arr.some((m) => m.id === row.id)) return;
  arr.push(row);
  if (arr.length > MSG_PER_CHAT) arr = arr.slice(-MSG_PER_CHAT);
  messagesByChat.set(k, arr);
}

function messagesFor(jid) {
  const merged = [];
  const seen = new Set();
  for (const k of chatKeys(jid)) {
    for (const m of messagesByChat.get(k) || []) {
      const id = m.id || `${m.ts}:${m.text}`;
      if (seen.has(id)) continue;
      seen.add(id);
      merged.push(m);
    }
  }
  merged.sort((a, b) => (a.ts || 0) - (b.ts || 0));
  return merged.slice(-MSG_PER_CHAT);
}

function touchChat(jid, patch) {
  const k = storeKey(jid);
  if (!k) return;
  const prev = chatsIndex.get(k) || {
    jid: k,
    name: "",
    unreadCount: 0,
    preview: "",
    lastTs: 0,
  };
  if (patch.name) prev.name = String(patch.name);
  if (typeof patch.unreadCount === "number") {
    prev.unreadCount = Math.max(0, patch.unreadCount);
  }
  if (typeof patch.deltaUnread === "number") {
    prev.unreadCount = Math.max(0, (prev.unreadCount || 0) + patch.deltaUnread);
  }
  if (patch.preview) prev.preview = String(patch.preview).slice(0, 160);
  if (patch.lastTs) prev.lastTs = patch.lastTs;
  if (!prev.name) prev.name = lookupName(k, k.split("@")[0]);
  prev.jid = k;
  chatsIndex.set(k, prev);
  const alt = jidAliases.get(k);
  if (alt) {
    const other = chatsIndex.get(storeKey(alt));
    if (other) {
      other.unreadCount = prev.unreadCount;
      other.preview = prev.preview;
      other.lastTs = prev.lastTs;
    }
  }
}

function ingestMessage(msg, { notify = false } = {}) {
  if (!msg?.key) return null;
  const fromMe = !!msg.key.fromMe;
  const { jid, lid, pn } = splitLidPn(msg);
  if (!jid || jid === "status@broadcast" || jid.endsWith("@newsletter")) return null;
  const isGroup = String(jid).endsWith("@g.us");
  const text = extractText(msg).trim();
  const body = text || (msg.message ? "[media/non-text message]" : "");
  if (!body) return null;
  const ts = Math.floor(Number(msg.messageTimestamp) || Date.now() / 1000);
  const senderJid = isGroup
    ? msg.key.participantAlt || msg.key.participant || jid
    : pn || jid;
  // Outgoing messages carry OUR pushName. Never attach it to the other chat.
  if (!isGroup && !fromMe && msg.pushName && !isJunkName(msg.pushName)) {
    rememberName(jid, msg.pushName, 1);
    if (pn) rememberName(pn, msg.pushName, 1);
    if (lid) rememberName(lid, msg.pushName, 1);
  }
  const name = isGroup
    ? lookupName(jid, msg.pushName || jid)
    : lookupName(
        jid,
        isJunkName(msg.pushName) ? "" : (msg.pushName || msg.verifiedBizName || "")
      );
  const row = {
    id: msg.key.id || `seq-${eventSeq + 1}`,
    jid,
    lid: lid || "",
    pn: pn || "",
    senderJid,
    name: String(name),
    text: body,
    fromMe,
    isGroup,
    ts,
    key: {
      remoteJid: msg.key.remoteJid,
      id: msg.key.id,
      fromMe,
      participant: msg.key.participant,
    },
  };
  storeChatMessage(jid, row);
  if (pn && pn !== jid) storeChatMessage(pn, row);
  touchChat(jid, {
    name: isGroup ? name : lookupName(jid, name),
    preview: body,
    lastTs: ts,
    deltaUnread: notify && !fromMe ? 1 : 0,
  });
  return row;
}

function mimeOf(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const map = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg; codecs=opus",
    ".opus": "audio/ogg; codecs=opus",
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
  };
  return map[ext] || "application/octet-stream";
}

function looksLikeOgg(filePath) {
  try {
    const fd = fs.openSync(filePath, "r");
    const buf = Buffer.alloc(4);
    fs.readSync(fd, buf, 0, 4, 0);
    fs.closeSync(fd);
    return buf.toString("ascii") === "OggS";
  } catch {
    return false;
  }
}

function findFfmpeg() {
  const roots = [
    path.join(__dirname, "..", "tools", "ffmpeg"),
    path.join(process.cwd(), "tools", "ffmpeg"),
  ];
  for (const dir of roots) {
    for (const name of ["ffmpeg.exe", "ffmpeg"]) {
      const p = path.join(dir, name);
      if (fs.existsSync(p)) return p;
    }
  }
  if (process.env.FFMPEG_PATH && fs.existsSync(process.env.FFMPEG_PATH)) {
    return process.env.FFMPEG_PATH;
  }
  return "";
}

function convertToVoiceOgg(src) {
  const ffmpeg = findFfmpeg();
  if (!ffmpeg) {
    console.error("[WA Bridge] ffmpeg not found — cannot make a WhatsApp voice note");
    return "";
  }
  const dest = path.join(os.tmpdir(), `athena-wa-voice-${Date.now()}.ogg`);
  const r = spawnSync(
    ffmpeg,
    [
      "-y",
      "-i",
      src,
      "-vn",
      "-map_metadata",
      "-1",
      "-ac",
      "1",
      "-ar",
      "48000",
      "-c:a",
      "libopus",
      "-b:a",
      "24k",
      "-vbr",
      "on",
      "-application",
      "voip",
      "-f",
      "ogg",
      dest,
    ],
    { encoding: "utf8", windowsHide: true }
  );
  if (r.status === 0 && fs.existsSync(dest) && fs.statSync(dest).size > 64 && looksLikeOgg(dest)) {
    return dest;
  }
  const err = (r.stderr || r.stdout || "").trim().slice(-500);
  console.error("[WA Bridge] opus convert failed:", err || `status=${r.status}`);
  try {
    if (fs.existsSync(dest)) fs.unlinkSync(dest);
  } catch {}
  return "";
}

function mediaKindOf(filePath, forced, ptt) {
  if (forced) return String(forced).toLowerCase();
  if (ptt) return "audio";
  const ext = path.extname(filePath).toLowerCase();
  if ([".jpg", ".jpeg", ".png", ".gif", ".webp"].includes(ext)) return "image";
  if ([".mp4", ".mov", ".mkv", ".webm"].includes(ext)) return "video";
  if ([".mp3", ".m4a", ".ogg", ".opus", ".wav"].includes(ext)) return "audio";
  return "document";
}

function buildMediaContent(filePath, { caption, ptt, mediaType }) {
  const kind = mediaKindOf(filePath, mediaType, ptt);
  const mime = mimeOf(filePath);
  const buf = fs.readFileSync(filePath);
  if (kind === "image") return { image: buf, caption: caption || undefined, mimetype: mime };
  if (kind === "video") return { video: buf, caption: caption || undefined, mimetype: mime };
  if (kind === "audio" || kind === "voice") {
    const opus = looksLikeOgg(filePath);
    const asPtt = !!(ptt || kind === "voice") && opus;
    return {
      audio: buf,
      mimetype: asPtt ? "audio/ogg; codecs=opus" : mime,
      ptt: asPtt,
    };
  }
  return {
    document: buf,
    fileName: path.basename(filePath),
    mimetype: mime,
    caption: caption || undefined,
  };
}

async function refreshGroups() {
  if (!sock) return;
  try {
    const groups = await sock.groupFetchAllParticipating();
    let n = 0;
    for (const [gjid, meta] of Object.entries(groups || {})) {
      const subject = meta?.subject;
      if (gjid && subject) {
        rememberName(String(gjid), String(subject), 3);
        n += 1;
      }
    }
    saveNameIndex();
    console.log(`[WA Bridge] indexed ${n} groups`);
  } catch (e) {
    console.error("[WA Bridge] group fetch failed:", e.message);
  }
}

async function writeQrPng(qr) {
  lastQrAt = Date.now();
  const buf = await QRCode.toBuffer(qr, { width: 360, margin: 2, type: "png" });
  lastQrPng = buf.toString("base64");
  const tmp = `${QR_PATH}.tmp`;
  try {
    fs.writeFileSync(tmp, buf);
    try {
      if (fs.existsSync(QR_PATH)) fs.unlinkSync(QR_PATH);
    } catch {}
    try {
      fs.renameSync(tmp, QR_PATH);
    } catch {
      try {
        fs.copyFileSync(tmp, QR_PATH);
      } catch {}
    }
  } catch (e) {
    console.error("[WA Bridge] QR file write failed (HUD can still use in-memory PNG):", e.message);
  } finally {
    try {
      if (fs.existsSync(tmp)) fs.unlinkSync(tmp);
    } catch {}
  }
}

function clearSessionFiles() {
  const keep = new Set(["name_index.json", "name_rank.json", "qr.png", "qr.png.tmp"]);
  let names = [];
  try {
    names = fs.readdirSync(AUTH_DIR);
  } catch {
    return;
  }
  for (const name of names) {
    if (keep.has(name)) continue;
    try {
      fs.unlinkSync(path.join(AUTH_DIR, name));
    } catch {}
  }
}

async function stopSocket() {
  sockGen += 1;
  const old = sock;
  sock = null;
  if (old) {
    try {
      old.ev.removeAllListeners();
    } catch {}
    try {
      await old.end(undefined);
    } catch {}
    try {
      old.ws?.close();
    } catch {}
  }
}

async function forcePair() {
  await stopSocket();
  clearSessionFiles();
  lastQrPng = "";
  lastQrAt = 0;
  try {
    if (fs.existsSync(QR_PATH)) fs.unlinkSync(QR_PATH);
  } catch {}
  state = "connecting";
  await startSocket();
}

async function startSocket() {
  const gen = ++sockGen;
  state = "connecting";
  const { state: authState, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  let version;
  try {
    const v = await fetchLatestBaileysVersion();
    version = v.version;
  } catch {
    version = undefined;
  }

  sock = makeWASocket({
    version,
    auth: {
      creds: authState.creds,
      keys: makeCacheableSignalKeyStore(authState.keys, log),
    },
    logger: log,
    printQRInTerminal: false,
    syncFullHistory: false,
    markOnlineOnConnect: false,
    generateHighQualityLinkPreview: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("contacts.upsert", (list) => {
    for (const c of list || []) {
      if (!c?.id) continue;
      if (c.name) rememberName(c.id, c.name, 3);
      else if (c.notify) rememberName(c.id, c.notify, 1);
      else if (c.verifiedName) rememberName(c.id, c.verifiedName, 2);
    }
  });
  sock.ev.on("contacts.update", (list) => {
    for (const c of list || []) {
      if (!c?.id) continue;
      if (c.name) rememberName(c.id, c.name, 3);
      else if (c.notify) rememberName(c.id, c.notify, 1);
      else if (c.verifiedName) rememberName(c.id, c.verifiedName, 2);
    }
  });
  sock.ev.on("chats.upsert", (list) => {
    for (const ch of list || []) {
      if (!ch?.id) continue;
      if (ch.name) rememberName(ch.id, ch.name, 2);
      touchChat(ch.id, {
        name: ch.name || lookupName(ch.id, ""),
        unreadCount: typeof ch.unreadCount === "number" ? ch.unreadCount : undefined,
        preview: ch.conversationTimestamp ? undefined : undefined,
        lastTs: ch.conversationTimestamp
          ? Math.floor(Number(ch.conversationTimestamp))
          : undefined,
      });
    }
  });
  sock.ev.on("chats.update", (list) => {
    for (const ch of list || []) {
      if (!ch?.id) continue;
      if (ch.name) rememberName(ch.id, ch.name, 2);
      touchChat(ch.id, {
        name: ch.name || undefined,
        unreadCount: typeof ch.unreadCount === "number" ? ch.unreadCount : undefined,
      });
    }
  });
  sock.ev.on("groups.upsert", (list) => {
    for (const g of list || []) {
      if (!g?.id || !g.subject) continue;
      rememberName(String(g.id), String(g.subject), 3);
    }
    saveNameIndex();
  });
  sock.ev.on("groups.update", (list) => {
    for (const g of list || []) {
      if (!g?.id || !g.subject) continue;
      rememberName(String(g.id), String(g.subject), 3);
    }
    saveNameIndex();
  });

  sock.ev.on("messaging-history.set", ({ messages, chats }) => {
    try {
      for (const ch of chats || []) {
        if (!ch?.id) continue;
        if (ch.name) rememberName(ch.id, ch.name, 2);
        touchChat(ch.id, {
          name: ch.name || lookupName(ch.id, ""),
          unreadCount: typeof ch.unreadCount === "number" ? ch.unreadCount : undefined,
          lastTs: ch.conversationTimestamp
            ? Math.floor(Number(ch.conversationTimestamp))
            : undefined,
        });
      }
      for (const msg of messages || []) {
        ingestMessage(msg, { notify: false });
      }
    } catch (e) {
      console.error("[WA Bridge] history set error:", e.message);
    }
  });

  sock.ev.on("connection.update", async (update) => {
    if (gen !== sockGen) return;
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      state = "qr";
      try {
        await writeQrPng(qr);
        console.log(`[WA Bridge] QR ready (${lastQrPng.length} b64 chars)`);
      } catch (e) {
        console.error("[WA Bridge] QR encode failed:", e.message);
      }
    }
    if (connection === "open") {
      state = "connected";
      lastQrPng = "";
      try {
        if (fs.existsSync(QR_PATH)) fs.unlinkSync(QR_PATH);
      } catch {}
      console.log("[WA Bridge] connected");
      refreshGroups().catch(() => {});
    } else if (connection === "close") {
      state = "disconnected";
      const code = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = code !== DisconnectReason.loggedOut;
      console.log(`[WA Bridge] closed code=${code} reconnect=${shouldReconnect}`);
      if (sockGen !== gen) return;
      sock = null;
      if (shouldReconnect) {
        setTimeout(() => {
          if (sockGen !== gen) return;
          startSocket().catch((e) =>
            console.error("[WA Bridge] restart failed:", e.message)
          );
        }, 2000);
      } else {
        console.log("[WA Bridge] logged out — delete auth folder and rescan QR");
      }
    } else if (connection === "connecting") {
      state = "connecting";
    }
  });

  sock.ev.on("messages.upsert", ({ messages, type }) => {
    if (!messages?.length) return;
    if (type && type !== "notify" && type !== "append") return;
    const notify = !type || type === "notify";
    for (const msg of messages) {
      try {
        if (!msg?.key) continue;
        const row = ingestMessage(msg, { notify });
        if (!row || row.fromMe) continue;
        if (!notify) continue;
        const ev = pushEvent({
          id: row.id,
          jid: row.jid,
          lid: row.lid,
          pn: row.pn,
          name: row.name,
          text: row.text,
          isGroup: row.isGroup,
          ts: row.ts,
        });
        console.log(
          `[WA Bridge] inbound seq=${ev.seq} from=${row.name} type=${type || "?"} text=${row.text.slice(0, 40)}`
        );
      } catch (e) {
        console.error("[WA Bridge] upsert error:", e.message);
      }
    }
  });
}

function requireConnected(res) {
  if (!sock || state !== "connected") {
    res.status(503).json({
      ok: false,
      error: state === "qr"
        ? `WhatsApp not linked. Scan the QR at ${QR_PATH}`
        : `WhatsApp bridge not connected (state=${state}).`,
      state,
      qrPath: state === "qr" && fs.existsSync(QR_PATH) ? QR_PATH : undefined,
    });
    return false;
  }
  return true;
}

const app = express();
app.use(express.json({ limit: "256kb" }));

app.get("/status", (_req, res) => {
  res.json({
    ok: true,
    state,
    bootId: BOOT_ID,
    latest: eventSeq,
    qrPath: state === "qr" && fs.existsSync(QR_PATH) ? QR_PATH : undefined,
    qrPng: state === "qr" && lastQrPng ? lastQrPng : undefined,
    qrAgeMs: state === "qr" ? Date.now() - lastQrAt : undefined,
    port: PORT,
  });
});

app.post("/pair", async (_req, res) => {
  if (pairing) {
    res.json({ ok: true, state, pending: true });
    return;
  }
  pairing = true;
  try {
    await forcePair();
    res.json({ ok: true, state });
  } catch (e) {
    console.error("[WA Bridge] /pair failed:", e.message);
    res.status(500).json({ ok: false, error: e.message, state });
  } finally {
    pairing = false;
  }
});

app.post("/resolve", async (req, res) => {
  if (!requireConnected(res)) return;
  const name = String(req.body?.name || "").trim();
  const kind = String(req.body?.kind || "any").toLowerCase(); // any | group | contact
  if (!name) {
    res.status(400).json({ ok: false, error: "name required" });
    return;
  }

  const digits = name.replace(/\D/g, "");
  if (
    kind !== "group" &&
    digits.length >= 8 &&
    digits.length <= 15 &&
    /^[\d\s+\-()]+$/.test(name.trim())
  ) {
    const jid = jidNormalizedUser(`${digits}@s.whatsapp.net`);
    res.json({
      ok: true,
      jid,
      name: lookupName(jid, digits),
      isGroup: false,
    });
    return;
  }

  try {
    const wantsGroup =
      kind === "group" || /\bgroup\b/i.test(name) || name.trim().endsWith(" group");
    if (wantsGroup || kind === "any") {
      await refreshGroups();
    }

    const candidates = [];
    for (const [jid, label] of nameIndex.entries()) {
      candidates.push({
        jid,
        name: String(label),
        isGroup: String(jid).endsWith("@g.us"),
      });
    }

    let best = null;
    let bestScore = 0;
    const seen = new Set();
    const query = name.replace(/\bgroup\b/gi, " ").replace(/\s+/g, " ").trim();

    for (const row of candidates) {
      if (!row.jid || seen.has(row.jid)) continue;
      seen.add(row.jid);
      if (kind === "group" && !row.isGroup) continue;
      if (kind === "contact" && row.isGroup) continue;

      let sc = Math.max(scoreName(name, row.name), scoreName(query, row.name));
      if (wantsGroup && row.isGroup) sc += 0.15;
      if (!wantsGroup && kind === "any" && !row.isGroup) sc += 0.05;

      if (sc > bestScore) {
        bestScore = sc;
        best = row;
      }
    }

    if (!best || bestScore < 0.35) {
      res.status(404).json({
        ok: false,
        error: wantsGroup
          ? `No WhatsApp group matched '${name}'. Check the exact group name.`
          : `No WhatsApp contact or group matched '${name}'. Try the full name, group name, or phone number with country code.`,
      });
      return;
    }

    res.json({
      ok: true,
      jid: sendJid(best.jid),
      name: best.name,
      score: bestScore,
      isGroup: !!best.isGroup,
    });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post("/send", async (req, res) => {
  if (!requireConnected(res)) return;
  const jid = String(req.body?.jid || "").trim();
  const text = String(req.body?.text || "");
  const mediaPath = String(req.body?.mediaPath || "").trim();
  const caption = String(req.body?.caption || "");
  const mediaType = String(req.body?.mediaType || "").trim();
  const ptt = Boolean(req.body?.ptt);
  if (!jid || (!text && !mediaPath)) {
    res.status(400).json({ ok: false, error: "jid and text or mediaPath required" });
    return;
  }
  try {
    const dest = sendJid(jid);
    let content;
    let storedText = text;
    if (mediaPath) {
      if (!fs.existsSync(mediaPath)) {
        res.status(400).json({ ok: false, error: "media file not found" });
        return;
      }
      const st = fs.statSync(mediaPath);
      if (!st.isFile() || st.size <= 0) {
        res.status(400).json({ ok: false, error: "media path is not a file" });
        return;
      }
      if (st.size > MEDIA_MAX_BYTES) {
        res.status(400).json({
          ok: false,
          error: `File is too large (${Math.round(st.size / 1048576)} MB). Max is 64 MB.`,
        });
        return;
      }
      let sendPath = mediaPath;
      let sendPtt = ptt || mediaType === "voice";
      if (sendPtt && !looksLikeOgg(sendPath)) {
        const converted = convertToVoiceOgg(sendPath);
        if (converted) {
          sendPath = converted;
          sendPtt = true;
        } else {
          sendPtt = false;
        }
      }
      content = buildMediaContent(sendPath, {
        caption: caption || text,
        ptt: sendPtt,
        mediaType: sendPtt ? "audio" : mediaType,
      });
      storedText = caption || text || `[${mediaKindOf(mediaPath, mediaType, ptt)}]`;
    } else {
      content = { text };
    }
    await sock.sendMessage(dest, content);
    const ts = Math.floor(Date.now() / 1000);
    storeChatMessage(dest, {
      id: `out-${ts}`,
      jid: dest,
      name: "You",
      text: storedText,
      fromMe: true,
      isGroup: String(dest).endsWith("@g.us"),
      ts,
    });
    touchChat(dest, { preview: storedText, lastTs: ts });
    res.json({ ok: true, jid: dest, sent: true, isGroup: String(dest).endsWith("@g.us") });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.get("/messages", async (req, res) => {
  if (!requireConnected(res)) return;
  const jid = String(req.query.jid || "").trim();
  const limit = Math.min(MSG_PER_CHAT, Math.max(1, Number(req.query.limit || 15) || 15));
  if (!jid) {
    res.status(400).json({ ok: false, error: "jid required" });
    return;
  }
  let rows = messagesFor(jid);
  if (rows.length < Math.min(limit, 3) && sock) {
    const oldest = rows[0];
    if (oldest?.key?.id) {
      try {
        await sock.fetchMessageHistory(
          limit,
          oldest.key,
          oldest.ts || Math.floor(Date.now() / 1000)
        );
        rows = messagesFor(jid);
      } catch (e) {
        console.error("[WA Bridge] fetchMessageHistory:", e.message);
      }
    }
  }
  const out = rows.slice(-limit).map((m) => ({
    id: m.id,
    ts: m.ts,
    fromMe: !!m.fromMe,
    name: m.fromMe ? "You" : lookupName(m.senderJid || m.jid, m.name),
    text: m.text,
    jid: m.jid,
    senderJid: m.senderJid || m.jid,
    isGroup: !!m.isGroup,
  }));
  res.json({
    ok: true,
    jid,
    messages: out,
    limited: rows.length === 0,
  });
});

app.get("/chats", (req, res) => {
  if (!requireConnected(res)) return;
  const unreadOnly = String(req.query.unread || "") === "1";
  let rows = [...chatsIndex.values()];
  if (unreadOnly) {
    rows = rows.filter((c) => (c.unreadCount || 0) > 0);
  }
  rows.sort((a, b) => (b.lastTs || 0) - (a.lastTs || 0));
  const chats = rows.slice(0, 30).map((c) => ({
    jid: c.jid,
    name: lookupName(c.jid, c.name || c.jid),
    unreadCount: c.unreadCount || 0,
    preview: c.preview || "",
    lastTs: c.lastTs || 0,
    isGroup: String(c.jid).endsWith("@g.us"),
  }));
  res.json({ ok: true, chats });
});

app.get("/events", (req, res) => {
  let since = Number(req.query.since || 0);
  const cutoff = Date.now() - EVENT_TTL_MS;
  let reset = false;
  if (since > eventSeq) {
    since = 0;
    reset = true;
  }
  const out = events.filter(
    (e) => e.seq > since && e.ts * 1000 >= cutoff
  );
  res.json({
    ok: true,
    events: out,
    latest: eventSeq,
    bootId: BOOT_ID,
    reset,
  });
});

app.post("/ack", (req, res) => {
  const ids = Array.isArray(req.body?.ids) ? req.body.ids.map(String) : [];
  if (ids.length) {
    const drop = new Set(ids);
    for (let i = events.length - 1; i >= 0; i--) {
      if (drop.has(String(events[i].id))) events.splice(i, 1);
    }
  }
  res.json({ ok: true });
});

app.get("/health", (_req, res) => {
  res.json({ ok: true, state });
});

async function main() {
  await startSocket();
  app.listen(PORT, HOST, () => {
    console.log(`[WA Bridge] listening http://${HOST}:${PORT}`);
    console.log(`[WA Bridge] auth → ${AUTH_DIR}`);
  });
}

main().catch((e) => {
  console.error("[WA Bridge] fatal:", e);
  process.exit(1);
});
