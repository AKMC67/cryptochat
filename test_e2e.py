import asyncio, json, subprocess, time, sys, hashlib, os, signal
import websockets

PORT = 8801
proc = subprocess.Popen(
    [sys.executable, "server.py"],
    cwd="/home/user/cryptochat",
    env={**os.environ, "PORT": str(PORT)},
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)
time.sleep(1.5)
URL = f"ws://127.0.0.1:{PORT}/ws"
results = {}

async def drain(ws, timeout=0.5):
    """Collect all messages currently waiting."""
    out = []
    try:
        while True:
            out.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout)))
    except asyncio.TimeoutError:
        pass
    return out

async def main():
    a = await websockets.connect(URL)
    b = await websockets.connect(URL)

    await a.send(json.dumps({"type": "join", "room": "r1"}))
    await b.send(json.dumps({"type": "join", "room": "r1"}))
    await asyncio.sleep(0.3)
    a_msgs = await drain(a)
    b_msgs = await drain(b)

    # highest presence/joined count either side saw should reach 2
    def max_count(msgs):
        return max([m.get("count", 0) for m in msgs] + [0])
    results["room_reached_2_members"] = (max_count(a_msgs) == 2 and max_count(b_msgs) == 2)

    # A sends opaque ciphertext; B must receive it verbatim, A must not echo
    blob = json.dumps({"iv": "AAAA", "ct": "CIPHERTEXT_OPAQUE_TO_SERVER"})
    await a.send(json.dumps({"type": "msg", "payload": blob}))
    await asyncio.sleep(0.3)
    a_after = await drain(a)
    b_after = await drain(b)

    b_relayed = [m for m in b_after if m.get("type") == "msg"]
    results["b_received_message"] = len(b_relayed) == 1
    results["payload_relayed_verbatim"] = bool(b_relayed) and b_relayed[0]["payload"] == blob
    results["server_added_timestamp"] = bool(b_relayed) and "ts" in b_relayed[0]
    results["sender_got_no_echo"] = all(m.get("type") != "msg" for m in a_after)

    # isolation: a client in a DIFFERENT room must not receive r1 traffic
    c = await websockets.connect(URL)
    await c.send(json.dumps({"type": "join", "room": "OTHER"}))
    await asyncio.sleep(0.2)
    await drain(c)
    await a.send(json.dumps({"type": "msg", "payload": blob}))
    await asyncio.sleep(0.3)
    c_after = await drain(c)
    results["room_isolation"] = all(m.get("type") != "msg" for m in c_after)

    await b.close()
    await asyncio.sleep(0.3)
    a_final = await drain(a)
    results["presence_drops_to_1_after_leave"] = any(m.get("count") == 1 for m in a_final)

    await a.close(); await c.close()

asyncio.run(main())

def derive(p, room):
    salt = hashlib.sha256(("cryptochat|v1|" + room).encode()).digest()
    return hashlib.pbkdf2_hmac("sha256", p.encode(), salt, 600000, 32)
results["same_key_deterministic"] = derive("pw", "r1") == derive("pw", "r1")
results["wrong_key_differs"] = derive("pw", "r1") != derive("bad", "r1")
results["diff_room_diff_key"] = derive("pw", "r1") != derive("pw", "r2")
results["key_len_bytes"] = len(derive("pw", "r1"))

proc.send_signal(signal.SIGINT); time.sleep(0.3); proc.kill()

print(json.dumps(results, indent=2))
allpass = all(v is True for k, v in results.items() if k != "key_len_bytes")
print("\nALL CRITICAL CHECKS PASSED:" , allpass, "| key bytes:", results["key_len_bytes"])
