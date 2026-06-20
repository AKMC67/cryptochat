# 🔒 CryptoChat — End-to-End Encrypted Chat Rooms

Two (or more) people enter the **same room code** and the **same encryption key**,
and they can chat. Everyone else — the server, your ISP, anyone sniffing the
network — sees only random-looking ciphertext.

**Zero dependencies.** The server uses only the Python standard library.
Just run one file.

---

## Quick start

```bash
cd cryptochat
python3 server.py
```

Then open **http://localhost:8765** in your browser.

To chat with someone else, both of you open the page, type the **same room code**
and the **same encryption key**, and start talking.

Custom port:

```bash
PORT=9000 python3 server.py
```

---

## How the security works

| Layer | What we use |
|---|---|
| **Cipher** | AES-256-GCM (authenticated encryption) |
| **Key derivation** | PBKDF2-HMAC-SHA256, **600,000 iterations** |
| **Salt** | `SHA-256("cryptochat\|v1\|" + roomCode)` (deterministic, so both sides derive the same key) |
| **Nonce** | Fresh random 96-bit IV per message |
| **Integrity** | 128-bit GCM auth tag — tampered or wrong-key messages are rejected |
| **Where** | 100% in the browser (Web Crypto API) |

### What this guarantees
- **The server never sees your key or your plaintext.** It is a dumb relay that
  forwards opaque ciphertext blobs between people in the same room. Read
  `server.py` — there is no decryption code anywhere in it, because it's impossible.
- **Your ISP / network attacker sees only ciphertext.** Even on plain HTTP, the
  message contents are encrypted before they ever leave your tab.
- **Only someone with the exact same passphrase + room code can read messages.**
- **Tampering is detected.** Flipping a single bit makes decryption fail loudly.

### Honest caveats (so "impenetrable" actually means something)
1. **Your passphrase is the whole game.** AES-256 is unbreakable by brute force,
   but a *weak passphrase* is not. Use a long, unique phrase (e.g. 5+ random
   words). The app warns you if it's under 8 characters.
2. **Use TLS for the transport in production.** End-to-end encryption already
   hides message *contents* from your ISP. But to also hide *metadata* (that you
   connected, the room codes, timing) and to enable the browser's Web Crypto on a
   remote machine, serve it over **HTTPS/WSS**. Easiest way — put it behind a
   reverse proxy:

   ```nginx
   # /etc/nginx/sites-enabled/cryptochat
   server {
     listen 443 ssl;
     server_name chat.example.com;
     ssl_certificate     /etc/letsencrypt/live/chat.example.com/fullchain.pem;
     ssl_certificate_key /etc/letsencrypt/live/chat.example.com/privkey.pem;
     location / {
       proxy_pass http://127.0.0.1:8765;
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";
       proxy_set_header Host $host;
     }
   }
   ```
   The client auto-switches to `wss://` when the page is served over `https://`.
   (Browsers allow Web Crypto on `localhost` without TLS, which is why local dev
   works out of the box.)
3. **No forward secrecy.** Everyone shares one passphrase-derived key, so if the
   passphrase leaks later, past captured ciphertext could be read. For casual
   secure chat this is fine; for higher threat models you'd layer in a key-exchange
   (X3DH/Double Ratchet). See "Going further" below.
4. **Endpoint security matters.** If someone has malware on your device or reads
   your screen, no protocol can help. Encryption protects data *in transit and on
   the server*, not a compromised endpoint.

---

## Files

```
cryptochat/
├── server.py            # zero-dependency relay (stdlib only) — never decrypts
├── static/
│   ├── index.html       # UI
│   ├── styles.css       # styling
│   └── app.js           # ALL crypto happens here (Web Crypto API)
├── test_e2e.py          # automated relay + key-derivation tests
└── README.md
```

## Run the tests

```bash
pip install websockets          # test-only; the server itself needs nothing
python3 test_e2e.py
```

Verifies: ciphertext is relayed verbatim, sender gets no echo, rooms are isolated
from each other, presence counts update, and key derivation is deterministic per
passphrase+room.

---

## Going further (stronger threat models)
- **Per-conversation forward secrecy:** add an ECDH (P-256 / X25519) handshake so
  each session has an ephemeral key; rotate with a Double Ratchet.
- **Hide metadata fully:** run behind Tor or a hidden service.
- **Disappearing messages:** the server already keeps nothing; add client-side
  auto-delete timers for local history.
