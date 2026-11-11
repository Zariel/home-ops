"""Exercise knock through a real ZNC process and a loopback IRC server."""

import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import tempfile
import time
import unittest


MODULE = Path(__file__).resolve().parents[1] / "app/resources/knock.py"


class KnockTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="znc-knock-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "configs").mkdir()
        (self.root / "modules").mkdir()
        shutil.copyfile(MODULE, self.root / "modules/knock.py")
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.addCleanup(self.listener.close)
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            self.client_port = port.getsockname()[1]
        (self.root / "configs/znc.conf").write_text(f"""
Version = 1.10.3
ConnectDelay = 0
ServerThrottle = 0
LoadModule = modpython
<Listener test>
    Port = {self.client_port}
    Host = 127.0.0.1
    SSL = false
</Listener>
<User test>
    Pass = plain#test
    Admin = true
    Nick = tester
    Ident = tester
    RealName = Test
    JoinTries = 1
    LoadModule = controlpanel
    <Network test>
        Server = 127.0.0.1 {self.listener.getsockname()[1]}
        FloodRate = 0
        LoadModule = knock
    </Network>
</User>
""")
        self.process = None
        self.server = None
        self.client = None
        self.addCleanup(self._stop)
        self._start()

    def _start(self):
        self.server_lines = []
        self.client_lines = []
        self.buffers = {}
        self.log = open(self.root / "process.log", "a+")
        self.process = subprocess.Popen(
            [os.environ.get("ZNC", "znc"), "--foreground", "--datadir", str(self.root)],
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        self._until(lambda: self.server is not None)
        self.client = socket.create_connection(("127.0.0.1", self.client_port))
        self._send(self.client, "PASS test/test:test", "NICK tester", "USER test 0 * :Test")
        self._until(lambda: any(" 001 " in line for line in self.client_lines))
        self._command("List", "Messages hidden.")

    def _stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
        for connection in (self.server, self.client):
            if connection:
                connection.close()
        self.server = self.client = None
        if hasattr(self, "log"):
            self.log.close()

    def _send(self, connection, *lines):
        connection.sendall(("\r\n".join(lines) + "\r\n").encode())

    def _pump(self, timeout=0.1):
        sockets = [self.listener] + [s for s in (self.server, self.client) if s]
        readable, _, _ = select.select(sockets, [], [], timeout)
        for connection in readable:
            if connection is self.listener:
                if self.server:
                    self.server.close()
                self.server, _ = self.listener.accept()
                continue
            data = connection.recv(65536)
            if not data and connection is self.server:
                connection.close()
                self.server = None
                continue
            self.assertTrue(data, "Unexpected client socket closure")
            buffer = self.buffers.get(connection, b"") + data
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.rstrip(b"\r").decode()
                if connection is self.client:
                    self.client_lines.append(line)
                else:
                    self.server_lines.append(line)
                    if line.startswith("CAP LS"):
                        self._send(connection, ":server CAP * LS :")
                    elif line.startswith("USER "):
                        self._send(
                            connection,
                            ":server 001 tester :Welcome",
                            ":server 005 tester CHANTYPES=#& CASEMAPPING=ascii :Supported",
                            ":server 376 tester :End of MOTD",
                        )
                    elif line.startswith("PING "):
                        self._send(connection, "PONG " + line[5:])
                    elif line.startswith("QUIT "):
                        connection.close()
                        self.server = None
            self.buffers[connection] = buffer

    def _until(self, condition, timeout=10):
        deadline = time.monotonic() + timeout
        while not condition():
            if self.process.poll() is not None:
                self.fail((self.root / "process.log").read_text())
            if time.monotonic() >= deadline:
                self.fail(f"Timed out; server={self.server_lines!r}; client={self.client_lines!r}; "
                          f"log={(self.root / 'process.log').read_text()}")
            self._pump()

    def _observe(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._pump()

    def _command(self, command, response):
        self.client_lines.clear()
        self._send(self.client, f"PRIVMSG *knock :{command}", "PING :command-end")
        self._until(lambda: any(" PONG " in line and "command-end" in line
                                for line in self.client_lines))
        self.assertTrue(any(response in line for line in self.client_lines),
                        self.client_lines)

    def _join(self, channel):
        self._send(self.server, f":tester!test@localhost JOIN :{channel}")
        self._until(lambda: f"MODE {channel}" in self.server_lines)

    def test_recovery(self):
        # One bot authenticates two channels, a separate bot handles a third.
        self._command("Backoff 30 30", "30–30 seconds")
        self._command("Set #one,#two BotUser one,two fake-key", "configured")
        self._command("Set #three OtherBot knock other-key", "configured")
        first = "PRIVMSG BotUser :one,two fake-key"
        other = "PRIVMSG OtherBot :knock other-key"
        self._until(lambda: first in self.server_lines and other in self.server_lines)
        self.assertEqual(self.server_lines.count(first), 1)
        self.assertFalse(any(line.startswith("JOIN ") for line in self.server_lines))

        # Bot missing, then API failure: neither an error nor a reply is success.
        self._send(self.server, ":server 401 tester BotUser :No such nick")
        self._join("#one")
        self._join("#three")
        self._until(lambda: self.server_lines.count(first) >= 2, timeout=65)
        self.assertEqual(self.server_lines.count(other), 1)
        self._send(self.server, ":BotUser!bot@localhost NOTICE tester :API unavailable")
        self._until(lambda: self.server_lines.count(first) >= 3, timeout=65)
        self.assertFalse(any(line.startswith("JOIN ") for line in self.server_lines))

        # Invites for other users or unmanaged channels must not trigger a JOIN.
        self._send(self.server, ":BotUser!bot@localhost INVITE somebody #two",
                   ":BotUser!bot@localhost INVITE tester #unmanaged")
        self._observe(0.2)
        self.assertFalse(any(line.startswith("JOIN ") for line in self.server_lines))
        self._send(self.server, ":BotUser!bot@localhost INVITE tester #two")
        self._until(lambda: any(line.rstrip() == "JOIN #two" for line in self.server_lines))
        self._join("#two")
        self._command("List", "#two -> BotUser: joined")
        self.assertFalse(any("fake-key" in line or "other-key" in line
                             for line in self.client_lines))
        sent = self.server_lines.count(first)
        self._observe(32)
        self.assertEqual(self.server_lines.count(first), sent)

        # Completed recovery allows a fresh knock after a later disconnect.
        self._send(self.client, "PRIVMSG *status :Jump")
        self._until(lambda: self.server_lines.count(first) > sent, timeout=40)
        self._until(lambda: self.server_lines.count(other) == 2, timeout=40)

    def test_persistence_and_part(self):
        self._command("Set #One BotUser identify fake-key", "configured")
        self._join("#one")
        self._send(self.client, "PART #one :Done")
        self._until(lambda: any(line.startswith("PART #one") for line in self.server_lines))
        self._send(self.server, ":tester!test@localhost PART #one :Done")
        self._until(lambda: any(" PART #one " in line for line in self.client_lines))
        self._command("List", "inactive")
        self._send(self.server, ":BotUser!bot@localhost INVITE tester #one")
        self._observe(0.2)
        self.assertFalse(any(line.startswith("JOIN ") for line in self.server_lines))

        self._send(self.client, "PRIVMSG *status :SaveConfig")
        self._until(lambda: any("Wrote config to " in line for line in self.client_lines))
        self._stop()
        self._start()
        self._command("List", "#one -> BotUser: inactive")
        self.assertFalse(any(line.startswith("PRIVMSG BotUser") for line in self.server_lines))
        self._send(self.client, "JOIN #ONE")
        self._until(lambda: "PRIVMSG BotUser :identify fake-key" in self.server_lines)
        self._join("#ONE")
        self.client_lines.clear()
        self._send(self.client, "PRIVMSG *status :SaveConfig")
        self._until(lambda: any("Wrote config to " in line for line in self.client_lines))
        self._stop()
        self._start()
        self._until(lambda: "PRIVMSG BotUser :identify fake-key" in self.server_lines, timeout=40)
        self._command("List", "#one -> BotUser: waiting")

    def test_literal_message(self):
        self._command("Set #one Bot   knock #chan user ..key  ", "configured")
        self._until(lambda: "PRIVMSG Bot :  knock #chan user ..key  " in self.server_lines)

        self._command("Set #two Bot :identify %nick% ${key} |\t ", "configured")
        self._until(lambda: "PRIVMSG Bot ::identify %nick% ${key} |\t " in self.server_lines)
        self._command("Set #three Bot    ", "configured")
        self._until(lambda: "PRIVMSG Bot :   " in self.server_lines)

        self.client_lines.clear()
        self._send(self.client, "PRIVMSG *status :SaveConfig")
        self._until(lambda: any("Wrote config to " in line for line in self.client_lines))
        self._stop()
        self._start()
        self._until(lambda: "PRIVMSG Bot :  knock #chan user ..key  " in self.server_lines, timeout=40)
        self._until(lambda: "PRIVMSG Bot ::identify %nick% ${key} |\t " in self.server_lines, timeout=40)

    def test_configuration(self):
        for command, response in (
            ("Set #one Bot,Other secret", "one bot nickname"),
            ("Set #one #public secret", "one bot nickname"),
            ("Set #one,not-a-channel Bot secret", "one channel name"),
            ("Set #one Bot " + "é" * 250, "IRC line limit"),
            ("Backoff 0 1800", "30 <= initial"),
            ("Backoff nope 1800", "30 <= initial"),
            ("Backoff 120 60", "30 <= initial"),
        ):
            with self.subTest(command=command):
                self._command(command, response)
        self.assertFalse(any(line.startswith("PRIVMSG ") for line in self.server_lines))

        self._command("Set #one Bot identify fake-key", "configured")
        self._command("Set #ONE Bot identify updated-key", "configured")
        self._command("List", "#one -> Bot: waiting")
        self.assertEqual(sum("#one ->" in line for line in self.client_lines), 1)
        self._command("Del #ONE", "removed")
        self._command("List", "Messages hidden")
        self.assertFalse(any("#one ->" in line for line in self.client_lines))

        # ZNC folds ASCII case; distinct Unicode channel names must remain distinct.
        self._command("Set #Ä Bot first-key", "configured")
        self._command("Set #ä Bot second-key", "configured")
        self._command("List", "#Ä -> Bot: waiting")
        self.assertTrue(any("#ä -> Bot: waiting" in line for line in self.client_lines))
        self._send(self.client, "JOIN #ordinary")
        self._until(lambda: any(line.split()[:2] == ["JOIN", "#ordinary"]
                                for line in self.server_lines))

    def test_initial_delay(self):
        self._command("InitialDelay 2", "Initial delay: 2 seconds")
        self._command("Set #one,#two Bot one,two fake-key", "configured")
        knock = "PRIVMSG Bot :one,two fake-key"
        self._observe(1)
        self.assertNotIn(knock, self.server_lines)
        self._until(lambda: knock in self.server_lines, timeout=40)
        self.assertEqual(self.server_lines.count(knock), 1)

        self._command("InitialDelay 120", "Initial delay: 120 seconds")
        self._send(self.client, "PRIVMSG *status :SaveConfig")
        self._until(lambda: any("Wrote config to " in line for line in self.client_lines))
        self._stop()
        self._start()
        self._command("List", "Initial delay: 120 seconds")
        self._observe(1)
        self.assertNotIn(knock, self.server_lines)

    def test_disabled_channel(self):
        self._command("Set #one Bot identify fake-key", "configured")
        self._join("#one")
        self._send(self.server, ":operator!op@localhost KICK #one tester :Maintenance")
        self._until(lambda: any(" KICK #one tester " in line for line in self.client_lines))
        self._command("List", "inactive")

        self._send(self.server, ":Bot!bot@localhost INVITE tester #one")
        self._observe(0.2)
        self.assertFalse(any(line.startswith("JOIN ") for line in self.server_lines))

        self._send(self.client, "JOIN #one")
        self._command("List", "waiting for channel")
        self._send(self.server, ":Bot!bot@localhost INVITE tester #one")
        self._until(lambda: any(line.split()[:2] == ["JOIN", "#one"]
                                for line in self.server_lines))


if __name__ == "__main__":
    unittest.main()
