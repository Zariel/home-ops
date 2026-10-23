"""Replace automatic channel joins with retryable bot messages."""

import json
import random
import re
import time

import znc


def _fold(value):
    # Match ZNC's byte-oriented channel lookup without folding Unicode names together.
    return value.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


def _knock_key(rule):
    return (_fold(rule["target"]), rule["message"])


class knock(znc.Module):
    description = "Retry bot authentication until configured channels are joined"
    module_types = [znc.CModInfo.NetworkModule]

    def OnLoad(self, args, message):
        self._backoff = {}
        try:
            settings = json.loads(self.nv.get("settings", "{}"))
            self._delay = settings.get("delay", 0)
            self._initial = settings.get("initial", 60)
            self._maximum = settings.get("maximum", 1800)
            self._rules = settings.get("channels", {})
            if (
                type(self._delay) is not int
                or not 0 <= self._delay <= 86400
                or type(self._initial) is not int
                or type(self._maximum) is not int
                or not 30 <= self._initial <= self._maximum <= 86400
            ):
                raise ValueError
            if not isinstance(self._rules, dict):
                raise ValueError
            for channel, rule in self._rules.items():
                self._validate(channel, rule["target"], rule["message"])
        except (ValueError, TypeError, KeyError, AttributeError):
            message.s = "Invalid knock settings; check the module registry."
            return False
        return True

    def _validate(self, channel, target, message):
        if not all(isinstance(value, str) and value for value in (channel, target, message)):
            raise ValueError("Channel, bot nickname, and message are required.")
        if channel[0] not in "#&+!" or any(
            c.isspace() or ord(c) < 32 or c in ",:" for c in channel
        ):
            raise ValueError("Expected one channel name.")
        if target[0] in "#&+!:$@" or any(
            c.isspace() or ord(c) < 32 or c in ",:!@" for c in target
        ):
            raise ValueError("Expected one bot nickname.")
        if any(c in message for c in "\r\n\0"):
            raise ValueError("The message must be a single IRC line.")
        if len(f"PRIVMSG {target} :{message}".encode("utf-8")) > 510:
            raise ValueError("The message exceeds the IRC line limit.")

    def _save(self):
        self.nv["settings"] = json.dumps(
            {"delay": self._delay, "initial": self._initial,
             "maximum": self._maximum, "channels": self._rules}
        )

    def _enable_channel(self, name):
        network = self.GetNetwork()
        channel = network.FindChan(name)
        if not channel:
            network.AddChan(name, True)
            channel = network.FindChan(name)
        channel.SetInConfig(True)
        channel.Enable()
        return channel

    def OnJoining(self, channel):
        rule = self._rules.get(_fold(channel.GetName()))
        if rule is None:
            return znc.CONTINUE

        if (
            self.GetNetwork().IsIRCConnected()
            and not channel.IsOn()
            and not channel.IsDisabled()
        ):
            # A single authentication can grant several channels. Share its backoff,
            # but let ZNC's membership state determine whether any still need it.
            key = _knock_key(rule)
            now = time.monotonic()
            due, limit = self._backoff.setdefault(key, (now + self._delay, self._initial))
            if now >= due:
                if self.PutIRC(f'PRIVMSG {rule["target"]} :{rule["message"]}'):
                    delay = random.uniform(max(self._initial, limit / 2), limit)
                    self._backoff[key] = (now + delay, min(limit * 2, self._maximum))

        # This hook precedes JoinTries accounting; failed knocks must never exhaust it.
        return znc.HALTCORE

    def OnJoinMessage(self, message):
        network = self.GetNetwork()
        if not message.GetNick().NickEquals(network.GetCurNick()):
            return
        rule = self._rules.get(_fold(message.GetTarget()))
        if rule is None:
            return
        key = _knock_key(rule)
        for name, candidate in self._rules.items():
            if _knock_key(candidate) == key:
                channel = network.FindChan(name)
                if channel and not channel.IsDisabled() and not channel.IsOn():
                    return
        # Only completed recovery resets the group, not a reply or a reconnect.
        self._backoff.pop(key, None)

    def OnUserJoinMessage(self, message):
        name = message.GetTarget()
        if _fold(name) not in self._rules:
            return znc.CONTINUE
        channel = self._enable_channel(name)
        if channel.IsOn():
            return znc.CONTINUE
        return self.OnJoining(channel)

    def OnInviteMessage(self, message):
        network = self.GetNetwork()
        if not znc.CNick(message.GetInvitedNick()).NickEquals(network.GetCurNick()):
            return znc.CONTINUE
        name = message.GetChannel()
        channel = network.FindChan(name)
        if (
            _fold(name) in self._rules
            and channel
            and not channel.IsOn()
            and not channel.IsDisabled()
            and network.IsIRCConnected()
        ):
            # Send the invited JOIN directly so it does not become another knock.
            channel.JoinUser()
        return znc.CONTINUE

    def OnModCommand(self, command):
        parts = command.split(None, 3)
        action = parts[0].lower() if parts else "help"
        try:
            if action == "set":
                header = re.match(r"[ \t]*set[ \t]+(\S+)[ \t]+(\S+)[ \t]", command, re.IGNORECASE)
                if header is None:
                    raise ValueError("Usage: Set <#channel[,#channel...]> <bot> <message>")
                names, target = header.groups()
                # Only the first separator after the bot belongs to the command.
                # Everything after it is the literal PRIVMSG body, including whitespace.
                message = command[header.end():]
                names = list(dict.fromkeys(_fold(name) for name in names.split(",")))
                for name in names:
                    self._validate(name, target, message)
                for name in names:
                    self._rules[name] = {"target": target, "message": message}
                self._save()
                channels = [self._enable_channel(name) for name in names]
                self.PutModule(f'Knock configured for {",".join(names)}; message hidden.')
                for channel in channels:
                    self.OnJoining(channel)
            elif action == "del" and len(parts) == 2:
                name = _fold(parts[1])
                if name not in self._rules:
                    raise ValueError("No knock configured for that channel.")
                del self._rules[name]
                self._save()
                self.PutModule(f"Knock removed for {name}; normal ZNC joining applies.")
            elif action == "initialdelay" and len(parts) == 2:
                error = "InitialDelay requires an integer from 0 to 86400 seconds."
                if not parts[1].isascii() or not parts[1].isdecimal():
                    raise ValueError(error)
                delay = int(parts[1])
                if not 0 <= delay <= 86400:
                    raise ValueError(error)
                self._delay = delay
                self._save()
                self.PutModule(f"Initial delay: {delay} seconds; existing schedules preserved.")
            elif action == "backoff" and len(parts) == 3:
                error = "Backoff requires 30 <= initial <= maximum <= 86400 seconds."
                if not all(value.isascii() and value.isdecimal() for value in parts[1:]):
                    raise ValueError(error)
                initial, maximum = map(int, parts[1:])
                if not 30 <= initial <= maximum <= 86400:
                    raise ValueError(error)
                self._initial, self._maximum = initial, maximum
                self._backoff.clear()
                self._save()
                self.PutModule(f"Knock backoff: {initial}–{maximum} seconds; pending delays reset.")
            elif action == "list" and len(parts) == 1:
                self.PutModule(f"Initial delay: {self._delay} seconds.")
                self.PutModule(f"Knock backoff: {self._initial}–{self._maximum} seconds. Messages hidden.")
                for name, rule in sorted(self._rules.items()):
                    channel = self.GetNetwork().FindChan(name)
                    if not channel or channel.IsDisabled():
                        state = "inactive (use JOIN to resume)"
                    elif channel.IsOn():
                        state = "joined"
                    elif not self.GetNetwork().IsIRCConnected():
                        state = "disconnected"
                    else:
                        state = "waiting for channel"
                    self.PutModule(f'{name} -> {rule["target"]}: {state}')
            else:
                self.PutModule("Set <#channel[,#channel...]> <bot> <message> | Del <#channel> | List | InitialDelay <seconds> | Backoff <initial> <maximum>")
        except ValueError as error:
            self.PutModule(str(error))
