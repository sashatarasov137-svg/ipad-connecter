#!/usr/bin/env python3
"""iPad Connecter - Mac side.

Run this on your Mac. Open the printed link on your iPad (same Wi-Fi).
Tapping a button on the iPad presses that key combo on the Mac.

No extra installs needed: uses only built-in Python + macOS CoreGraphics.
"""
import asyncio, base64, ctypes, ctypes.util, hashlib, os, secrets, socket, struct, subprocess, sys

PORT = int(os.environ.get("PORT", "8765"))
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, ".token")

# ---------------------------------------------------------------- key codes
# macOS virtual key codes (US layout positions)
KEYS = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
    "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "enter": 36,
    "return": 36, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43,
    "/": 44, "n": 45, "m": 46, ".": 47, "tab": 48, "space": 49, "`": 50,
    "backspace": 51, "delete": 51, "esc": 53, "escape": 53,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
    "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "home": 115, "pageup": 116, "forwarddelete": 117, "end": 119, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126,
}
ALIASES = {"leftarrow": "left", "rightarrow": "right", "uparrow": "up", "downarrow": "down",
           "ctl": "ctrl", "control": "ctrl", "option": "alt", "command": "cmd"}
ARROWS = {123, 124, 125, 126}

# modifier name -> (key code, CGEventFlags bit)
MODS = {
    "cmd": (55, 0x100000), "command": (55, 0x100000),
    "shift": (56, 0x20000),
    "alt": (58, 0x80000), "option": (58, 0x80000), "opt": (58, 0x80000),
    "ctrl": (59, 0x40000), "control": (59, 0x40000),
    "fn": (63, 0x800000),
}

# ---------------------------------------------------------------- CoreGraphics
if sys.platform != "darwin":
    print("This runs on macOS only (it needs CoreGraphics to press keys).")
    CG = None
else:
    CG = ctypes.cdll.LoadLibrary(ctypes.util.find_library("ApplicationServices"))
    CG.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    CG.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    CG.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    CG.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    CG.CFRelease.argtypes = [ctypes.c_void_p]
    CG.AXIsProcessTrusted.restype = ctypes.c_bool

def post(code, down, flags):
    if CG is None:
        print("key", code, "down" if down else "up", hex(flags)); return
    ev = CG.CGEventCreateKeyboardEvent(None, code, down)
    CG.CGEventSetFlags(ev, flags)
    CG.CGEventPost(0, ev)  # 0 = HID event tap: games see it like a real keyboard
    CG.CFRelease(ev)

def parse(combo):
    mods, key = [], None
    c = combo.lower()
    for a, b in (("←", " left "), ("→", " right "), ("↑", " up "), ("↓", " down "),
                 ("control", "ctrl"), ("arrow", ""), ("key", "")):
        c = c.replace(a, b)
    for part in c.replace("+", " ").split():
        part = ALIASES.get(part, part)
        if part in MODS:
            mods.append(MODS[part])
        elif part in KEYS:
            key = KEYS[part]
        elif part:
            raise ValueError("unknown key: " + part)
    return mods, key

def press(combo, down):
    """down=True presses the combo, down=False releases it."""
    mods, key = parse(combo)
    flags = 0
    if down:
        for code, bit in mods:           # hold modifiers first, like a human
            flags |= bit
            post(code, True, flags)
        if key is not None:
            # arrow keys need these extra flags or macOS ignores ctrl+arrow (switching desktops)
            post(key, True, flags | (0xA00000 if key in ARROWS else 0))
    else:
        for _, bit in mods:
            flags |= bit
        if key is not None:
            post(key, False, flags | (0xA00000 if key in ARROWS else 0))
        for code, bit in reversed(mods):
            flags &= ~bit
            post(code, False, flags)

# ---------------------------------------------------------------- tiny websocket + http server
GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

async def read_frame(r):
    b1, b2 = await r.readexactly(2)
    op, n = b1 & 0x0F, b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", await r.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", await r.readexactly(8))[0]
    mask = await r.readexactly(4) if b2 & 0x80 else b"\0\0\0\0"
    data = bytearray(await r.readexactly(n))
    for i in range(n):
        data[i] ^= mask[i % 4]
    return op, bytes(data)

def frame(op, data=b""):
    return bytes([0x80 | op, len(data)]) + data  # small frames only

async def handle(r, w):
    sock = w.get_extra_info("socket")
    if sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # no delay batching
    held = set()
    try:
        head = (await r.readuntil(b"\r\n\r\n")).decode("latin1")
        lines = head.split("\r\n")
        path = lines[0].split(" ")[1] if len(lines[0].split(" ")) > 1 else "/"
        hdr = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:] if l)}
        query = path.partition("?")[2]
        ok = ("k=" + TOKEN) in query.split("&")

        if hdr.get("upgrade", "").lower() != "websocket":
            print("Page opened by", w.get_extra_info("peername")[0])
            body = open(os.path.join(HERE, "web", "index.html"), "rb").read()
            w.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                    b"Cache-Control: no-store\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
            await w.drain(); return
        print("Button connection from", w.get_extra_info("peername")[0], "| code ok:", ok)
        if not ok:
            print("  ! Wrong or missing ?k= code. Re-open the full link printed above on the iPad.")
            w.write(b"HTTP/1.1 403 Forbidden\r\n\r\n"); await w.drain(); return

        accept = base64.b64encode(hashlib.sha1(hdr["sec-websocket-key"].encode() + GUID).digest())
        w.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        await w.drain()
        print("iPad connected:", w.get_extra_info("peername")[0])

        while True:
            op, data = await read_frame(r)
            if op == 8:
                break
            if op == 9:
                w.write(frame(10, data)); continue
            if op != 1:
                continue
            msg = data.decode()
            if msg == "ping":
                w.write(frame(1, b"pong")); continue
            kind, _, combo = msg.partition(":")
            try:
                if kind == "d":
                    press(combo, True); held.add(combo)
                elif kind == "u":
                    press(combo, False); held.discard(combo)
            except ValueError as e:
                w.write(frame(1, ("err:" + str(e)).encode()[:120]))
    except (asyncio.IncompleteReadError, ConnectionError):
        print("iPad disconnected")
    except Exception as e:
        import traceback; traceback.print_exc()
        print("  ! Error above - please send it to Claude")
    finally:
        for combo in held:                 # never leave keys stuck down
            try: press(combo, False)
            except ValueError: pass
        w.close()

def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1)); return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

def load_token():
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE).read().strip()
    t = secrets.token_urlsafe(6)
    open(TOKEN_FILE, "w").write(t)
    return t

TOKEN = load_token()

async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", PORT)
    try:
        name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip()
    except OSError:
        name = ""
    print("\n  iPad Connecter is running!\n")
    print("  Open one of these on your iPad (Safari):")
    if name:
        print(f"    http://{name}.local:{PORT}/?k={TOKEN}")
    print(f"    http://{local_ip()}:{PORT}/?k={TOKEN}\n")
    if CG is not None and not CG.AXIsProcessTrusted():
        print("  ! Key presses are blocked until you allow this app in:")
        print("    System Settings > Privacy & Security > Accessibility")
        print("    (add Terminal, or whatever app you ran this from, then restart it)\n")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
