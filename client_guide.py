"""
Smart Encrypted Chat — GUI Client (Tkinter)
Beautiful dark-themed interface with AES-256 encryption
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
import json
import base64
import hashlib
import socket
from datetime import datetime
from cryptography.fernet import Fernet


# ─── Encryption Utilities ────────────────────────────────────────────────────
def derive_key(password: str) -> bytes:
    import hashlib, base64
    hashed = hashlib.sha256(password.encode()).digest()
    return base64.urlsafe_b64encode(hashed)

def send_packet(conn, packet, cipher=None):
    raw = json.dumps(packet).encode()
    if cipher:
        raw = cipher.encrypt(raw)
    conn.sendall(len(raw).to_bytes(4, 'big') + raw)

def recv_packet(conn, cipher=None):
    try:
        lb = recvall(conn, 4)
        if not lb: return None
        raw = recvall(conn, int.from_bytes(lb, 'big'))
        if not raw: return None
        if cipher: raw = cipher.decrypt(raw)
        return json.loads(raw.decode())
    except:
        return None

def recvall(conn, n):
    data = b''
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk: return None
        data += chunk
    return data


# ─── Color Palette ───────────────────────────────────────────────────────────
BG       = "#0d0f14"
BG2      = "#141720"
BG3      = "#1c2030"
ACCENT   = "#00d4aa"
ACCENT2  = "#0099ff"
TEXT     = "#e2e8f0"
TEXT_DIM = "#64748b"
OWN_BG   = "#0a2a1f"
MSG_BG   = "#1a1f2e"
RED      = "#ff4757"
GOLD     = "#ffd700"


class LoginWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SecureChat - Connect")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.result = None
        self._build_ui()
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth() + 40
        h = self.root.winfo_reqheight() + 20
        x = (self.root.winfo_screenwidth() - w) // 2
        y = max(10, (self.root.winfo_screenheight() - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        tk.Label(self.root, text="SecureChat", font=("Segoe UI", 18, "bold"), bg=BG, fg=ACCENT).pack(pady=(20,2))
        tk.Label(self.root, text="AES-256 Encrypted", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack()

        form = tk.Frame(self.root, bg=BG2, padx=20, pady=14)
        form.pack(fill='x', padx=20, pady=12)

        fields = [
            ("Server Host", "host", "127.0.0.1"),
            ("Port",        "port", "9999"),
            ("Username",    "username", ""),
            ("Room Password","password", ""),
        ]
        self.vars = {}
        for label, key, default in fields:
            tk.Label(form, text=label, font=("Segoe UI", 9, "bold"), bg=BG2, fg=TEXT_DIM, anchor='w').pack(fill='x', pady=(6,1))
            v = tk.StringVar(value=default)
            self.vars[key] = v
            show = "*" if key == "password" else ""
            tk.Entry(form, textvariable=v, font=("Segoe UI", 11), bg=BG3, fg=TEXT,
                     insertbackground=ACCENT, relief='flat', bd=5, show=show).pack(fill='x', ipady=4)

        tk.Button(self.root, text="Connect Securely", font=("Segoe UI", 11, "bold"),
                  bg=ACCENT, fg="#000", activebackground="#00b894", relief='flat',
                  pady=9, cursor='hand2', command=self._connect).pack(fill='x', padx=20, pady=(0,8))

        self.status = tk.Label(self.root, text="", font=("Segoe UI", 9), bg=BG, fg=RED)
        self.status.pack(pady=(0,10))

    def _connect(self):
        self.result = {k: v.get().strip() for k, v in self.vars.items()}
        if not self.result['username']:
            self.status.config(text="Username required")
            return
        self.root.destroy()

    def show(self):
        self.root.mainloop()
        return self.result


class ChatWindow:
    def __init__(self, config: dict):
        self.config = config
        self.conn = None
        self.cipher = None
        self.room = 'general'
        self.running = False
        self.pending_files = {}
        os.makedirs("downloads", exist_ok=True)

        self.root = tk.Tk()
        self.root.title(f"🔐 SecureChat — {config['username']}")
        self.root.geometry("1000x680")
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self._connect()

    def _build_ui(self):
        # ── Left Sidebar ──
        sidebar = tk.Frame(self.root, bg=BG2, width=220)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)

        # Logo
        logo_frame = tk.Frame(sidebar, bg=BG2, pady=20)
        logo_frame.pack(fill='x')
        tk.Label(logo_frame, text="🔐 SecureChat", font=("Segoe UI", 14, "bold"), bg=BG2, fg=ACCENT).pack()
        tk.Label(logo_frame, text="AES-256 Encrypted", font=("Segoe UI", 8), bg=BG2, fg=TEXT_DIM).pack()

        tk.Frame(sidebar, bg=BG3, height=1).pack(fill='x')

        # User info
        user_frame = tk.Frame(sidebar, bg=BG2, padx=15, pady=10)
        user_frame.pack(fill='x')
        self.user_avatar = tk.Label(user_frame, text="●", font=("Segoe UI", 14), bg=BG2, fg=ACCENT)
        self.user_avatar.pack(side='left')
        user_info = tk.Frame(user_frame, bg=BG2)
        user_info.pack(side='left', padx=8)
        tk.Label(user_info, text=self.config['username'], font=("Segoe UI", 11, "bold"), bg=BG2, fg=TEXT).pack(anchor='w')
        self.status_label = tk.Label(user_info, text="Connecting...", font=("Segoe UI", 9), bg=BG2, fg=TEXT_DIM)
        self.status_label.pack(anchor='w')

        tk.Frame(sidebar, bg=BG3, height=1).pack(fill='x', pady=10)

        # Rooms
        tk.Label(sidebar, text="ROOMS", font=("Segoe UI", 9, "bold"), bg=BG2, fg=TEXT_DIM, padx=15).pack(anchor='w')
        self.room_buttons = {}
        for r in ['general', 'tech', 'random', 'private']:
            btn = tk.Button(sidebar, text=f"# {r}", font=("Segoe UI", 11), bg=BG2, fg=TEXT_DIM,
                            relief='flat', anchor='w', padx=20, pady=6, cursor='hand2',
                            activebackground=BG3,
                            command=lambda room=r: self._join_room(room))
            btn.pack(fill='x')
            self.room_buttons[r] = btn

        tk.Frame(sidebar, bg=BG3, height=1).pack(fill='x', pady=10)

        # Members
        tk.Label(sidebar, text="MEMBERS", font=("Segoe UI", 9, "bold"), bg=BG2, fg=TEXT_DIM, padx=15).pack(anchor='w')
        self.members_frame = tk.Frame(sidebar, bg=BG2, padx=15)
        self.members_frame.pack(fill='x')

        # ── Main Chat Area ──
        main = tk.Frame(self.root, bg=BG)
        main.pack(side='left', fill='both', expand=True)

        # Top bar
        topbar = tk.Frame(main, bg=BG2, pady=10, padx=20)
        topbar.pack(fill='x')
        self.room_label = tk.Label(topbar, text="# general", font=("Segoe UI", 14, "bold"), bg=BG2, fg=TEXT)
        self.room_label.pack(side='left')
        self.encrypt_badge = tk.Label(topbar, text="🔒 AES-256", font=("Segoe UI", 9, "bold"),
                                       bg=OWN_BG, fg=ACCENT, padx=8, pady=3)
        self.encrypt_badge.pack(side='right')

        tk.Frame(main, bg=BG3, height=1).pack(fill='x')

        # Messages
        self.msg_frame = tk.Frame(main, bg=BG)
        self.msg_frame.pack(fill='both', expand=True)

        self.canvas = tk.Canvas(self.msg_frame, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.msg_frame, orient="vertical", command=self.canvas.yview)
        self.messages_container = tk.Frame(self.canvas, bg=BG)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas_window = self.canvas.create_window((0,0), window=self.messages_container, anchor='nw')

        self.messages_container.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1*(e.delta//120), "units"))

        tk.Frame(main, bg=BG3, height=1).pack(fill='x')

        # Input area
        input_area = tk.Frame(main, bg=BG2, pady=12, padx=15)
        input_area.pack(fill='x')

        # File button
        self.file_btn = tk.Button(input_area, text="📎", font=("Segoe UI Emoji", 16), bg=BG2, fg=TEXT_DIM,
                                  relief='flat', cursor='hand2', activebackground=BG3,
                                  command=self._send_file)
        self.file_btn.pack(side='left', padx=(0, 8))

        # Text input
        self.input_var = tk.StringVar()
        self.input_entry = tk.Entry(input_area, textvariable=self.input_var,
                                    font=("Segoe UI", 12), bg=BG3, fg=TEXT,
                                    insertbackground=ACCENT, relief='flat', bd=10)
        self.input_entry.pack(side='left', fill='x', expand=True, ipady=8)
        self.input_entry.bind("<Return>", self._send_message)
        self.input_entry.bind("<KeyPress>", self._on_typing)

        # Send button
        send_btn = tk.Button(input_area, text="Send →", font=("Segoe UI", 11, "bold"),
                             bg=ACCENT, fg="#000", relief='flat', padx=16, pady=8,
                             cursor='hand2', activebackground="#00b894",
                             command=self._send_message)
        send_btn.pack(side='right', padx=(8, 0))

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_typing(self, event):
        pass

    def _add_message(self, sender, message, timestamp, own=False, system=False):
        frame = tk.Frame(self.messages_container, bg=BG, pady=4, padx=10)
        frame.pack(fill='x', anchor='e' if own else 'w')

        if system:
            tk.Label(frame, text=f"── {message} ──",
                     font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack()
            return

        bubble = tk.Frame(frame, bg=OWN_BG if own else MSG_BG, padx=12, pady=8)
        bubble.pack(side='right' if own else 'left')

        # Header
        header = tk.Frame(bubble, bg=OWN_BG if own else MSG_BG)
        header.pack(fill='x')
        tk.Label(header, text="You" if own else sender,
                 font=("Segoe UI", 9, "bold"), bg=OWN_BG if own else MSG_BG,
                 fg=ACCENT if own else ACCENT2).pack(side='left')
        tk.Label(header, text=timestamp,
                 font=("Segoe UI", 8), bg=OWN_BG if own else MSG_BG,
                 fg=TEXT_DIM).pack(side='right', padx=(10, 0))

        # Message
        tk.Label(bubble, text=message, font=("Segoe UI", 11), bg=OWN_BG if own else MSG_BG,
                 fg=TEXT, wraplength=500, justify='left', anchor='w').pack(fill='x', pady=(4, 0))

        self._scroll_bottom()

    def _add_file_message(self, sender, filename, size, file_id, timestamp):
        frame = tk.Frame(self.messages_container, bg=BG, pady=4, padx=10)
        frame.pack(fill='x')

        bubble = tk.Frame(frame, bg=BG3, padx=12, pady=10, relief='flat')
        bubble.pack(side='left')

        top = tk.Frame(bubble, bg=BG3)
        top.pack(fill='x')
        tk.Label(top, text=sender, font=("Segoe UI", 9, "bold"), bg=BG3, fg=ACCENT2).pack(side='left')
        tk.Label(top, text=timestamp, font=("Segoe UI", 8), bg=BG3, fg=TEXT_DIM).pack(side='right', padx=10)

        file_row = tk.Frame(bubble, bg=BG3)
        file_row.pack(fill='x', pady=4)
        tk.Label(file_row, text="📎", font=("Segoe UI Emoji", 18), bg=BG3, fg=GOLD).pack(side='left')
        info = tk.Frame(file_row, bg=BG3)
        info.pack(side='left', padx=8)
        tk.Label(info, text=filename, font=("Segoe UI", 11, "bold"), bg=BG3, fg=TEXT).pack(anchor='w')
        tk.Label(info, text=f"{size:,} bytes", font=("Segoe UI", 9), bg=BG3, fg=TEXT_DIM).pack(anchor='w')

        tk.Button(file_row, text="⬇ Download", font=("Segoe UI", 9, "bold"),
                  bg=ACCENT2, fg="#fff", relief='flat', padx=8, pady=4, cursor='hand2',
                  command=lambda: self._download_file(file_id, filename)).pack(side='right')

        self._scroll_bottom()

    def _scroll_bottom(self):
        self.root.after(50, lambda: self.canvas.yview_moveto(1.0))

    def _update_members(self, members):
        for w in self.members_frame.winfo_children():
            w.destroy()
        for m in members:
            f = tk.Frame(self.members_frame, bg=BG2)
            f.pack(fill='x', pady=2)
            tk.Label(f, text="●", font=("Segoe UI", 8), bg=BG2, fg=ACCENT).pack(side='left')
            tk.Label(f, text=m, font=("Segoe UI", 10), bg=BG2, fg=TEXT, padx=6).pack(side='left')

    def _update_room_buttons(self):
        for r, btn in self.room_buttons.items():
            if r == self.room:
                btn.config(bg=BG3, fg=TEXT)
            else:
                btn.config(bg=BG2, fg=TEXT_DIM)
        self.room_label.config(text=f"# {self.room}")

    def _connect(self):
        def do_connect():
            try:
                self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.conn.connect((self.config['host'], int(self.config['port'])))

                # Receive server key
                self.conn.recv(44)

                # Derive cipher
                self.cipher = Fernet(derive_key(self.config['password']))

                # Send auth
                auth = json.dumps({
                    "username": self.config['username'],
                    "password": self.config['password']
                }).encode()
                self.conn.sendall(len(auth).to_bytes(4, 'big') + auth)

                # Receive handshake
                lb = recvall(self.conn, 4)
                raw = recvall(self.conn, int.from_bytes(lb, 'big'))
                resp = json.loads(raw.decode())

                self.running = True
                self.root.after(0, lambda: self.status_label.config(text="● Online", fg=ACCENT))
                self.root.after(0, lambda: self._add_message(
                    None, resp.get('message', 'Connected!'), datetime.now().strftime('%H:%M:%S'), system=True))

                threading.Thread(target=self._listen, daemon=True).start()

            except Exception as e:
                self.root.after(0, lambda: self.status_label.config(text="● Offline", fg=RED))
                self.root.after(0, lambda: messagebox.showerror("Connection Error", str(e)))

        threading.Thread(target=do_connect, daemon=True).start()

    def _listen(self):
        while self.running:
            packet = recv_packet(self.conn, self.cipher)
            if packet is None:
                self.root.after(0, lambda: self.status_label.config(text="● Disconnected", fg=RED))
                break

            ptype = packet.get('type')

            if ptype == 'message':
                self.root.after(0, lambda p=packet: self._add_message(
                    p.get('sender'), p.get('message'), p.get('timestamp', ''),
                    own=p.get('own', False)
                ))

            elif ptype == 'system':
                self.root.after(0, lambda p=packet: self._add_message(
                    None, p.get('message'), p.get('timestamp', ''), system=True
                ))

            elif ptype == 'room_joined':
                self.room = packet.get('room')
                members = packet.get('members', [])
                self.root.after(0, self._update_room_buttons)
                self.root.after(0, lambda m=members: self._update_members(m))

            elif ptype == 'file_available':
                fid = packet.get('file_id')
                self.pending_files[fid] = packet.get('filename')
                self.root.after(0, lambda p=packet: self._add_file_message(
                    p.get('sender'), p.get('filename'), p.get('size', 0),
                    p.get('file_id'), p.get('timestamp', '')
                ))

            elif ptype == 'file_download':
                fn = packet.get('filename', 'file')
                data = base64.b64decode(packet.get('data', ''))
                path = os.path.join("downloads", fn)
                with open(path, 'wb') as f:
                    f.write(data)
                self.root.after(0, lambda p=path: messagebox.showinfo("Downloaded", f"File saved to:\n{p}"))

    def _send_message(self, event=None):
        msg = self.input_var.get().strip()
        if not msg or not self.conn:
            return
        self.input_var.set("")
        send_packet(self.conn, {
            "type": "message",
            "message": msg,
            "room": self.room
        }, self.cipher)

    def _send_file(self):
        path = filedialog.askopenfilename()
        if not path:
            return
        def upload():
            with open(path, 'rb') as f:
                data = f.read()
            filename = os.path.basename(path)
            send_packet(self.conn, {
                "type": "file_upload",
                "filename": filename,
                "room": self.room,
                "data": base64.b64encode(data).decode()
            }, self.cipher)
        threading.Thread(target=upload, daemon=True).start()

    def _download_file(self, file_id, filename):
        send_packet(self.conn, {
            "type": "file_download",
            "file_id": file_id
        }, self.cipher)

    def _join_room(self, room):
        if room == self.room:
            return
        send_packet(self.conn, {"type": "join_room", "room": room}, self.cipher)

    def _on_close(self):
        self.running = False
        if self.conn:
            try: self.conn.close()
            except: pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    login = LoginWindow()
    config = login.show()
    if config:
        app = ChatWindow(config)
        app.run()