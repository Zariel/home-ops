# ZNC channel knocking

The `knock` Python network module retries a private message to a bot until ZNC
joins the configured channels. It supports forced joins and automatically accepts
invitations for configured, enabled channels addressed to your IRC nickname.

ZNC owns server reconnection and channel membership. The module replaces automatic
JOIN attempts through `OnJoining`, before ZNC counts failed join attempts. Bot
errors, replies, and silence do not count as success. Retries continue without a
limit while the channel is missing and enabled.

## Configure a network

The Deployment mounts `app/resources/knock.py` at `/config/modules/knock.py` from
the `znc-modules` ConfigMap. Flux must deploy this change before the module can be
loaded. The container includes `modpython`; the startup script ensures it is loaded
globally before ZNC starts.

From an IRC client connected to the intended ZNC network:

1. Load the module on this network:

   ```irc
   /msg *status LoadMod --type=network knock
   ```

2. Configure each channel or channel group. Replace the example names and
   messages with your values. The message is the literal PRIVMSG body; omit the
   IRC command and its leading colon:

   ```irc
   /msg *knock Set #channel1,#channel2,#channel3 user channel1,channel2,channel3 YOUR_AUTH_KEY
   /msg *knock Set #another BotUser identify YOUR_AUTH_KEY
   /msg *knock Set #third OtherBot some other authentication message
   ```

   `Set` adds and enables the listed channels in ZNC's configuration and starts
   recovery. By default, the first knock is immediate if connected and missing a channel;
   an existing backoff for the same message still applies. The channel list before
   the bot nickname specifies the membership to recover; the message after the
   nickname is sent unchanged. In the first example, the wire command is
   `PRIVMSG user :channel1,channel2,channel3 YOUR_AUTH_KEY`.

   Repeating `Set` replaces the rules for the listed channels. It does not remove
   unlisted channels from an existing configuration; use `Del` to remove their
   rules. Identical messages to the same bot share a retry schedule, including
   when configured with separate `Set` commands.

3. Check status and save ZNC's module and channel configuration:

   ```irc
   /msg *knock List
   /msg *status SaveConfig
   ```

   `List` reports each channel as joined, waiting, disconnected, or inactive. It
   does not display authentication messages. Verify the expected channels appear
   in your IRC client.

4. Remove the corresponding Perform entries with `*perform List` and
   `*perform Del <number>`. Re-list after each deletion because entry numbers
   change. Keep unrelated Perform commands. Perform's list includes its stored
   commands, including authentication keys.

Repeat the network-specific steps for each IRC network. Knock settings are stored
in ZNC's persistent module registry on the `/config` volume. Authentication
messages are stored as plaintext there; keep them out of Git. Your IRC client may
also retain commands in its history.

## Operate the module

To wait before the first knock in each recovery, configure an initial delay before
adding the channel rules:

```irc
/msg *knock InitialDelay 30
```

The delay defaults to 0 (immediate) and accepts 0–86400 seconds. It starts when ZNC
first tries to recover a missing channel while connected. Channels sharing a
bot/message share this delay; additional join attempts and IRC reconnects do not
restart it. Changing `InitialDelay` affects future recovery schedules and preserves
existing ones. The setting persists across restarts; restarting the module starts
a fresh delay. Invitations can still be accepted while waiting.

Backoff is shared per distinct bot/message pair and starts after the first knock.
By default, its retry delay starts at 60 seconds and grows exponentially to a
30-minute cap. Random jitter spreads subsequent attempts: the second delay is
60–120 seconds, the third is 120–240 seconds, and delays at the cap are 15–30
minutes. Retries continue indefinitely at that reduced rate during long outages.

ZNC checks for missing channels approximately every 30 seconds, so an actual retry
can occur up to one check later than its scheduled time, including the first
knock's delay. To set the initial retry interval and cap for this network, in seconds:

```irc
/msg *knock Backoff 60 1800
```

Both values must be between 30 and 86400, with the initial delay no greater than
the cap. Changing `Backoff` resets pending delays. IRC reconnects preserve pending
backoff so a flapping connection cannot repeatedly trigger fresh knocks. Backoff
resets when a JOIN completes recovery of all active channels sharing that message.
Restarting ZNC or reloading the module also resets its in-memory delays. No client
needs to remain attached.

A successful JOIN stops knocks for that channel. If another channel shares its
authentication message and is still missing, retries of that message continue.
If the bot always forces you into several channels together, those retries can
also rejoin a channel you deliberately parted.
Normal ZNC channel controls still apply:

- PART removes the channel from ZNC and stops recovery. Its knock rule remains;
  `/join #channel` adds and enables the channel again.
- A disabled channel stays inactive, including after a kick. Use `/join #channel`
  to resume recovery. The module does not override ZNC's kick policy.
- Detaching a channel does not stop recovery of its upstream membership.
- `Del #channel` removes the knock rule without parting the channel. Normal ZNC
  JOIN behavior then applies.
- Invitations for other users, unconfigured channels, and inactive channels do
  not cause the module to send JOIN.

To disable the module, run `/msg *status UnloadMod knock` on the network and save
the ZNC configuration. Restore the Perform entries if reverting to manual
recovery. Module code updates trigger the Deployment's existing ConfigMap
reloader; the process restart loads the mounted code.

## Validate changes

Run the integration tests with Python 3 and a ZNC 1.10.3 binary built with
`modpython` available:

```sh
python3 -m unittest discover -s k8s/apps/default/znc/tests -v
kubectl kustomize k8s/apps/default/znc/app
```

Set the `ZNC` environment variable to use a binary outside `PATH`. The tests start
disposable ZNC processes, use loopback IRC servers and placeholder keys, and
remove their temporary configuration. They exercise real retry timers, so allow
several minutes. They cover partial recovery, bot/API failure, invitations,
reconnection, persistence, PART/resume, and configuration validation. Additional
tests use a controlled clock to check backoff growth, jitter bounds, the cap, and
reset behavior without waiting through a long outage.

The implementation uses ZNC's
[`OnJoining` and invitation hooks](https://docs.znc.in/classCModule.html) and
the [network join loop](https://github.com/znc/znc/blob/znc-1.10.3/src/IRCNetwork.cpp).
