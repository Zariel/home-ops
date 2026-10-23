"""Check retry timing at module hooks with a controlled clock and ZNC state.

The real ZNC integration tests cover hook dispatch and IRC state transitions.
"""

import importlib.util
from pathlib import Path
import random
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


MODULE = Path(__file__).resolve().parents[1] / "app/resources/knock.py"


class BackoffTest(unittest.TestCase):
    def setUp(self):
        znc = SimpleNamespace(Module=object, CModInfo=SimpleNamespace(NetworkModule=0),
                              CONTINUE=0, HALTCORE=1)
        spec = importlib.util.spec_from_file_location("knock", MODULE)
        self.code = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, znc=znc):
            spec.loader.exec_module(self.code)
        self.now = 0
        clock = patch.object(self.code.time, "monotonic", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        jitter = patch.object(self.code.random, "uniform", random.Random(1).uniform)
        jitter.start()
        self.addCleanup(jitter.stop)
        self.channels = {}
        self.connected = True
        self.network = Mock()
        self.network.FindChan.side_effect = lambda name: self.channels.get(name)
        self.network.AddChan.side_effect = self._add_channel
        self.network.IsIRCConnected.side_effect = lambda: self.connected
        self.network.GetCurNick.return_value = "tester"
        self.sent = []
        self.module = self.code.knock()
        self.module.nv = {}
        self.module.GetNetwork = lambda: self.network
        self.module.PutIRC = self._send
        self.module.PutModule = Mock()
        self.assertTrue(self.module.OnLoad("", SimpleNamespace(s="")))

    def _add_channel(self, name, in_config):
        channel = Mock()
        channel.GetName.return_value = name
        channel.IsOn.return_value = False
        channel.IsDisabled.return_value = False
        self.channels[name] = channel

    def _send(self, line):
        self.sent.append((self.now, line))
        return True

    def _tick(self):
        for channel in self.channels.values():
            self.module.OnJoining(channel)

    def _connect(self):
        self.connected = True
        callback = getattr(self.module, "OnIRCConnected", None)
        if callback:
            callback()

    def _joined(self, name, own=True):
        message = Mock()
        message.GetNick.return_value.NickEquals.return_value = own
        message.GetTarget.return_value = name
        if own:
            self.channels[name].IsOn.return_value = True
        self.module.OnJoinMessage(message)

    def test_initial_delay(self):
        self.module.OnModCommand("InitialDelay 120")
        self.module.OnModCommand("Set #one,#two Bot one,two fake-key")
        self.assertEqual(self.sent, [])

        self.now = 30
        self.module.OnModCommand("Set #two Bot one,two fake-key")
        self.now = 60
        self._joined("#one")
        self.connected = False
        self.now = 119
        self._connect()
        self._tick()
        self.assertEqual(self.sent, [])

        self.now = 120
        self._tick()
        self.assertEqual(self.sent, [(120, "PRIVMSG Bot :one,two fake-key")])
        self.now = 179
        self._tick()
        self.assertEqual(len(self.sent), 1)
        self.now = 180
        self._tick()
        self.assertEqual(len(self.sent), 2)

        # A fresh recovery receives the initial delay again after the group recovers.
        self._joined("#two")
        self.channels["#one"].IsOn.return_value = False
        self.now = 200
        self._tick()
        self.now = 319
        self._tick()
        self.assertEqual(len(self.sent), 2)
        self.now = 320
        self._tick()
        self.assertEqual(self.sent[-1], (320, "PRIVMSG Bot :one,two fake-key"))

    def test_delay_configuration(self):
        self.module.OnModCommand("InitialDelay 120")
        for value in ("-1", "86401", "nope"):
            self.module.OnModCommand(f"InitialDelay {value}")
            self.module.PutModule.assert_called_with(
                "InitialDelay requires an integer from 0 to 86400 seconds.")

        self.assertTrue(self.module.OnLoad("", SimpleNamespace(s="")))
        self.module.OnModCommand("Set #one Bot fake-key")
        self.now = 60
        self.module.OnModCommand("InitialDelay 0")
        self._tick()
        self.assertEqual(self.sent, [])
        self.now = 120
        self._tick()
        self.assertEqual(self.sent, [(120, "PRIVMSG Bot :fake-key")])

    def test_bounded_backoff(self):
        self.module.OnModCommand("Set #one,#two Bot one,two fake-key")
        self.assertEqual(self.sent, [(0, "PRIVMSG Bot :one,two fake-key")])

        # Polling more often cannot create duplicate knocks for a shared message.
        while len(self.sent) < 8:
            self.now += 1
            self._tick()
            self.assertLess(self.now, 10000)
        delays = [later[0] - earlier[0] for earlier, later in zip(self.sent, self.sent[1:])]
        self.assertEqual(delays[0], 60)
        # Explicit bounds distinguish exponential growth from fixed or linear delays.
        for delay, (lower, upper) in zip(delays[1:], [
            (60, 120), (120, 240), (240, 480), (480, 960), (900, 1800), (900, 1800)
        ]):
            self.assertGreaterEqual(delay, lower)
            self.assertLessEqual(delay, upper)
        self.assertTrue(any(delay < upper for delay, upper in zip(delays[1:],
                                                                [120, 240, 480, 960, 1800, 1800])))

    def test_partial_recovery_and_reconnect(self):
        self.module.OnModCommand("Set #one,#two Bot one,two fake-key")
        self.module.OnModCommand("Set #three OtherBot other-key")
        self.now = 60
        self._tick()
        self.assertEqual(len(self.sent), 4)

        self._joined("#one")
        self._joined("#two", own=False)
        self.connected = False
        self.now = 1000
        self._tick()
        self.assertEqual(len(self.sent), 4)

        self._connect()
        self._tick()
        self.assertEqual(len(self.sent), 6)
        self.connected = False
        self.now += 1
        self._tick()
        self._connect()
        self._tick()
        self.assertEqual(len(self.sent), 6)

        # Full recovery resets only this bot/message, leaving other failures backed off.
        self._joined("#two")
        self.channels["#one"].IsOn.return_value = False
        self._tick()
        self.assertEqual(self.sent[-1], (1001, "PRIVMSG Bot :one,two fake-key"))
        self.assertEqual(len(self.sent), 7)
        self.now = 1060
        self._tick()
        self.assertEqual(len(self.sent), 7)
        self.now = 1061
        self._tick()
        self.assertEqual(self.sent[-1], (1061, "PRIVMSG Bot :one,two fake-key"))
        self.assertEqual(len(self.sent), 8)


if __name__ == "__main__":
    unittest.main()
