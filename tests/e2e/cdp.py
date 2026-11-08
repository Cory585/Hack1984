"""Tiny Chrome DevTools Protocol driver (stdlib only) for end-to-end checks in headless Edge."""
import base64, json, os, socket, struct, subprocess, tempfile, time, urllib.parse, urllib.request

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/microsoft-edge",
]
EDGE = os.environ.get("CC_BROWSER") or next((p for p in BROWSERS if os.path.exists(p)), None)


class WS:
    def __init__(self, url):
        u = urllib.parse.urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        self.extra = buf.split(b"\r\n\r\n", 1)[1]

    def _read(self, n):
        while len(self.extra) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.extra += chunk
        out, self.extra = self.extra[:n], self.extra[n:]
        return out

    def send(self, text):
        data = text.encode()
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126); head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127); head += struct.pack(">Q", n)
        mask = os.urandom(4)
        self.s.sendall(bytes(head) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        msg = b""
        while True:
            b1, b2 = self._read(2)
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            msg += self._read(n)
            if b1 & 0x80:
                return msg.decode("utf-8", "replace")


class Browser:
    def __init__(self, port=None, width=1280, height=900):
        port = port or __import__("random").randint(9300, 9900)
        if not EDGE:
            raise SystemExit("No Chrome/Edge found. Set CC_BROWSER to the browser's path.")
        self.prof = tempfile.mkdtemp(prefix="cc-e2e-")
        self.proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}",
                                      f"--user-data-dir={self.prof}", "--no-first-run", f"--window-size={width},{height}",
                                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.25)
        self.ws = WS(page["webSocketDebuggerUrl"])
        self.n = 0
        self.call("Page.enable"); self.call("Runtime.enable")
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
        self.console = []

    def call(self, method, **params):
        self.n += 1
        my = self.n
        self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("method") == "Runtime.exceptionThrown":
                self.console.append("EXCEPTION " + json.dumps(m["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:300])
            if m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] in ("error", "warning"):
                self.console.append(m["params"]["type"] + " " + " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"])[:300])
            if m.get("id") == my:
                if "error" in m:
                    raise RuntimeError(m["error"])
                return m.get("result", {})

    def js(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", str(r["exceptionDetails"]))[:500])
        return r["result"].get("value")

    def wait(self, cond, timeout=20):
        return self.js(f"""new Promise(res => {{ const t0 = Date.now(); (function poll() {{
            let ok = false; try {{ ok = !!({cond}); }} catch (e) {{}}
            if (ok) res(true); else if (Date.now() - t0 > {timeout * 1000}) res(false); else setTimeout(poll, 80); }})(); }})""")

    def goto(self, url):
        self.call("Page.navigate", url=url)
        time.sleep(0.3)
        self.wait("document.readyState === 'complete'")

    def shot(self, path):
        data = self.call("Page.captureScreenshot", format="png")["data"]
        open(path, "wb").write(base64.b64decode(data))

    def close(self):
        try:
            self.call("Browser.close")
        except Exception:
            pass
        self.proc.kill()
