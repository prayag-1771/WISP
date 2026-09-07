# `single_esp32_csi` — firmware for the one-board sensor

Streams Wi-Fi CSI from **a single ESP32** to the serial port in the `CSI_DATA` format
[`wisp/ingest/parser.py`](../../wisp/ingest/parser.py) already parses. This is the whole
hardware half of the single-board system; the detector on the laptop is unchanged.

The full bring-up walkthrough (placement, calibration, troubleshooting, the physics of why
one board works) lives in [`docs/SINGLE_ESP32.md`](../../docs/SINGLE_ESP32.md). This file
is just build-and-flash.

---

## Why one board is enough

CSI is measured on **received** frames, so the sensor needs a transmitter — but it does
not need to be *ours*. Pick a link mode in `menuconfig`:

| Mode | Transmitter | Rate | Needs |
| --- | --- | --- | --- |
| **`STA`** (default) | your **router** | you choose (UDP), ~30 Hz (self-ping) | Wi-Fi credentials |
| **`SOFTAP`** | your **laptop** | you choose (UDP) | nothing but the laptop |
| **`SNIFFER`** | any AP in range | ~10 Hz (beacons) | nothing at all |

In `STA` and `SOFTAP` the board binds a UDP port and throws away everything that arrives —
the payload is irrelevant, the *arrival* is the measurement. [`scripts/traffic.py`](../../scripts/traffic.py)
sends those datagrams at a rate you pick, which is what turns "however many packets the
network happens to send" into a controlled sampling rate. `server/app.py` starts that
generator for you once it sees the board's IP on the serial line.

## Build and flash

Requires ESP-IDF **v4.3+** (v5.x also fine), ESP32 / ESP32-S target.

```bash
. $HOME/esp/esp-idf/export.sh          # or %USERPROFILE%\esp\esp-idf\export.bat on Windows

cd firmware/single_esp32_csi
idf.py set-target esp32
idf.py menuconfig                      # -> "SenseThrough single-ESP32 CSI": mode + SSID
idf.py -p /dev/ttyUSB0 -b 115200 flash monitor
```

- **Flash at `-b 115200`.** Faster flashing baud rates time out over USB/IP; the *running*
  console baud is separate (921600, see below) and set by `sdkconfig.defaults`.
- `Ctrl-]` leaves `idf.py monitor`. Close the monitor before starting the detector —
  two programs cannot hold the same port.

### What to expect on the console

```
CSI_INFO,mode=sta,ssid=myrouter,state=connecting
CSI_LINK,state=connected,bssid=ac:84:c6:11:22:33,channel=6,rssi=-47
CSI_INFO,mode=sta,ip=192.168.1.42,udp_port=8888
CSI_INFO,hint=aim the traffic generator here: python scripts/traffic.py --host 192.168.1.42 --hz 50
CSI_DATA,SINGLE,ac:84:c6:11:22:33,-47,11,1,0,0,1,1,0,0,0,0,-93,0,6,0,1043216,0,42,0,124,[12 -8 5 3 ...]
CSI_STAT,rate_hz=32.8,packets=164,dropped=0,link=up,rssi=-47
```

`CSI_STAT` every 5 s is the field diagnostic: **`rate_hz`** is what the detector actually
gets, and **`dropped`** counts CSI the printing task could not keep up with. A nonzero
`dropped` means the UART is the bottleneck — raise the baud or lower the traffic rate.

## Configuration that actually matters

| Setting | Default | Why |
| --- | --- | --- |
| `CONFIG_ESP32_WIFI_CSI_ENABLED` | `y` | **Without it the board reboot-loops** on `esp_wifi_set_csi`. Set in `sdkconfig.defaults`; never turn it off. |
| `WISP_CSI_LLTF_ONLY` | `y` | Constant subcarrier width and ~1/3 the serial bytes. Turn off only if you want HT-LTF subcarriers and have baud to spare. |
| `CONFIG_ESP_CONSOLE_UART_BAUDRATE` | `921600` | One CSI line is ~420 bytes: 115200 baud caps you near 25 Hz, 921600 has room for 100 Hz. |
| `WISP_UDP_PORT` | `8888` | Where `scripts/traffic.py` aims. |
| `WISP_SELF_PING` / `WISP_PING_INTERVAL_MS` | `y` / `30` | Self-contained traffic so the board streams even with no laptop generator running. |
| `WISP_MAC_FILTER` | auto | CSI from two transmitters averaged together is meaningless. Auto-pinned to the associated peer; **must be set by hand in `SNIFFER` mode**. |

## Line format

```
CSI_DATA,SINGLE,<mac>,<rssi>,<rate>,<sig_mode>,<mcs>,<bandwidth>,<smoothing>,<not_sounding>,
<aggregation>,<stbc>,<fec_coding>,<sgi>,<noise_floor>,<ampdu_cnt>,<channel>,
<secondary_channel>,<local_timestamp_us>,<ant>,<sig_len>,<rx_state>,<len>,[<i> <q> ...]
```

The parser only reads the trailing `[...]` block — interleaved I/Q int8 pairs, one pair per
subcarrier, amplitude `sqrt(i² + q²)`. The metadata columns are for humans and for
`scripts/serial_check.py`.

Two subcarriers are missing by design: the ESP32's first CSI word is documented as
sometimes invalid, so the first four bytes are dropped **unconditionally** — dropping them
only when the invalid flag is set would make the packet width vary, and a varying width
breaks the fixed-width room mask. `len` is always the count actually emitted.

## Verify before you trust it

```bash
python scripts/serial_check.py --port /dev/ttyUSB0 --baud 921600
```

Confirms CSI is flowing, the parser understands the lines, the width is stable, and prints
the measured rate. Run this before the detector, every time the setup changes.
