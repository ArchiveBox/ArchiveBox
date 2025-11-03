# Chrome Remote Debugging Setup Guide

This guide explains how to set up Chrome with remote debugging for use with ArchiveBox-TS extractors.

## Why Chrome DevTools Protocol (CDP)?

The `screenshot`, `title`, and `headers` extractors use Puppeteer to control a Chrome browser. By connecting to Chrome via the Chrome DevTools Protocol (CDP), all extractors can:

- **Share a single browser instance** - More efficient than launching Chrome for each URL
- **Use a remote Chrome** - Run Chrome in a container or separate machine
- **Better for production** - Cleaner separation of concerns
- **Faster execution** - No browser startup overhead for each extraction

## Quick Start

### 1. Start Chrome with Remote Debugging

```bash
# Linux
chromium --remote-debugging-port=9222 --headless --disable-gpu --no-sandbox

# Mac
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --headless --disable-gpu

# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 --headless --disable-gpu
```

Keep this terminal open - Chrome will run in the foreground.

### 2. Get the WebSocket URL

In a new terminal:

```bash
curl http://localhost:9222/json/version
```

Look for the `webSocketDebuggerUrl` field:

```json
{
  "Browser": "Chrome/120.0.6099.109",
  "Protocol-Version": "1.3",
  "User-Agent": "Mozilla/5.0 ...",
  "V8-Version": "12.0.267.8",
  "WebKit-Version": "537.36",
  "webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### 3. Set the Environment Variable

```bash
# Extract and set the URL
export CHROME_CDP_URL=$(curl -s http://localhost:9222/json/version | jq -r .webSocketDebuggerUrl)

# Verify it's set
echo $CHROME_CDP_URL
# Should output: ws://localhost:9222/devtools/browser/...
```

### 4. Run ArchiveBox-TS

Now you can use the Chrome-based extractors:

```bash
node dist/cli.js add https://example.com --extractors title,headers,screenshot
```

## Troubleshooting

### "CHROME_CDP_URL environment variable not set"

You need to set the `CHROME_CDP_URL` before running extractors:

```bash
export CHROME_CDP_URL="ws://localhost:9222/devtools/browser/..."
```

### "Connection refused" or "ECONNREFUSED"

Chrome is not running or not accessible. Check:

1. Chrome is running: `ps aux | grep chrome`
2. Port 9222 is open: `curl http://localhost:9222/json/version`
3. Firewall not blocking port 9222

### "Protocol error" or "Target closed"

The browser may have crashed or been closed. Restart Chrome with remote debugging.

### Chrome won't start in headless mode

Some systems have issues with headless Chrome. Try:

```bash
# Add more flags
chromium \
  --remote-debugging-port=9222 \
  --headless \
  --disable-gpu \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-setuid-sandbox
```

### "jq: command not found"

Install jq to parse JSON:

```bash
# Ubuntu/Debian
sudo apt-get install jq

# Mac
brew install jq

# Or manually copy the WebSocket URL
curl http://localhost:9222/json/version
# Copy the webSocketDebuggerUrl value manually
```

## Production Setup

### Docker Compose

Create a `docker-compose.yml`:

```yaml
version: '3'
services:
  chrome:
    image: browserless/chrome:latest
    ports:
      - "9222:9222"
    environment:
      - DEFAULT_HEADLESS=true
      - MAX_CONCURRENT_SESSIONS=5
    restart: unless-stopped

  archivebox-ts:
    build: .
    depends_on:
      - chrome
    environment:
      - CHROME_CDP_URL=ws://chrome:9222/devtools/browser
    volumes:
      - ./data:/app/data
```

Start with:

```bash
docker-compose up -d
```

### Kubernetes

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: archivebox-ts
spec:
  containers:
  - name: chrome
    image: browserless/chrome:latest
    ports:
    - containerPort: 9222
    env:
    - name: DEFAULT_HEADLESS
      value: "true"
    resources:
      requests:
        memory: "512Mi"
        cpu: "500m"
      limits:
        memory: "2Gi"
        cpu: "2000m"

  - name: archivebox-ts
    image: archivebox-ts:latest
    env:
    - name: CHROME_CDP_URL
      value: "ws://localhost:9222/devtools/browser"
    volumeMounts:
    - name: data
      mountPath: /app/data

  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: archivebox-data
```

### systemd Service

Create `/etc/systemd/system/chrome-remote-debugging.service`:

```ini
[Unit]
Description=Chrome Remote Debugging
After=network.target

[Service]
Type=simple
User=archivebox
ExecStart=/usr/bin/chromium \
  --remote-debugging-port=9222 \
  --headless \
  --disable-gpu \
  --no-sandbox \
  --disable-dev-shm-usage
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable chrome-remote-debugging
sudo systemctl start chrome-remote-debugging
```

Add to your archivebox-ts service file:

```ini
Environment="CHROME_CDP_URL=ws://localhost:9222/devtools/browser"
```

## Advanced Configuration

### Multiple Chrome Instances

Run Chrome on different ports for load balancing:

```bash
# Chrome instance 1
chromium --remote-debugging-port=9222 --headless --no-sandbox &

# Chrome instance 2
chromium --remote-debugging-port=9223 --headless --no-sandbox &

# Use different instances
export CHROME_CDP_URL="ws://localhost:9222/devtools/browser/..."
node dist/cli.js add https://example1.com

export CHROME_CDP_URL="ws://localhost:9223/devtools/browser/..."
node dist/cli.js add https://example2.com
```

### Remote Chrome

Run Chrome on a separate machine:

```bash
# On the Chrome machine (192.168.1.100)
chromium \
  --remote-debugging-port=9222 \
  --remote-debugging-address=0.0.0.0 \
  --headless \
  --no-sandbox

# On the ArchiveBox-TS machine
export CHROME_CDP_URL="ws://192.168.1.100:9222/devtools/browser/..."
node dist/cli.js add https://example.com
```

**Security Warning**: Only expose Chrome remote debugging on trusted networks!

### Custom User Data Directory

Persist browser state (cookies, cache, etc.):

```bash
mkdir -p ~/.chrome-profile

chromium \
  --remote-debugging-port=9222 \
  --headless \
  --user-data-dir=~/.chrome-profile \
  --no-sandbox
```

### Resource Limits

Limit Chrome's resource usage:

```bash
# Limit memory to 2GB
ulimit -v 2097152

# Run Chrome
chromium --remote-debugging-port=9222 --headless --no-sandbox
```

Or use cgroups:

```bash
# Create a cgroup
sudo cgcreate -g memory:chrome

# Set memory limit (2GB)
echo 2147483648 | sudo tee /sys/fs/cgroup/memory/chrome/memory.limit_in_bytes

# Run Chrome in the cgroup
sudo cgexec -g memory:chrome chromium \
  --remote-debugging-port=9222 \
  --headless \
  --no-sandbox
```

## Monitoring

### Check Chrome Status

```bash
# Get Chrome info
curl http://localhost:9222/json/version | jq

# List open tabs/pages
curl http://localhost:9222/json/list | jq

# Check if Chrome is responsive
curl -s http://localhost:9222/json/version > /dev/null && echo "Chrome is running" || echo "Chrome is down"
```

### Health Check Script

Create `check-chrome.sh`:

```bash
#!/bin/bash

if curl -s http://localhost:9222/json/version > /dev/null; then
  echo "✓ Chrome is running"
  exit 0
else
  echo "✗ Chrome is not responding"
  exit 1
fi
```

### Logging

Redirect Chrome logs:

```bash
chromium \
  --remote-debugging-port=9222 \
  --headless \
  --no-sandbox \
  > /var/log/chrome-stdout.log \
  2> /var/log/chrome-stderr.log
```

## Performance Tips

1. **Reuse browser instance**: Don't restart Chrome between archives
2. **Limit concurrent pages**: Chrome can handle ~5-10 pages concurrently
3. **Set resource limits**: Prevent Chrome from using too much memory
4. **Close unused tabs**: Puppeteer pages close automatically, but check with `/json/list`
5. **Use headless mode**: Faster and uses less memory than headed mode
6. **Disable unnecessary features**: Use `--disable-gpu`, `--disable-dev-shm-usage`, etc.

## Security Considerations

1. **Never expose port 9222 to the internet** - Anyone can control Chrome
2. **Use firewall rules** to restrict access to localhost or trusted IPs
3. **Run Chrome as unprivileged user** - Use `--no-sandbox` with caution
4. **Keep Chrome updated** - Security patches are important
5. **Use network isolation** - Run Chrome in a separate network namespace or container

## Example: Complete Setup Script

```bash
#!/bin/bash
set -e

# Install dependencies
sudo apt-get update
sudo apt-get install -y chromium-browser jq curl

# Start Chrome
chromium \
  --remote-debugging-port=9222 \
  --headless \
  --disable-gpu \
  --no-sandbox \
  --disable-dev-shm-usage &

CHROME_PID=$!
echo "Chrome started with PID: $CHROME_PID"

# Wait for Chrome to be ready
echo "Waiting for Chrome to start..."
for i in {1..30}; do
  if curl -s http://localhost:9222/json/version > /dev/null; then
    echo "✓ Chrome is ready"
    break
  fi
  sleep 1
done

# Get and set CDP URL
export CHROME_CDP_URL=$(curl -s http://localhost:9222/json/version | jq -r .webSocketDebuggerUrl)
echo "CHROME_CDP_URL=$CHROME_CDP_URL"

# Run archivebox-ts
cd archivebox-ts
node dist/cli.js add "https://example.com" --extractors title,headers,screenshot

# Cleanup
kill $CHROME_PID
echo "✓ Done"
```

Make it executable:

```bash
chmod +x setup-and-run.sh
./setup-and-run.sh
```

## References

- [Chrome DevTools Protocol Documentation](https://chromedevtools.github.io/devtools-protocol/)
- [Puppeteer Documentation](https://pptr.dev/)
- [Chrome Headless Documentation](https://developer.chrome.com/blog/headless-chrome/)
- [Browserless.io](https://www.browserless.io/) - Managed Chrome service
