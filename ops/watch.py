"""Cron helper on the bot server. `watch.py check` (every 30 min): tell the owner in Telegram when the bot service is down
or the disk is almost full (once per problem per day). `watch.py backup` (daily): snapshot zb.db, keep 14 days."""
import glob, json, os, shutil, sqlite3, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(l.strip().split("=", 1) for l in open(os.path.join(HERE, ".env")) if "=" in l and not l.startswith("#"))


def tell(key, text):
    flag = os.path.join(HERE, f".warned-{key}")
    today = time.strftime("%F")
    if os.path.exists(flag) and open(flag).read() == today:
        return
    urllib.request.urlopen(urllib.request.Request(
        f"https://api.telegram.org/bot{env['TG_TOKEN']}/sendMessage",
        json.dumps({"chat_id": int(env["OWNER_CHAT"]), "text": text}).encode(), {"Content-Type": "application/json"}), timeout=20)
    open(flag, "w").write(today)


def check():
    state = subprocess.run(["systemctl", "is-active", "zdravniki"], capture_output=True, text=True).stdout.strip()
    if state != "active":
        tell("down", f"⚠️ zdravniki bot service is {state or 'unknown'} on {os.uname().nodename}")
    du = shutil.disk_usage("/")
    if du.used / du.total > 0.9:
        tell("disk", f"⚠️ disk {du.used / du.total:.0%} full on {os.uname().nodename}")


def backup():
    os.makedirs(os.path.join(HERE, "backups"), exist_ok=True)
    dst = os.path.join(HERE, "backups", f"zb-{time.strftime('%F')}.db")
    src = sqlite3.connect(os.path.join(HERE, "zb.db"))
    with sqlite3.connect(dst) as d:
        src.backup(d)
    for f in sorted(glob.glob(os.path.join(HERE, "backups", "zb-*.db")))[:-14]:
        os.remove(f)


if __name__ == "__main__":
    {"check": check, "backup": backup}[sys.argv[1]]()
