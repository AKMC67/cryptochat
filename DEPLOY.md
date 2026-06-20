# 🌐 Putting CryptoChat online (so anyone, anywhere can use it)

Someone not on your wifi needs a **public HTTPS URL**. HTTPS is mandatory: browsers
disable the Web Crypto encryption on a remote plain-`http://` site. All options
below give you HTTPS automatically. The app auto-switches to secure `wss://`
WebSockets when served over HTTPS — no code changes needed.

Pick ONE:

---

## Option A — Instant public link (your computer stays on)  ⭐ fastest

Great for "I just want to share a link in the next 2 minutes." Uses a free
Cloudflare Tunnel. No account, no signup.

1. Install `cloudflared`:
   - **macOS:** `brew install cloudflared`
   - **Windows:** `winget install --id Cloudflare.cloudflared`
   - **Linux:** download from https://github.com/cloudflare/cloudflared/releases

2. In one terminal, start the server:
   ```bash
   cd cryptochat
   python3 server.py
   ```

3. In a second terminal, expose it:
   ```bash
   cloudflared tunnel --url http://localhost:8765
   ```

4. Cloudflare prints a public URL like:
   ```
   https://random-words-here.trycloudflare.com
   ```
   Send that link to anyone. They open it, type the same room code + key, and chat.
   The tunnel handles HTTPS and WebSockets for you.

> Note: the link lives only while both `python3 server.py` and `cloudflared` are
> running on your machine. Close them and the link dies. For an always-on site,
> use Option B.

(ngrok works the same way if you prefer: `ngrok http 8765` — it needs a free
account/authtoken these days.)

---

## Option B — Permanent free hosting (no need to keep your PC on)  ⭐ recommended

Deploy to **Render.com** free tier. Stays online 24/7 with a real HTTPS URL.

1. Put this `cryptochat` folder in a **GitHub repo** (create repo → upload files,
   or `git init && git add . && git commit && git push`).
2. Go to **render.com → New → Blueprint** and select your repo.
   Render reads the included `render.yaml` automatically.
   - (Or **New → Web Service**, runtime **Python 3**, start command
     `python3 server.py`, and it just works — no build step, no dependencies.)
3. Render gives you `https://cryptochat-xxxx.onrender.com`. Share it. Done.

Render injects a `PORT` env var; `server.py` already reads it. The free tier may
"sleep" after inactivity and take ~30s to wake on the first visit — fine for
personal use.

**Railway / Fly.io** work the same way and also detect the included `Dockerfile`.

---

## Option C — Your own VPS / always-on box (most control)

On any cheap Linux server (DigitalOcean, Hetzner, an old Raspberry Pi, etc.):

```bash
# 1. copy the folder up, then:
cd cryptochat
python3 server.py            # runs on :8765

# 2. point a domain at the box and terminate TLS with nginx + Let's Encrypt:
sudo certbot --nginx -d chat.example.com
```
Use the nginx reverse-proxy config in `README.md` (it forwards HTTPS→localhost:8765
and upgrades WebSockets). Run the server under `systemd` or `tmux` so it survives
logout:
```bash
# minimal systemd unit: /etc/systemd/system/cryptochat.service
[Unit]
Description=CryptoChat
After=network.target
[Service]
WorkingDirectory=/opt/cryptochat
ExecStart=/usr/bin/python3 server.py
Restart=always
Environment=PORT=8765
[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now cryptochat
```

---

## Security reminder (still true once it's public)
- The host/proxy/Cloudflare/Render **only ever see ciphertext** — they cannot read
  messages, because decryption happens only in each visitor's browser.
- The strength of everything still rests on your **passphrase**. Use a long, unique
  one and share it with your contact over a *separate* secure channel (not in the
  same chat, not over the same email thread you're trying to protect).
