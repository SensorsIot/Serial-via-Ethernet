# Container Configuration

## devcontainer.json

Copy `devcontainer.json` to your project's `.devcontainer/` folder or merge with existing config.

## Key Settings

| Setting | Purpose |
|---------|---------|
| `--privileged` | Full device access |
| `c 166:* rwm` | Access ttyACM devices |
| `c 188:* rwm` | Access ttyUSB devices |
| `/dev:/dev:rslave` | See host devices, propagate mount events |

## Usage

Devices appear automatically. No USB/IP commands needed.

```bash
# List devices
ls /dev/ttyUSB* /dev/ttyACM*

# PlatformIO upload
pio run -t upload

# Serial monitor
pio device monitor
```
