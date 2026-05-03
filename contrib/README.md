# contrib/

Optional platform integrations and helper infrastructure for eBay Hunter.
Nothing here is required to run the tool — these are convenience additions.

---

## com.ebay-hunter.plist — macOS launchd job

Runs `hunt.py --report` every 2 hours as a background launchd agent.
Survives terminal closes and respects sleep/wake cycles. Output and errors
are logged to `cache/launchd.log` and `cache/launchd-error.log`.

### Install

```bash
# 1. Copy to the user LaunchAgents directory
cp contrib/com.ebay-hunter.plist ~/Library/LaunchAgents/

# 2. Load it (starts immediately on next trigger; does not run at load)
launchctl load ~/Library/LaunchAgents/com.ebay-hunter.plist
```

### Verify it loaded

```bash
launchctl list | grep ebay-hunter
```

A row with PID `-` and exit code `0` means it's loaded and waiting for its
next scheduled trigger.

### Run it once manually (without waiting for the timer)

```bash
launchctl start com.ebay-hunter
```

### Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.ebay-hunter.plist
rm ~/Library/LaunchAgents/com.ebay-hunter.plist
```

### Adjust the interval

Edit the `StartInterval` value in the plist (seconds). Reload after any change:

```bash
launchctl unload ~/Library/LaunchAgents/com.ebay-hunter.plist
launchctl load ~/Library/LaunchAgents/com.ebay-hunter.plist
```

### Review output in Claude.ai

After the job runs, paste the contents of `cache/report.md` into your
Claude.ai session for analysis. The report is plain markdown — no terminal
colour codes.
