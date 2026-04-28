const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const Database = require('better-sqlite3');

const app = express();
const server = http.createServer(app);

const io = new Server(server, {
  cors: { origin: '*', methods: ['GET', 'POST'] },
  maxHttpBufferSize: 10 * 1024 * 1024
});

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// ── SQLite Database Setup ──────────────────────────────────────────────────
const db = new Database('chat.db');

db.exec(`
  CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    room        TEXT    NOT NULL,
    sender      TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    encrypted   INTEGER NOT NULL DEFAULT 1,
    type        TEXT    NOT NULL DEFAULT 'text',
    filename    TEXT,
    file_url    TEXT,
    file_size   INTEGER,
    timestamp   TEXT    NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  CREATE INDEX IF NOT EXISTS idx_room ON messages(room);
  CREATE INDEX IF NOT EXISTS idx_created ON messages(created_at);
`);

// DB helper functions
const saveMessage = db.prepare(`
  INSERT INTO messages (room, sender, message, encrypted, type, filename, file_url, file_size, timestamp)
  VALUES (@room, @sender, @message, @encrypted, @type, @filename, @file_url, @file_size, @timestamp)
`);

const getHistory = db.prepare(`
  SELECT * FROM messages
  WHERE room = ?
  ORDER BY created_at DESC
  LIMIT ?
`);

const searchMessages = db.prepare(`
  SELECT * FROM messages
  WHERE room = ? AND sender LIKE ? AND created_at >= ? AND created_at <= ?
  ORDER BY created_at DESC
  LIMIT 100
`);

const getStats = db.prepare(`
  SELECT
    COUNT(*) as total,
    COUNT(DISTINCT sender) as unique_users,
    SUM(CASE WHEN type='file' THEN 1 ELSE 0 END) as files_shared,
    MIN(created_at) as first_message,
    MAX(created_at) as last_message
  FROM messages WHERE room = ?
`);

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

// File upload
app.post('/upload', upload.single('file'), (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file' });
  res.json({
    filename: req.file.originalname,
    fileId: req.file.filename,
    url: `/files/${req.file.filename}`,
    size: req.file.size
  });
});

// Get message history for a room
app.get('/api/history/:room', (req, res) => {
  const { room } = req.params;
  const limit = Math.min(parseInt(req.query.limit) || 50, 200);
  const msgs = getHistory.all(room, limit).reverse();
  res.json({ room, messages: msgs, count: msgs.length });
});

// Search messages
app.get('/api/search/:room', (req, res) => {
  const { room } = req.params;
  const sender = `%${req.query.sender || ''}%`;
  const from = req.query.from || '2000-01-01';
  const to   = req.query.to   || '2099-12-31';
  const msgs = searchMessages.all(room, sender, from, to);
  res.json({ room, messages: msgs, count: msgs.length });
});

// Room stats
app.get('/api/stats/:room', (req, res) => {
  const stats = getStats.get(req.params.room);
  res.json(stats);
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
  console.log(`[+] Socket connected: ${socket.id}`);

  socket.on('join', ({ username, room, password }) => {
    if (!rooms[room]) rooms[room] = { password, members: new Map() };

    if (rooms[room].password !== password) {
      socket.emit('error', { message: 'Wrong room password!' });
      return;
    }

    // Leave previous room
    const prev = users[socket.id];
    if (prev) {
      socket.leave(prev.room);
      if (rooms[prev.room]) {
        rooms[prev.room].members.delete(socket.id);
        io.to(prev.room).emit('system', { message: `👋 ${prev.username} left the room.`, timestamp: getTimestamp() });
        io.to(prev.room).emit('members', getRoomMembers(prev.room));
      }
    }

    socket.join(room);
    rooms[room].members.set(socket.id, username);
    users[socket.id] = { username, room };

    // Load last 50 messages from DB
    const history = getHistory.all(room, 50).reverse();

    socket.emit('joined', {
      room,
      members: getRoomMembers(room),
      message: `🔐 Connected! Room "${room}" is AES-256 encrypted.`,
      history
    });

    socket.to(room).emit('system', { message: `🔐 ${username} joined the room.`, timestamp: getTimestamp() });
    io.to(room).emit('members', getRoomMembers(room));

    console.log(`[AUTH] ${username} joined room '${room}'`);
  });

  socket.on('message', ({ message, encrypted }) => {
    const user = users[socket.id];
    if (!user) return;

    const ts = getTimestamp();
    const id = crypto.randomUUID();

    // Save to DB
    saveMessage.run({
      room: user.room,
      sender: user.username,
      message,
      encrypted: encrypted ? 1 : 0,
      type: 'text',
      filename: null,
      file_url: null,
      file_size: null,
      timestamp: ts
    });

    const packet = { sender: user.username, message, encrypted, timestamp: ts, id };
    socket.to(user.room).emit('message', packet);
    socket.emit('message', { ...packet, own: true });
  });

  socket.on('file_shared', ({ filename, fileId, url, size }) => {
    const user = users[socket.id];
    if (!user) return;

    const ts = getTimestamp();

    // Save file message to DB
    saveMessage.run({
      room: user.room,
      sender: user.username,
      message: filename,
      encrypted: 0,
      type: 'file',
      filename,
      file_url: url,
      file_size: size,
      timestamp: ts
    });

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
    console.log(`[-] Socket disconnected: ${socket.id}`);
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log('═══════════════════════════════════════════════');
  console.log('  🔐 SecureChat Web Server + SQLite DB');
  console.log(`  Running on http://localhost:${PORT}`);
  console.log('═══════════════════════════════════════════════');
});
