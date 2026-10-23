#!/usr/bin/env python3
"""Interactively migrate network Perform messages to knock over verified TLS."""

import argparse
import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
import getpass
import os
from pathlib import Path
import re
import selectors
import socket
import ssl
import subprocess
import sys
import uuid
import warnings


class MigrationError(Exception):
    pass


def fold(value):
    return value.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


def clean(value):
    return "".join(c if c.isprintable() else "?" for c in value)


def parse_line(line):
    if line.startswith(b"@"):
        line = line.split(b" ", 1)[1]
    prefix = b""
    if line.startswith(b":"):
        prefix, line = line[1:].split(b" ", 1)
    head, separator, trailing = line.partition(b" :")
    fields = head.split()
    if separator:
        fields.append(trailing)
    if not fields:
        raise MigrationError("ZNC sent an empty IRC message.")
    return prefix, fields[0], fields[1:]


class IRC:
    def __init__(self, host, port, context, tls_name, user, password, network=None, prefix="*"):
        self.prefix = prefix
        self.socket = None
        self.reader = None
        try:
            raw = socket.create_connection((host, port), timeout=15)
            try:
                self.socket = context.wrap_socket(raw, server_hostname=tls_name)
            except BaseException:
                raw.close()
                raise
            self.reader = self.socket.makefile("rb")
            identity = f"{user}@knock-migrate" + (f"/{network}" if network else "")
            self.send(f"PASS :{identity}:{password}")
            self.send("NICK knock-migrate")
            self.send("USER knock-migrate 0 * :Knock migration")
            while True:
                _, command, _ = self.read()
                if command == b"001":
                    break
                if command in (b"464", b"465", b"ERROR"):
                    raise MigrationError("ZNC authentication failed.")
            if network:
                replies = self.command("status", f"JumpNetwork {network}")
                if not any(line in (f"Switched to {network}".encode(),
                                    b"You are already connected with this network.") for line in replies):
                    raise MigrationError("Could not verify the selected ZNC network.")
        except BaseException:
            self.close()
            raise

    def send(self, line):
        if any(c in line for c in "\r\n\0") or len(line.encode()) > 510:
            raise MigrationError("A command contains invalid characters or exceeds the IRC line limit.")
        self.socket.sendall(line.encode() + b"\r\n")

    def read(self):
        while True:
            line = self.reader.readline(65537)
            if not line or len(line) > 65536 or not line.endswith(b"\n"):
                raise MigrationError("ZNC disconnected or sent an invalid response.")
            prefix, command, params = parse_line(line.rstrip(b"\r\n"))
            if command == b"PING":
                self.send("PONG :" + params[-1].decode())
                continue
            if command == b"ERROR":
                raise MigrationError("ZNC closed the connection.")
            return prefix, command, params

    def command(self, module, command):
        target = f"{self.prefix}{module}"
        marker = "knock-migrate-" + uuid.uuid4().hex
        self.send(f"PRIVMSG {target} :{command}")
        # ZNC processes commands synchronously. Its PONG delimits the complete reply,
        # including tables, without guessing how long a response might take.
        self.send(f"PING :{marker}")
        replies = []
        for _ in range(100000):
            sender, kind, params = self.read()
            if kind == b"PONG" and params[-1] == marker.encode():
                return replies
            if (kind in (b"PRIVMSG", b"NOTICE") and len(params) == 2
                    and sender.split(b"!", 1)[0] == target.encode()
                    and sender.endswith(b"@znc.in")):
                replies.append(params[-1])
        raise MigrationError("ZNC did not finish its command response.")

    def expect(self, module, command, response):
        if not any(line.decode() == response for line in self.command(module, command)):
            # Never include command text or raw replies: they can contain credentials.
            raise MigrationError(f"{module} did not confirm the requested change; inspect its state before retrying.")

    def close(self):
        if self.reader:
            self.reader.close()
        if self.socket:
            self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def table(lines, columns):
    borders = [line for line in lines if re.fullmatch(rb"\+(?:-+\+)+", line)]
    if not borders:
        raise MigrationError("Expected an English ZNC table; no changes made to this selection.")
    border = borders[0]
    positions = [i for i, byte in enumerate(border) if byte == ord("+")]
    rows = []
    for line in lines:
        if not line.startswith(b"|"):
            continue
        if len(line) != len(border) or any(line[i:i + 1] != b"|" for i in positions):
            raise MigrationError("Malformed or truncated ZNC table.")
        # ZNC pads columns by byte length. Splitting on pipes would corrupt keys
        # containing '|'; decoding before slicing would corrupt Unicode columns.
        rows.append([line[a + 2:b - 1].rstrip(b" ").decode()
                     for a, b in zip(positions, positions[1:])])
    if len(borders) != 3 or not rows or rows[0] != columns or borders[-1] != border:
        raise MigrationError("Unexpected ZNC table format; use an English ZNC session.")
    return rows[1:]


def modules(client):
    result = {"User": set(), "Network": set(), "Global": set()}
    section = None
    for line in client.command("status", "ListMods"):
        if line in (b"User modules:", b"Network modules:", b"Global modules:"):
            section = line.split()[0].decode()
        elif line.startswith(b"\x02") and section:
            result[section].add(line[1:].split(b"\x0f", 1)[0].decode())
    return result


def perform(client):
    lines = client.command("perform", "List")
    if lines == [b"No commands in your perform list."]:
        return []
    rows = table(lines, ["Id", "Perform", "Expanded"])
    if [row[0] for row in rows] != [str(i) for i in range(1, len(rows) + 1)]:
        raise MigrationError("Unexpected Perform entry numbering.")
    return [(row[1], row[2]) for row in rows]


def rules(client):
    lines = client.command("knock", "List")
    if not any(b"Messages hidden." in line for line in lines):
        raise MigrationError("Unable to read knock configuration; check that the module is installed.")
    result = {}
    for line in lines:
        match = re.fullmatch(r"(\S+) -> (\S+): (.+)", line.decode())
        if match:
            channel, bot, state = match.groups()
            result[fold(channel)] = (fold(bot), state)
    return result


def channels(value):
    names = list(dict.fromkeys(fold(name) for name in re.split(r"[,\s]+", value.strip()) if name))
    if not names or any(name[0] not in "#&+!" or any(ord(c) < 32 or c in ",:" for c in name)
                        for name in names):
        raise MigrationError("Enter explicit channel names, such as #one,#two.")
    return names


@dataclass
class Account:
    user: str
    password: str = field(repr=False)
    admin: bool = False


@dataclass
class Selection:
    index: int
    bot: str
    message: str = field(repr=False)
    channels: list[str]


@dataclass
class Plan:
    account: Account
    network: str
    snapshot: list = field(repr=False)
    selections: list[Selection]


def inspect(account, network, snapshot, existing, show_messages):
    selections = []
    used = set()
    for index, (command, expanded) in enumerate(snapshot, 1):
        match = re.fullmatch(r"PRIVMSG ([^ ,:!@\s]+) :(.+)", command, re.IGNORECASE)
        if not match or expanded or match[1][0] in "#&+!:$@":
            print(f"  Perform #{index}: skipped (not a static private message).")
            continue
        bot, message = match.groups()
        if any(c in command for c in "\r\n\0"):
            print(f"  Perform #{index}: skipped (message contains an IRC line delimiter).")
            continue
        print(f"  Perform #{index} -> {clean(bot)} (message hidden)")
        if show_messages:
            print(f"    {clean(message)}")
        while True:
            answer = input("    Channels to recover (comma-separated, Enter to skip): ").strip()
            if not answer:
                break
            try:
                names = channels(answer)
                if used.intersection(names):
                    raise MigrationError("A channel cannot use two selected knock messages.")
                wire = f"PRIVMSG *knock :Set {','.join(names)} {bot} {message}"
                if len(wire.encode()) > 510:
                    raise MigrationError("This group is too large for one IRC command; use smaller groups.")
                if any(name in existing for name in names):
                    print("    Replaces existing knock rules for: " + ", ".join(clean(n) for n in names if n in existing))
                selections.append(Selection(index, bot, message, names))
                used.update(names)
                break
            except MigrationError as error:
                print(f"    {error}")
    return Plan(account, network, snapshot, selections) if selections else None


def unchanged(client, expected):
    # Perform has index-based deletion, not compare-and-delete. Recheck before each
    # edit, and require other clients not to edit Perform during migration.
    current = perform(client)
    if [command for command, _ in current] != [command for command, _ in expected]:
        raise MigrationError("Perform changed since inspection; stop editing it elsewhere and rerun. No further entries will be removed.")


def apply(client, plan, delay, initial, maximum):
    unchanged(client, plan.snapshot)
    if "knock" not in modules(client)["Network"]:
        replies = client.command("status", "LoadMod --type=network knock")
        if not any(line.startswith(b"Loaded module knock") for line in replies):
            raise MigrationError("Could not load knock; Perform entries retained.")
    client.expect("knock", f"InitialDelay {delay}",
                  f"Initial delay: {delay} seconds; existing schedules preserved.")
    client.expect("knock", f"Backoff {initial} {maximum}",
                  f"Knock backoff: {initial}–{maximum} seconds; pending delays reset.")
    for selection in plan.selections:
        names = ",".join(selection.channels)
        client.expect("knock", f"Set {names} {selection.bot} {selection.message}",
                      f"Knock configured for {names}; message hidden.")
    observed = rules(client)
    if any(observed.get(name, (None,))[0] != fold(selection.bot)
           for selection in plan.selections for name in selection.channels):
        raise MigrationError("Knock verification failed; Perform entries retained.")
    return observed


def cleanup(client, plan):
    expected = list(plan.snapshot)
    removed = 0
    for selection in sorted(plan.selections, key=lambda s: s.index, reverse=True):
        unchanged(client, expected)
        observed = rules(client)
        if not all(observed.get(name) == (fold(selection.bot), "joined") for name in selection.channels):
            print(f"  Retained Perform #{selection.index}: target channels are not all joined.")
            continue
        client.expect("perform", f"Del {selection.index}", "Command Erased.")
        expected.pop(selection.index - 1)
        unchanged(client, expected)
        removed += 1
    return removed


@contextmanager
def endpoint(args):
    if not args.kubernetes:
        yield args.host, args.port, ssl.create_default_context(cafile=args.ca_file), args.tls_name or args.host
        return
    kubectl = ["kubectl"]
    config = os.environ.get("KUBECONFIG") or Path(__file__).resolve().parents[4] / "kubeconfig"
    if Path(config).is_file():
        kubectl += ["--kubeconfig", str(config)]
    kubectl += ["-n", "default"]
    ca = subprocess.check_output(kubectl + ["get", "secret", "znc-tls", "-o", r"jsonpath={.data.ca\.crt}"])
    context = ssl.create_default_context(cadata=base64.b64decode(ca).decode())
    process = subprocess.Popen(kubectl + ["port-forward", "--address=127.0.0.1", "service/znc", ":6697"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=20):
                raise MigrationError("Timed out starting the ZNC port-forward.")
            line = process.stdout.readline()
        match = re.search(rb"Forwarding from 127\.0\.0\.1:(\d+)", line)
        if not match:
            raise MigrationError("Could not start the ZNC port-forward; check kubectl access.")
        yield "127.0.0.1", int(match[1]), context, "znc.default.svc.cluster.local"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdout.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    address = parser.add_mutually_exclusive_group(required=True)
    address.add_argument("--kubernetes", action="store_true", help="Port-forward the repository's ZNC service and trust its cluster CA")
    address.add_argument("--host", help="ZNC IRC TLS hostname")
    parser.add_argument("--port", type=int, default=6697)
    parser.add_argument("--tls-name", help="Certificate hostname when connecting through a tunnel")
    parser.add_argument("--ca-file", help="PEM CA certificate for direct connections")
    parser.add_argument("--user", action="append", default=[], help="ZNC username; repeat for multiple users, including an administrator")
    parser.add_argument("--initial-delay", type=int, default=30)
    parser.add_argument("--backoff", type=int, nargs=2, default=[60, 1800], metavar=("INITIAL", "MAXIMUM"))
    parser.add_argument("--show-messages", action="store_true", help="Display Perform message bodies, including authentication keys")
    args = parser.parse_args(argv)
    initial, maximum = args.backoff
    if not 0 <= args.initial_delay <= 86400 or not 30 <= initial <= maximum <= 86400:
        parser.error("Require delay 0–86400 and backoff 30 <= initial <= maximum <= 86400.")
    users = args.user or input("ZNC usernames (space-separated, include an administrator): ").split()
    if not users or len(set(users)) != len(users) or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", user) for user in users):
        parser.error("Supply distinct ZNC usernames containing only letters, digits, _, . or -.")
    try:
        with endpoint(args) as (host, port, context, tls_name):
            def connect(account, network=None):
                return IRC(host, port, context, tls_name, account.user, account.password, network)

            accounts = []
            plans = []
            print("Inspecting only; no configuration changes until you approve the summary.")
            for user in users:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    try:
                        password = getpass.getpass(f"ZNC password for {user}: ")
                    except getpass.GetPassWarning:
                        raise MigrationError("Run in an interactive terminal so passwords can be entered without echo.") from None
                account = Account(user, password)
                accounts.append(account)
                with connect(account) as client:
                    account.admin = any(line.startswith(b"\x02SaveConfig\x0f")
                                        for line in client.command("status", "Help SaveConfig"))
                    lines = client.command("status", "ListNetworks")
                    networks = [] if lines == [b"No networks"] else [row[0] for row in table(
                        lines, ["Network", "On IRC", "IRC Server", "IRC User", "Channels"])]
                for network in networks:
                    if not re.fullmatch(r"[A-Za-z0-9_-]+", network):
                        raise MigrationError("Unsupported network name.")
                    print(f"\n{user}/{network}")
                    with connect(account, network) as client:
                        loaded = modules(client)
                        if "perform" not in loaded["Network"]:
                            if "perform" in loaded["User"]:
                                print("  Skipping user-scoped Perform; it is shared across networks.")
                            continue
                        snapshot = perform(client)
                        existing = rules(client) if "knock" in loaded["Network"] else {}
                    plan = inspect(account, network, snapshot, existing, args.show_messages)
                    if plan:
                        plans.append(plan)
            if not plans:
                print("Nothing selected. No configuration changes made.")
                return 0
            admin = next((account for account in accounts if account.admin), None)
            if admin is None:
                raise MigrationError("Include an administrator with --user so SaveConfig can persist module loading. No changes made.")
            print(f"\nMigration preview — initial delay {args.initial_delay}s, retry {initial}–{maximum}s:")
            for plan in plans:
                for selection in plan.selections:
                    print(f"  {plan.account.user}/{plan.network}: Perform #{selection.index} -> "
                          f"{clean(selection.bot)} for {', '.join(map(clean, selection.channels))}")
            print("These timing settings apply to all knock rules on each selected network.")
            print("Do not edit Perform from another client until this finishes.")
            if input("Apply this migration? [y/N] ").lower() != "y":
                print("Cancelled. No configuration changes made.")
                return 0
            for plan in plans:
                with connect(plan.account, plan.network) as client:
                    observed = apply(client, plan, args.initial_delay, initial, maximum)
                print(f"Configured {plan.account.user}/{plan.network}:")
                for selection in plan.selections:
                    for name in selection.channels:
                        print(f"  {clean(name)}: {clean(observed[name][1])}")
            with connect(admin) as client:
                if not any(line.startswith(b"Wrote config to ") for line in client.command("status", "SaveConfig")):
                    raise MigrationError("SaveConfig failed; Perform entries retained.")
            print("Configuration saved. Perform entries are still intact.")
            if input("Remove selected Perform entries whose channels are now all joined? [y/N] ").lower() == "y":
                for plan in plans:
                    with connect(plan.account, plan.network) as client:
                        removed = cleanup(client, plan)
                    print(f"  {plan.account.user}/{plan.network}: removed {removed} selected Perform entries.")
            print("Done. Rerun to migrate remaining entries; existing rules will be shown before replacement.")
            return 0
    except (MigrationError, OSError, ValueError, subprocess.SubprocessError) as error:
        detail = str(error) if isinstance(error, MigrationError) else type(error).__name__
        print(f"Stopped: {detail} Check the affected network before retrying; earlier changes may have completed.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled; completed changes remain. No automatic retries.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
