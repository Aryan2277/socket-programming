const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

const app = express();
const server = http.createServer(app);

const io = new Server(server, {
  cors: { origin: '*', methods: ['GET', 'POST'] },
  maxHttpBufferSize: 10 * 1024 * 1024
});

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// ── Simple JSON file-based database (no compilation needed!) ──────────────
const DB_FILE = path.join(__dirname, 'chat_history.json');

function loadDB() {
  if (!fs.existsSync(DB_FILE)) return { messages: [] };
  try { return JSON.parse(fs.readFileSync(DB_FILE, 'utf8')); }
  catch { return { messages: [] }; }
}

function saveDB(data) {
  fs.writeFileSync(DB_FILE, JSON.stringify(data, null, 2));
}

function saveMessage(msg) {
  const db = loadDB();
  msg.id = crypto.randomUUID();
  msg.created_at = new Date().toISOString();
  db.messages.push(msg);
  // Keep max 10000 messages
  if (db.messages.length > 10000) db.messages = db.messages.slice(-10000);
  saveDB(db);
  return msg;
}

function getHistory(room, limit = 50) {
  const db = loadDB();
  return db.messages
    .filter(m => m.room === room)
    .slice(-limit);
}

function searchMessages(room, sender, from, to) {
  const db = loadDB();
  return db.messages.filter(m => {
    const date = m.created_at ? m.created_at.split('T')[0] : '';
    return m.room === room &&
      (!sender || m.sender.toLowerCase().includes(sender.toLowerCase())) &&
      (!from || date >= from) &&
      (!to || date <= to);
  }).slice(-100);
}

function getRoomStats(room) {
  const db = loadDB();
  const msgs = db.messages.filter(m => m.room === room);
  const senders = [...new Set(msgs.map(m => m.sender))];
  const files = msgs.filter(m => m.type === 'file');
  return {
    total: msgs.length,
    unique_users: senders.length,
    files_shared: files.length,
    first_message: msgs[0]?.created_at || null,
    last_message: msgs[msgs.length-1]?.created_at || null
  };
}

// ── File storage ───────────────────────────────────────────────────────────
const FILES_DIR = path.join(__dirname, 'uploads');
if (!fs.existsSync(FILES_DIR)) fs.mkdirSync(FILES_DIR);

const storage = multer.diskStorage({
  destination: FILES_DIR,
  filename: (req, file, cb) => cb(null, `${Date.now()}_${file.originalname}`)
});
const upload = multer({ storage, limits: { fileSize: 10 * 1024 * 1024 } });
app.use('/files', express.static(FILES_DIR));

// ── REST API ───────────────────────────────────────────────────────────────
app.post('/upload', upload.single('file'), (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file' });
  res.json({
    filename: req.file.originalname,
    fileId: req.file.filename,
    url: `/files/${req.file.filename}`,
    size: req.file.size
  });
});

app.get('/api/history/:room', (req, res) => {
  const limit = Math.min(parseInt(req.query.limit) || 50, 200);
  const msgs = getHistory(req.params.room, limit);
  res.json({ room: req.params.room, messages: msgs, count: msgs.length });
});

app.get('/api/search/:room', (req, res) => {
  const msgs = searchMessages(
    req.params.room,
    req.query.sender || '',
    req.query.from || '',
    req.query.to || ''
  );
  res.json({ room: req.params.room, messages: msgs, count: msgs.length });
});

app.get('/api/stats/:room', (req, res) => {
  res.json(getRoomStats(req.params.room));
});

// ── State ──────────────────────────────────────────────────────────────────
const rooms = {};
const users = {};

function getTimestamp() {
  return new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}
function getRoomMembers(room) {
  if (!rooms[room]) return [];
  return Array.from(rooms[room].members.values());
}

// ── Socket.io ──────────────────────────────────────────────────────────────
io.on('connection', (socket) => {
  console.log(`[+] Connected: ${socket.id}`);

  socket.on('join', ({ username, room, password }) => {
    if (!rooms[room]) rooms[room] = { password, members: new Map() };
    if (rooms[room].password !== password) {
      socket.emit('error', { message: 'Wrong room password!' });
      return;
    }

    const prev = users[socket.id];
    if (prev) {
      socket.leave(prev.room);
      if (rooms[prev.room]) {
        rooms[prev.room].members.delete(socket.id);
        io.to(prev.room).emit('system', { message: `👋 ${prev.username} left.`, timestamp: getTimestamp() });
        io.to(prev.room).emit('members', getRoomMembers(prev.room));
      }
    }

    socket.join(room);
    rooms[room].members.set(socket.id, username);
    users[socket.id] = { username, room };

    const history = getHistory(room, 50);
    socket.emit('joined', {
      room, members: getRoomMembers(room),
      message: `🔐 Connected! Room "${room}" is AES-256 encrypted.`,
      history
    });

    socket.to(room).emit('system', { message: `🔐 ${username} joined.`, timestamp: getTimestamp() });
    io.to(room).emit('members', getRoomMembers(room));
    console.log(`[AUTH] ${username} → room '${room}'`);
  });

  socket.on('message', ({ message, encrypted }) => {
    const user = users[socket.id];
    if (!user) return;
    const ts = getTimestamp();
    saveMessage({ room: user.room, sender: user.username, message, encrypted: encrypted ? 1 : 0, type: 'text', timestamp: ts });
    const packet = { sender: user.username, message, encrypted, timestamp: ts, id: crypto.randomUUID() };
    socket.to(user.room).emit('message', packet);
    socket.emit('message', { ...packet, own: true });
  });

  socket.on('file_shared', ({ filename, fileId, url, size }) => {
    const user = users[socket.id];
    if (!user) return;
    const ts = getTimestamp();
    saveMessage({ room: user.room, sender: user.username, message: filename, encrypted: 0, type: 'file', filename, file_url: url, file_size: size, timestamp: ts });
    io.to(user.room).emit('file_shared', { sender: user.username, filename, fileId, url, size, timestamp: ts });
  });

  socket.on('typing', ({ isTyping }) => {
    const user = users[socket.id];
    if (!user) return;
    socket.to(user.room).emit('typing', { username: user.username, isTyping });
  });

  socket.on('disconnect', () => {
    const user = users[socket.id];
    if (user) {
      if (rooms[user.room]) {
        rooms[user.room].members.delete(socket.id);
        io.to(user.room).emit('system', { message: `❌ ${user.username} disconnected.`, timestamp: getTimestamp() });
        io.to(user.room).emit('members', getRoomMembers(user.room));
      }
      delete users[socket.id];
    }
    console.log(`[-] Disconnected: ${socket.id}`);
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log('═══════════════════════════════════════════════');
  console.log('  🔐 SecureChat Web Server');
  console.log(`  Running on http://localhost:${PORT}`);
  console.log('  History saved to chat_history.json');
  console.log('═══════════════════════════════════════════════');
});
