"""
Smart Encrypted Chat Server
Uses AES-256 encryption via Fernet (symmetric key cryptography)
Supports multi-client chat and encrypted file sharing
"""

import socket
import threading
import os
import json
import base64
import hashlib
from datetime import datetime
from cryptography.fernet import Fernet

# ─── Configuration ───────────────────────────────────────────────────────────
HOST = '0.0.0.0'
PORT = 9999
BUFFER_SIZE = 65536
FILES_DIR = "server_files"

# ─── Server State ─────────────────────────────────────────────────────────────
clients = {}         # {conn: {"username": str, "cipher": Fernet}}
rooms   = {}         # {room_name: [conn, ...]}
lock    = threading.Lock()

# Generate or load server key (used for key derivation)
SERVER_KEY = Fernet.generate_key()

os.makedirs(FILES_DIR, exist_ok=True)


def derive_key(password: str) -> bytes:
    """Derive a Fernet key from a shared password using SHA-256."""
    hashed = hashlib.sha256(password.encode()).digest()
    return base64.urlsafe_b64encode(hashed)


def send_packet(conn: socket.socket, packet: dict, cipher: Fernet = None):
    """Serialize, optionally encrypt, and send a packet."""
    raw = json.dumps(packet).encode('utf-8')
    if cipher:
        raw = cipher.encrypt(raw)
    length = len(raw).to_bytes(4, 'big')
    try:
        conn.sendall(length + raw)
    except Exception:
        pass


def recv_packet(conn: socket.socket, cipher: Fernet = None) -> dict | None:
    """Receive, optionally decrypt, and deserialize a packet."""
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
    except Exception:
        return None


def recvall(conn: socket.socket, n: int) -> bytes | None:
    """Helper to receive exactly n bytes."""
    data = b''
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def broadcast(packet: dict, room: str, sender_conn=None, system=False):
    """Send a packet to all clients in a room."""
    with lock:
        targets = rooms.get(room, [])
        for conn in targets:
            if conn == sender_conn and not system:
                continue
            info = clients.get(conn)
            if info:
                send_packet(conn, packet, info['cipher'])


def handle_handshake(conn: socket.socket, addr) -> tuple[str, Fernet] | None:
    """Perform key exchange and return (username, cipher)."""
    # Step 1: Send server key to client
    conn.sendall(SERVER_KEY)

    # Step 2: Receive client's auth packet (plaintext, before encryption)
    raw_len = recvall(conn, 4)
    if not raw_len:
        return None
    raw = recvall(conn, int.from_bytes(raw_len, 'big'))
    if not raw:
        return None
    auth = json.loads(raw.decode())

    username = auth.get('username', 'Anonymous')
    password = auth.get('password', 'default')

    # Derive shared symmetric key from password
    key = derive_key(password)
    cipher = Fernet(key)

    # Confirm connection
    send_packet(conn, {
        "type": "handshake_ok",
        "message": f"Welcome {username}! Connection encrypted with AES-256."
    })

    return username, cipher


def handle_file_upload(conn: socket.socket, packet: dict, info: dict):
    """Save an uploaded file to the server."""
    filename = packet.get('filename', 'unknown')
    filedata_b64 = packet.get('data', '')
    room = packet.get('room', 'general')
    sender = info['username']

    filedata = base64.b64decode(filedata_b64)
    save_path = os.path.join(FILES_DIR, f"{sender}_{filename}")
    with open(save_path, 'wb') as f:
        f.write(filedata)

    # Notify all room members
    broadcast({
        "type": "file_available",
        "filename": filename,
        "sender": sender,
        "size": len(filedata),
        "timestamp": datetime.now().strftime('%H:%M:%S'),
        "file_id": f"{sender}_{filename}"
    }, room, sender_conn=None, system=True)

    print(f"[FILE] {sender} uploaded '{filename}' ({len(filedata)} bytes)")


def handle_file_download(conn: socket.socket, packet: dict, info: dict):
    """Send a requested file to the client."""
    file_id = packet.get('file_id', '')
    path = os.path.join(FILES_DIR, file_id)
    cipher = info['cipher']

    if os.path.exists(path):
        with open(path, 'rb') as f:
            data = f.read()
        send_packet(conn, {
            "type": "file_download",
            "file_id": file_id,
            "filename": file_id.split('_', 1)[-1],
            "data": base64.b64encode(data).decode()
        }, cipher)
    else:
        send_packet(conn, {"type": "error", "message": "File not found."}, cipher)


def handle_client(conn: socket.socket, addr):
    """Main client handler."""
    print(f"[+] Connection from {addr}")

    result = handle_handshake(conn, addr)
    if not result:
        conn.close()
        return

    username, cipher = result
    room = 'general'

    with lock:
        clients[conn] = {'username': username, 'cipher': cipher, 'room': room}
        rooms.setdefault(room, []).append(conn)

    print(f"[AUTH] {username} joined room '{room}'")

    # Notify room
    broadcast({
        "type": "system",
        "message": f"🔐 {username} joined the room.",
        "timestamp": datetime.now().strftime('%H:%M:%S')
    }, room, sender_conn=conn, system=True)

    # Send join confirmation with room members
    with lock:
        members = [clients[c]['username'] for c in rooms.get(room, [])]
    send_packet(conn, {
        "type": "room_joined",
        "room": room,
        "members": members
    }, cipher)

    try:
        while True:
            packet = recv_packet(conn, cipher)
            if packet is None:
                break

            ptype = packet.get('type')

            if ptype == 'message':
                packet['sender'] = username
                packet['timestamp'] = datetime.now().strftime('%H:%M:%S')
                broadcast(packet, room, sender_conn=conn)
                # Echo back to sender
                send_packet(conn, {**packet, "own": True}, cipher)

            elif ptype == 'file_upload':
                handle_file_upload(conn, packet, clients[conn])

            elif ptype == 'file_download':
                handle_file_download(conn, packet, clients[conn])

            elif ptype == 'join_room':
                new_room = packet.get('room', 'general')
                # Leave old room
                with lock:
                    if conn in rooms.get(room, []):
                        rooms[room].remove(conn)
                broadcast({
                    "type": "system",
                    "message": f"👋 {username} left the room.",
                    "timestamp": datetime.now().strftime('%H:%M:%S')
                }, room, system=True)
                room = new_room
                with lock:
                    clients[conn]['room'] = room
                    rooms.setdefault(room, []).append(conn)
                broadcast({
                    "type": "system",
                    "message": f"🔐 {username} joined the room.",
                    "timestamp": datetime.now().strftime('%H:%M:%S')
                }, room, sender_conn=conn, system=True)
                with lock:
                    members = [clients[c]['username'] for c in rooms.get(room, [])]
                send_packet(conn, {
                    "type": "room_joined",
                    "room": room,
                    "members": members
                }, cipher)

            elif ptype == 'ping':
                send_packet(conn, {"type": "pong"}, cipher)

    except Exception as e:
        print(f"[!] Error with {username}: {e}")

    finally:
        with lock:
            clients.pop(conn, None)
            if conn in rooms.get(room, []):
                rooms[room].remove(conn)
        broadcast({
            "type": "system",
            "message": f"❌ {username} disconnected.",
            "timestamp": datetime.now().strftime('%H:%M:%S')
        }, room, system=True)
        conn.close()
        print(f"[-] {username} disconnected from {addr}")


def main():
    print("=" * 55)
    print("  🔐 Smart Encrypted Chat Server")
    print("  AES-256 Encryption | Multi-Room | File Sharing")
    print("=" * 55)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(50)
    print(f"[*] Listening on {HOST}:{PORT}\n")

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n[*] Shutting down server...")
    finally:
        server.close()


if __name__ == '__main__':
    main()
