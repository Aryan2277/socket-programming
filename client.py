"""
Smart Encrypted Chat Client (Terminal)
Uses AES-256 encryption via Fernet (symmetric key cryptography)
Supports multi-room chat and encrypted file sharing
"""

import socket
import threading
import os
import json
import base64
import hashlib
import sys
from datetime import datetime
from cryptography.fernet import Fernet

# ─── Configuration ───────────────────────────────────────────────────────────
BUFFER_SIZE = 65536
DOWNLOADS_DIR = "downloads"

os.makedirs(DOWNLOADS_DIR, exist_ok=True)


def derive_key(password: str) -> bytes:
    hashed = hashlib.sha256(password.encode()).digest()
    return base64.urlsafe_b64encode(hashed)


def send_packet(conn: socket.socket, packet: dict, cipher: Fernet = None):
    raw = json.dumps(packet).encode('utf-8')
    if cipher:
        raw = cipher.encrypt(raw)
    length = len(raw).to_bytes(4, 'big')
    conn.sendall(length + raw)


def recv_packet(conn: socket.socket, cipher: Fernet = None) -> dict | None:
    try:
        length_bytes = recvall(conn, 4)
        if not length_bytes:
            return None
        length = int.from_bytes(length_bytes, 'big')
        raw = recvall(conn, length)
        if not raw:
            return None
        if cipher:
            raw = cipher.decrypt(raw)
        return json.loads(raw.decode('utf-8'))
    except Exception as e:
        return None


def recvall(conn: socket.socket, n: int) -> bytes | None:
    data = b''
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


class ChatClient:
    def __init__(self, host: str, port: int, username: str, password: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.cipher = None
        self.conn = None
        self.room = 'general'
        self.running = False
        self.pending_files = {}  # file_id -> filename

    def connect(self):
        self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn.connect((self.host, self.port))

        # Receive server key
        self.conn.recv(44)  # Fernet key is 44 bytes base64

        # Derive our cipher from shared password
        self.cipher = Fernet(derive_key(self.password))

        # Send auth (plaintext, before encryption established)
        auth = json.dumps({"username": self.username, "password": self.password}).encode()
        self.conn.sendall(len(auth).to_bytes(4, 'big') + auth)

        # Receive handshake confirmation (plaintext)
        length_bytes = recvall(self.conn, 4)
        length = int.from_bytes(length_bytes, 'big')
        raw = recvall(self.conn, length)
        resp = json.loads(raw.decode())
        print(f"\n✅ {resp.get('message', 'Connected')}")

        self.running = True

    def listen(self):
        """Background thread to receive messages."""
        while self.running:
            packet = recv_packet(self.conn, self.cipher)
            if packet is None:
                print("\n[!] Disconnected from server.")
                self.running = False
                break

            ptype = packet.get('type')

            if ptype == 'message':
                ts = packet.get('timestamp', '')
                sender = packet.get('sender', '?')
                msg = packet.get('message', '')
                own = packet.get('own', False)
                tag = "YOU" if own else sender
                print(f"\r[{ts}] {tag}: {msg}")

            elif ptype == 'system':
                ts = packet.get('timestamp', '')
                print(f"\r[{ts}] *** {packet.get('message', '')} ***")

            elif ptype == 'room_joined':
                self.room = packet.get('room')
                members = ', '.join(packet.get('members', []))
                print(f"\r[Room: {self.room}] Members: {members}")

            elif ptype == 'file_available':
                ts = packet.get('timestamp', '')
                sender = packet.get('sender', '?')
                fn = packet.get('filename', '')
                size = packet.get('size', 0)
                fid = packet.get('file_id', '')
                self.pending_files[fid] = fn
                print(f"\r[{ts}] 📎 {sender} shared file: '{fn}' ({size} bytes)")
                print(f"     Download with: /download {fid}")

            elif ptype == 'file_download':
                fid = packet.get('file_id', '')
                fn = packet.get('filename', 'file')
                data = base64.b64decode(packet.get('data', ''))
                path = os.path.join(DOWNLOADS_DIR, fn)
                with open(path, 'wb') as f:
                    f.write(data)
                print(f"\r✅ File saved to: {path}")

            elif ptype == 'error':
                print(f"\r[ERROR] {packet.get('message', '')}")

            elif ptype == 'pong':
                print("\r[PONG] Server alive.")

            sys.stdout.write(f"[{self.room}] > ")
            sys.stdout.flush()

    def send_message(self, message: str):
        send_packet(self.conn, {
            "type": "message",
            "message": message,
            "room": self.room
        }, self.cipher)

    def send_file(self, filepath: str):
        if not os.path.exists(filepath):
            print(f"[!] File not found: {filepath}")
            return
        with open(filepath, 'rb') as f:
            data = f.read()
        filename = os.path.basename(filepath)
        send_packet(self.conn, {
            "type": "file_upload",
            "filename": filename,
            "room": self.room,
            "data": base64.b64encode(data).decode()
        }, self.cipher)
        print(f"[*] Uploading '{filename}' ({len(data)} bytes)...")

    def download_file(self, file_id: str):
        send_packet(self.conn, {
            "type": "file_download",
            "file_id": file_id
        }, self.cipher)

    def join_room(self, room: str):
        send_packet(self.conn, {
            "type": "join_room",
            "room": room
        }, self.cipher)

    def run(self):
        self.connect()

        # Start listener thread
        t = threading.Thread(target=self.listen, daemon=True)
        t.start()

        print("\n─── Commands ───────────────────────────────")
        print("  /join <room>        Join a chat room")
        print("  /send <filepath>    Upload a file")
        print("  /download <file_id> Download a file")
        print("  /ping               Ping server")
        print("  /quit               Disconnect")
        print("────────────────────────────────────────────\n")

        while self.running:
            try:
                sys.stdout.write(f"[{self.room}] > ")
                sys.stdout.flush()
                line = input()
            except (EOFError, KeyboardInterrupt):
                break

            if not line.strip():
                continue

            if line.startswith('/join '):
                self.join_room(line.split(' ', 1)[1].strip())
            elif line.startswith('/send '):
                self.send_file(line.split(' ', 1)[1].strip())
            elif line.startswith('/download '):
                self.download_file(line.split(' ', 1)[1].strip())
            elif line == '/ping':
                send_packet(self.conn, {"type": "ping"}, self.cipher)
            elif line == '/quit':
                break
            else:
                self.send_message(line)

        self.running = False
        self.conn.close()
        print("\n[*] Disconnected.")


if __name__ == '__main__':
    print("=" * 55)
    print("  🔐 Smart Encrypted Chat Client")
    print("=" * 55)

    host = input("Server host [127.0.0.1]: ").strip() or '127.0.0.1'
    port = int(input("Server port [9999]: ").strip() or '9999')
    username = input("Username: ").strip() or 'User'
    password = input("Room password: ").strip() or 'default'

    client = ChatClient(host, port, username, password)
    try:
        client.run()
    except ConnectionRefusedError:
        print("[!] Could not connect to server.")
