"""Pretend to be an ADMS device against a running server, so the whole push path can be tested without hardware.

    python manage.py runserver
    python manage.py simulate_adms --sn SIM0000001 --count 40 --poll 60
"""
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

from attendance import services


class Command(BaseCommand):
    help = "Simulate a ZKTeco ADMS device: handshake, user list, punches, and command polling."

    def add_arguments(self, parser):
        parser.add_argument("--url", default="http://127.0.0.1:8000")
        parser.add_argument("--sn", default="SIM0000001")
        parser.add_argument("--count", type=int, default=30, help="number of punches to push")
        parser.add_argument("--days", type=int, default=3, help="spread punches over the last N days")
        parser.add_argument("--push3", action="store_true", help="also exercise the push-3.x registry/config requests")
        parser.add_argument("--poll", type=int, default=0,
                            help="keep polling for commands this many seconds (answers INFO/CHECK/DATA QUERY USERINFO)")

    def _call(self, method, path, params, body=None):
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        data = body.encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "text/plain"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def _users_body(self):
        return "\n".join(f"USER PIN={101 + i}\tName={n}\tPri=0\tPasswd=\tCard=\tGrp=1\tTZ=0000000100000000"
                         for i, n in enumerate(services.DEMO_NAMES))

    def handle(self, *args, **opts):
        self.base, sn = opts["url"].rstrip("/"), opts["sn"]
        rng = random.Random(sn)
        if opts["push3"]:
            status, text = self._call("POST", "/iclock/registry", {"SN": sn}, "~DeviceName=Simulator,StringPinFunOn=1,FirmVer=Ver 1.0")
            self.stdout.write(f"registry -> {status} {text.strip()}")
            status, text = self._call("GET", "/iclock/push", {"SN": sn, "PushVersion": "3.0.1"})
            self.stdout.write(f"push config -> {status}\n{text}")
        status, text = self._call("GET", "/iclock/cdata", {"SN": sn, "options": "all", "pushver": "2.4.1"})
        self.stdout.write(f"handshake -> {status}\n{text}")

        status, text = self._call("POST", "/iclock/cdata", {"SN": sn, "table": "OPERLOG", "Stamp": "1"}, self._users_body())
        self.stdout.write(f"users (OPERLOG) -> {status} {text.strip()}")

        now, lines = datetime.now(), []
        for _ in range(opts["count"]):
            day = now - timedelta(days=rng.randint(0, max(opts["days"] - 1, 0)))
            ts = day.replace(hour=rng.randint(7, 18), minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0)
            if ts <= now:
                lines.append(f"{101 + rng.randrange(len(services.DEMO_NAMES))}\t{ts:%Y-%m-%d %H:%M:%S}\t"
                             f"{rng.choice([0, 1])}\t{rng.choice([1, 15, 4])}\t0\t0\t0\t0")
        status, text = self._call("POST", "/iclock/cdata", {"SN": sn, "table": "ATTLOG", "Stamp": str(int(time.time()))},
                                  "\r\n".join(lines) + "\r\n")
        self.stdout.write(f"punches (ATTLOG, {len(lines)} lines) -> {status} {text.strip()}")

        deadline = time.time() + opts["poll"]
        while time.time() < deadline:
            status, text = self._call("GET", "/iclock/getrequest", {"SN": sn, "INFO": "Ver 6.60,2,0,0"})
            for line in filter(None, text.splitlines()):
                if not line.startswith("C:"):
                    continue
                _, cid, cmd = line.split(":", 2)
                self.stdout.write(f"command {cid}: {cmd}")
                if cmd.startswith("DATA QUERY USERINFO"):
                    self._call("POST", "/iclock/cdata", {"SN": sn, "table": "USERINFO"}, self._users_body())
                self._call("POST", "/iclock/devicecmd", {"SN": sn}, f"ID={cid}&Return=0&CMD={cmd.split()[0]}")
            time.sleep(5)
        self.stdout.write(self.style.SUCCESS("simulation finished"))
