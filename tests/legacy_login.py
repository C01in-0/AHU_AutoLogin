import os
import sys
import time
import socket
import requests
from datetime import datetime

GATEWAY_IP = "172.16.253.3"
GATEWAY_PORT = 801
TARGET_URL = f"http://{GATEWAY_IP}:{GATEWAY_PORT}/eportal/"
DEFAULT_PREFIXES = ("10.", "172.16.", "172.21.")


def get_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_base_dir()
LOG_PATH = os.path.join(BASE_DIR, "autologin.log")


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def get_path(filename):
    return os.path.join(BASE_DIR, filename)


def load_env():
    env_path = get_path(".env")
    data = {}
    if not os.path.exists(env_path):
        log(f"missing .env: {env_path}")
        return data
    try:
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
        return data
    except Exception as e:
        log(f"read .env failed: {e!r}")
        return {}


def campus_prefixes(env):
    raw = env.get("CAMPUS_IP_PREFIXES", "")
    if not raw:
        return DEFAULT_PREFIXES
    prefixes = tuple(x.strip() for x in raw.split(",") if x.strip())
    return prefixes or DEFAULT_PREFIXES


def is_valid_campus_ip(ip, prefixes):
    if not ip:
        return False
    bad_prefixes = ("127.", "169.254.", "192.168.")
    if ip.startswith(bad_prefixes):
        return False
    return ip.startswith(prefixes)


def get_real_ip(prefixes, max_retries=20):
    """Route probe against the campus gateway, not the public Internet."""
    last_ip = None
    for i in range(1, max_retries + 1):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect((GATEWAY_IP, GATEWAY_PORT))
            local_ip = s.getsockname()[0]
            s.close()
            last_ip = local_ip
            log(f"route probe {i}/{max_retries}: local_ip={local_ip}")
            if is_valid_campus_ip(local_ip, prefixes):
                return local_ip
        except Exception as e:
            log(f"route probe {i}/{max_retries} failed: {e!r}")
        time.sleep(1)
    log(f"no valid campus ip, last_ip={last_ip}, prefixes={prefixes}")
    return None


def login(local_ip, env):
    user = env.get("CAMPUS_ACCOUNT", "")
    pwd = env.get("CAMPUS_PASSWORD", "")
    if not user or not pwd:
        log("empty CAMPUS_ACCOUNT or CAMPUS_PASSWORD")
        return False

    payload = {
        "c": "Portal",
        "a": "login",
        "callback": "dr1003",
        "login_method": "1",
        "user_account": user,
        "user_password": pwd,
        "wlan_user_ip": local_ip,
        "jsVersion": "3.3.2",
        "terminal_type": "1",
        "v": "7379",
        "lang": "zh-cn",
    }

    try:
        session = requests.Session()
        session.trust_env = False
        r = session.get(TARGET_URL, params=payload, timeout=6)
        text = (r.text or "")[:500].replace("\r", " ").replace("\n", " ")
        log(f"login response: status={r.status_code}, len={len(r.text or '')}, body={text}")
        return r.status_code == 200
    except Exception as e:
        log(f"login request failed: {e!r}")
        return False


def main():
    log("==== start ====")
    env = load_env()
    prefixes = campus_prefixes(env)
    local_ip = get_real_ip(prefixes)
    if not local_ip:
        log("exit: no campus ip")
        return
    ok = login(local_ip, env)
    log(f"exit: login_called={ok}, local_ip={local_ip}")


if __name__ == "__main__":
    main()

