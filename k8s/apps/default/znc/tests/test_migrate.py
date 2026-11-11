"""Migrate through the terminal entry point against real ZNC with TLS and IRC peers."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import warnings
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("migrate_knock", ROOT / "migrate_knock.py")
migrate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = migrate
spec.loader.exec_module(migrate)


class IRCServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Peer(socketserver.StreamRequestHandler):
    def handle(self):
        nick = "tester"
        try:
            for raw in self.rfile:
                _, command, params = migrate.parse_line(raw.rstrip(b"\r\n"))
                if command == b"NICK":
                    nick = params[0].decode()
                elif command == b"CAP" and params[0] == b"LS":
                    self.send(":server CAP * LS :")
                elif command == b"USER":
                    self.send(f":server 001 {nick} :Welcome",
                              f":server 005 {nick} CHANTYPES=#& CASEMAPPING=ascii :Supported",
                              f":server 376 {nick} :End of MOTD")
                elif command == b"PING":
                    self.send("PONG :" + params[-1].decode())
                elif command == b"PRIVMSG":
                    bot, message = (param.decode() for param in params)
                    self.server.messages.append((nick, bot, message))
                    if self.server.join:
                        names = "#three" if bot == "OtherBot" else message.split()[0]
                        for name in names.split(","):
                            self.send(f":{nick}!test@localhost JOIN :{name}")
                elif command == b"QUIT":
                    return
        except (ConnectionError, OSError):
            pass

    def send(self, *lines):
        self.wfile.write(("\r\n".join(lines) + "\r\n").encode())
        self.wfile.flush()


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="znc-migration-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.server = IRCServer(("127.0.0.1", 0), Peer)
        self.server.messages = []
        self.server.join = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            self.port = port.getsockname()[1]
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(self.root / "key.pem"), "-out", str(self.root / "cert.pem"),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (self.root / "znc.pem").write_bytes((self.root / "key.pem").read_bytes() +
                                           (self.root / "cert.pem").read_bytes())
        (self.root / "configs").mkdir()
        (self.root / "modules").mkdir()
        shutil.copyfile(ROOT / "app/resources/knock.py", self.root / "modules/knock.py")
        self.accounts = {
            "alpha": migrate.Account("alpha", "alpha password", True),
            "beta": migrate.Account("beta", "beta-password"),
        }
        config = f"""Version = 1.10.3
ConnectDelay = 0
ServerThrottle = 0
LoadModule = modpython
<Listener test>
    Port = {self.port}
    Host = 127.0.0.1
    SSL = true
</Listener>
"""
        self.networks = [("alpha", "first"), ("alpha", "second"), ("beta", "first")]
        for user, account in self.accounts.items():
            config += f"""<User {user}>
    Pass = plain#{account.password}
    Admin = {'true' if account.admin else 'false'}
    Nick = {user}
    Ident = tester
    RealName = Test
"""
            for owner, network in self.networks:
                if owner == user:
                    config += f"""    <Network {network}>
        Nick = {user}_{network}
        Server = 127.0.0.1 {self.server.server_address[1]}
        FloodRate = 0
        LoadModule = perform
    </Network>
"""
            config += "</User>\n"
        (self.root / "configs/znc.conf").write_text(config)
        self.context = ssl.create_default_context(cafile=str(self.root / "cert.pem"))
        self.process = None
        self.addCleanup(self.stop)
        self.start()
        self.original = {
            ("alpha", "first"): ["PRIVMSG Bot :#one,#two fake-key|α", "MODE %nick% +i"],
            ("alpha", "second"): ["PRIVMSG OtherBot :identify second-key"],
            ("beta", "first"): ["PRIVMSG Bot :#four beta-key"],
        }
        for pair, commands in self.original.items():
            with self.connect(*pair) as client:
                for command in commands:
                    client.expect("perform", "Add " + command, "Added!")

    def start(self):
        self.log = open(self.root / "process.log", "a+")
        self.process = subprocess.Popen([
            os.environ.get("ZNC", "znc"), "--foreground", "--datadir", str(self.root)
        ], stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 10
        while True:
            if self.process.poll() is not None:
                self.fail((self.root / "process.log").read_text())
            try:
                with self.connect("alpha", "first"):
                    return
            except ConnectionRefusedError:
                if time.monotonic() > deadline:
                    self.fail("ZNC did not start")
                time.sleep(0.05)

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
            self.log.close()

    def connect(self, user, network=None):
        return migrate.IRC("127.0.0.1", self.port, self.context, "localhost", user,
                           self.accounts[user].password, network)

    def run_tool(self, answers, users=("alpha", "beta"), before_answer=None, extra=()):
        output = io.StringIO()
        replies = iter(answers)

        def answer(prompt):
            if before_answer:
                before_answer(prompt)
            return next(replies)

        args = ["--host", "127.0.0.1", "--port", str(self.port), "--tls-name", "localhost",
                "--ca-file", str(self.root / "cert.pem"), "--initial-delay", "0"]
        for user in users:
            args += ["--user", user]
        args += list(extra)
        with patch("builtins.input", side_effect=answer), \
                patch.object(migrate.getpass, "getpass", side_effect=[self.accounts[u].password for u in users]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = migrate.main(args)
        for secret in ("fake-key", "second-key", "third-key", "beta-key", "alpha password", "beta-password"):
            self.assertNotIn(secret, output.getvalue())
        return result, output.getvalue()

    def wait_joined(self, prompt, pairs=None):
        if not prompt.startswith("Remove selected"):
            return
        deadline = time.monotonic() + 10
        while True:
            ready = True
            for pair in pairs or self.networks:
                with self.connect(*pair) as client:
                    observed = migrate.rules(client)
                    ready &= bool(observed) and all(state == "joined" for _, state in observed.values())
            if ready:
                return
            if time.monotonic() >= deadline:
                self.fail("Target channels did not join")
            time.sleep(0.05)

    def assert_original(self):
        for pair, original in self.original.items():
            with self.connect(*pair) as client:
                self.assertEqual([raw for raw, _ in migrate.perform(client)], original)

    def test_migrate_and_restart(self):
        result, output = self.run_tool(["#one,#two", "#three", "#four", "y", "y"],
                                       before_answer=self.wait_joined)
        self.assertEqual(result, 0, output)
        expected = {("alpha", "first"): ["MODE %nick% +i"],
                    ("alpha", "second"): [], ("beta", "first"): []}
        for pair, remaining in expected.items():
            with self.connect(*pair) as client:
                self.assertEqual([raw for raw, _ in migrate.perform(client)], remaining)

        # A new process must recover channels using only the saved knock configuration.
        self.stop()
        self.server.messages.clear()
        self.start()
        deadline = time.monotonic() + 40
        expected_messages = {("alpha_first", "Bot", "#one,#two fake-key|α"),
                             ("alpha_second", "OtherBot", "identify second-key"),
                             ("beta_first", "Bot", "#four beta-key")}
        while not expected_messages.issubset(set(self.server.messages)):
            self.assertLess(time.monotonic(), deadline, self.server.messages)
            time.sleep(0.05)
        for pair, remaining in expected.items():
            with self.connect(*pair) as client:
                self.assertEqual([raw for raw, _ in migrate.perform(client)], remaining)

    def test_decline(self):
        result, output = self.run_tool(["#one,#two", "#three", "#four", "n"])
        self.assertEqual(result, 0, output)
        self.assert_original()
        for pair in self.networks:
            with self.connect(*pair) as client:
                self.assertNotIn("knock", migrate.modules(client)["Network"])

    def test_pending_channels_retain_perform(self):
        self.server.join = False
        result, output = self.run_tool(["#one,#two", "#three", "#four", "y", "y"])
        self.assertEqual(result, 0, output)
        self.assert_original()
        self.assertIn("target channels are not all joined", output)

    def test_stale_plan(self):
        def edit(prompt):
            if prompt.startswith("Apply this"):
                with self.connect("alpha", "first") as client:
                    client.expect("perform", "Add MODE tester +w", "Added!")
        result, output = self.run_tool(["#one,#two", "", "y"], users=("alpha",), before_answer=edit)
        self.assertEqual(result, 1, output)
        self.assertIn("Perform changed", output)
        with self.connect("alpha", "first") as client:
            self.assertNotIn("knock", migrate.modules(client)["Network"])
            self.assertEqual(len(migrate.perform(client)), 3)

    def test_requires_admin(self):
        result, output = self.run_tool(["#four"], users=("beta",))
        self.assertEqual(result, 1, output)
        self.assertIn("Include an administrator", output)
        self.assert_original()

    def test_leading_whitespace(self):
        with self.connect("alpha", "first") as client:
            client.expect("perform", "Del 1", "Command Erased.")
            client.expect("perform", "Add PRIVMSG Bot :  knock #chan user ..key", "Added!")
        self.server.join = False
        result, output = self.run_tool(["#chan", "", "y", "n"], users=("alpha",))
        self.assertEqual(result, 0, output)
        deadline = time.monotonic() + 5
        expected = ("alpha_first", "Bot", "  knock #chan user ..key")
        while expected not in self.server.messages:
            self.assertLess(time.monotonic(), deadline, self.server.messages)
            time.sleep(0.05)

    def test_crlf_perform_entry(self):
        # Reproduce a saved web-form entry: Perform splits on LF and persists CR.
        self.stop()
        registry = self.root / "users/alpha/networks/first/moddata/perform/.registry"
        saved = registry.read_bytes()
        self.assertIn(b"%0a;", saved)
        registry.write_bytes(saved.replace(b"%0a;", b"%0d;%0a;", 1))
        self.start()
        with self.connect("alpha", "first") as client:
            self.assertTrue(migrate.perform(client)[0][0].endswith("\r"))

        result, output = self.run_tool(
            ["#one,#two", "", "y", "y"], users=("alpha",),
            before_answer=lambda prompt: self.wait_joined(prompt, [("alpha", "first")]))
        self.assertEqual(result, 0, output)
        with self.connect("alpha", "first") as client:
            self.assertEqual([raw for raw, _ in migrate.perform(client)], ["MODE %nick% +i"])

        self.stop()
        self.server.messages.clear()
        self.start()
        expected = ("alpha_first", "Bot", "#one,#two fake-key|α")
        deadline = time.monotonic() + 40
        while expected not in self.server.messages:
            self.assertLess(time.monotonic(), deadline, self.server.messages)
            time.sleep(0.05)

    def test_multiple_entries(self):
        with self.connect("alpha", "first") as client:
            client.expect("perform", "Add PRIVMSG ThirdBot :#five third-key", "Added!")
        result, output = self.run_tool(
            ["#one,#two", "#five", "", "y", "y"], users=("alpha",),
            before_answer=lambda prompt: self.wait_joined(prompt, [("alpha", "first")]))
        self.assertEqual(result, 0, output)
        with self.connect("alpha", "first") as client:
            self.assertEqual([raw for raw, _ in migrate.perform(client)], ["MODE %nick% +i"])

    def test_stale_cleanup(self):
        def edit(prompt):
            if prompt.startswith("Remove selected"):
                with self.connect("alpha", "first") as client:
                    client.expect("perform", "Add MODE tester +w", "Added!")
        result, output = self.run_tool(["#one,#two", "", "y", "y"], users=("alpha",), before_answer=edit)
        self.assertEqual(result, 1, output)
        self.assertIn("Perform changed", output)
        with self.connect("alpha", "first") as client:
            self.assertIn("knock", migrate.modules(client)["Network"])
            self.assertEqual([raw for raw, _ in migrate.perform(client)],
                             self.original[("alpha", "first")] + ["MODE tester +w"])

    def test_load_failure_keeps_perform(self):
        with self.connect("alpha") as client:
            client.command("status", "UnloadMod --type=global modpython")
            self.assertNotIn("modpython", migrate.modules(client)["Global"])
        result, output = self.run_tool(["#one,#two", "", "y"], users=("alpha",))
        self.assertEqual(result, 1, output)
        self.assertIn("Could not load knock", output)
        self.assert_original()

    def test_tls_verification(self):
        result, output = self.run_tool([], users=("alpha",), extra=("--tls-name", "wrong.example"))
        self.assertEqual(result, 1, output)
        self.assertIn("SSLCertVerificationError", output)
        self.assert_original()


class MessageTest(unittest.TestCase):
    def test_trailing_whitespace(self):
        body = "  knock #chan\tuser key \\r"
        snapshot = [("PRIVMSG Bot :" + body + " \t\r\n", "")]
        with patch("builtins.input", return_value="#chan"), contextlib.redirect_stdout(io.StringIO()):
            plan = migrate.inspect(migrate.Account("user", "password"), "network", snapshot, {}, False)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.selections[0].message, body)
        self.assertEqual(plan.snapshot, snapshot)

    def test_embedded_delimiters(self):
        for body in ("knock\rkey", "knock\nkey", "knock\0key", "knock key\0"):
            with self.subTest(body=body), patch("builtins.input") as prompt, \
                    contextlib.redirect_stdout(io.StringIO()):
                plan = migrate.inspect(migrate.Account("user", "password"), "network",
                                       [("PRIVMSG Bot :" + body, "")], {}, False)
                self.assertIsNone(plan)
                prompt.assert_not_called()


class PasswordTest(unittest.TestCase):
    def test_refuses_echo_fallback(self):
        def no_terminal(prompt):
            warnings.warn("Cannot control echo", migrate.getpass.GetPassWarning)

        output = io.StringIO()
        with patch.object(migrate, "endpoint", return_value=contextlib.nullcontext(("localhost", 6697, None, "localhost"))), \
                patch.object(migrate.getpass, "getpass", side_effect=no_terminal), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = migrate.main(["--host", "localhost", "--user", "alpha"])
        self.assertEqual(result, 1)
        self.assertIn("without echo", output.getvalue())


if __name__ == "__main__":
    unittest.main()
