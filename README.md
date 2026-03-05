# 🔐 Smart Encrypted Chat with File Sharing

A complete multi-client encrypted chat application with file sharing, built using Python socket programming and AES-256 encryption.

---

## 📁 Project Structure

```
chat_project/
├── server.py         # Multi-client TCP server
├── client.py         # Terminal-based client
├── client_gui.py     # GUI client (Tkinter)
├── requirements.txt  # Python dependencies
├── server_files/     # Server file storage (auto-created)
└── downloads/        # Client downloads (auto-created)
```

---

## 🛡️ Encryption Architecture

| Layer | Method |
|-------|--------|
| Key Derivation | SHA-256 hash of shared password |
| Symmetric Cipher | AES-256 via Fernet (CBC mode + HMAC-SHA256) |
| Transport | Custom length-prefixed packet protocol over TCP |
| File Transfer | Base64-encoded, fully encrypted payloads |

### How It Works

```
Client Password ──► SHA-256 ──► Fernet Key ──► AES-256 Encrypt/Decrypt
                                     ▲                    │
                                     │                    ▼
                              Server derives      All packets encrypted
                              same key from      before socket send
                              same password
```

---

## 🚀 Setup & Run

### 1. Install Dependencies

```bash
pip install cryptography
```

### 2. Start the Server

```bash
python server.py
```

Output:
```
═══════════════════════════════════════════════════════
  🔐 Smart Encrypted Chat Server
  AES-256 Encryption | Multi-Room | File Sharing
═══════════════════════════════════════════════════════
[*] Listening on 0.0.0.0:9999
```

### 3. Start a Client

**GUI Client (recommended):**
```bash
python client_gui.py
```

**Terminal Client:**
```bash
python client.py
```

---

## 💬 Features

### Messaging
- Real-time multi-client chat
- Messages encrypted with AES-256 before sending
- Timestamps on all messages
- Own message differentiated visually

### Rooms
- Join different rooms: `general`, `tech`, `random`, `private`
- Live member list per room
- System notifications when users join/leave

### File Sharing
- Upload any file (images, docs, archives, etc.)
- Files stored encrypted on server
- Any room member can download shared files
- File size shown in chat

---

## 🖥️ GUI Client Features

- **Dark themed UI** with cyan/teal accent colors
- **Sidebar** with room list and online members
- **Message bubbles** — your messages vs others
- **File upload** via file picker button (📎)
- **File download** via in-chat Download button
- **Encryption badge** always visible (🔒 AES-256)
- **Login screen** with host, port, username, password

---

## 📟 Terminal Client Commands

| Command | Description |
|---------|-------------|
| `/join <room>` | Switch to a room |
| `/send <filepath>` | Upload a file |
| `/download <file_id>` | Download a shared file |
| `/ping` | Ping the server |
| `/quit` | Disconnect |

---

## 🔌 Packet Protocol

All packets are JSON, encrypted with Fernet (AES-256), prefixed with 4-byte length:

```
[4 bytes: length][encrypted JSON payload]
```

### Packet Types

| Type | Direction | Description |
|------|-----------|-------------|
| `message` | Both | Chat message |
| `system` | Server→Client | System notification |
| `file_upload` | Client→Server | Upload file |
| `file_available` | Server→Client | Notify file ready |
| `file_download` | Both | Request/send file |
| `join_room` | Client→Server | Switch room |
| `room_joined` | Server→Client | Room join confirmation |
| `ping`/`pong` | Both | Keepalive |
| `handshake_ok` | Server→Client | Auth success |

---

## 🧵 Threading Model

```
Server:
  Main Thread ──► accept connections
  Per Client  ──► handle_client() thread

Client (GUI):
  Main Thread ──► Tkinter UI event loop
  Thread      ──► _listen() receives packets
  Thread      ──► file uploads (non-blocking)
```

---

## 🔒 Security Notes

- All chat messages encrypted end-to-end with AES-256
- File contents encrypted during transfer
- Password never sent in plaintext (only used for key derivation)
- HMAC authentication in Fernet prevents tampering

---

## 📊 Class & Function Summary

### server.py
- `derive_key(password)` — SHA-256 key derivation
- `send_packet() / recv_packet()` — Encrypted packet I/O
- `handle_handshake()` — Key exchange & auth
- `handle_client()` — Per-client thread
- `broadcast()` — Send to all room members
- `handle_file_upload() / handle_file_download()` — File ops

### client.py
- `ChatClient` — Full terminal client class
  - `connect()` — Handshake & auth
  - `listen()` — Background receive thread
  - `send_message() / send_file() / download_file()` — Actions

### client_gui.py
- `LoginWindow` — Tkinter login form
- `ChatWindow` — Full chat UI
  - `_add_message()` — Render chat bubble
  - `_add_file_message()` — Render file card
  - `_connect()` / `_listen()` — Socket handling
  - `_send_message()` / `_send_file()` — Send actions
