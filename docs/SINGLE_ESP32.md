# SenseThrough on a single ESP32

**Fall detection over Wi-Fi CSI using one board.** This is the primary hardware path: one
ESP32, one USB cable, and a transmitter you already own. The two-board rig is still
supported and documented in [`SENSETHROUGH.md`](SENSETHROUGH.md), but it is no longer
required — and most of what used to break in that setup does not exist here.

> **The idea in one paragraph.** CSI is measured on frames a radio *receives*. So the
> sensor needs a transmitter, but it does not need to be *ours*: your router already fills
> the room with frames. One ESP32 listens to that link, we generate traffic at a rate we
> choose so the sampling is even, and a person moving through the path between router and
> board perturbs the channel measurably. One board, one sensor.

---

## 1. Why one board is easier than two

Everything in this column was a real failure mode of the two-board rig:

| Two boards | One board |
| --- | --- |
| Two USB devices to attach and keep attached | One |
| Opening either serial port resets that board; resets at different times desync the link and collapse the rate to ~1 Hz | The transmitter is a router. It does not care that you opened a serial port |
| "Stuck calibrating, packets=0" when the two boards fail to re-form their link | Nothing to re-form; the AP is already up |
| Packet rate is whatever the link gives (~12 Hz measured) | You set it: `--traffic-hz`, measured 66 Hz on this rig |
| HT-LTF/LLTF frames interleave, so packet width varies and the room mask crashes | LLTF-only firmware: constant 62 subcarriers |

What one board does *not* fix: placement sensitivity, the one-occupant assumption, and
"fell" vs "walked out of the room". Those are in §9.

---

## 2. What you need

- **1 × ESP32** (WROOM-32 / ESP-32S) and a **data** USB cable.
- **A transmitter**: your router, a phone hotspot, or the laptop itself. See §3.
- **A laptop** to run the detector — the same one the board is plugged into.
- **ESP-IDF v4.3 or newer** to build the firmware once.

## 3. Pick a link mode

Set this in `idf.py menuconfig` → *SenseThrough single-ESP32 CSI*.

| Mode | Transmitter | Rate | Trade-off |
| --- | --- | --- | --- |
| **`STA`** (default) | your router / hotspot | you choose | Needs Wi-Fi credentials. **Recommended**: board and laptop share a network, so the laptop can drive the rate *and* keep working normally. |
| **`SOFTAP`** | your laptop | you choose | No credentials, no router. But the laptop joins the board's network, so it has no internet while monitoring. |
| **`SNIFFER`** | any AP in range | ~10 Hz (beacons) | Nothing to configure at all, but the rate is not yours to control and is usually too low and too uneven for reliable detection. Use it to prove CSI works, not to run the gate. |

### Why traffic generation matters

In `STA` and `SOFTAP` the firmware binds a UDP port and **discards everything it receives**.
The payload is irrelevant: each datagram arrives as a Wi-Fi frame, and each received frame
is one CSI sample. [`scripts/traffic.py`](../scripts/traffic.py) sends them at a fixed rate,
which is what turns "however many packets the network happened to send" into a sampling
clock. `server/app.py` starts it automatically once it sees the board's IP.

The firmware also pings its own gateway (`WISP_SELF_PING`), so it produces ~33 Hz on its
own even with no generator running. That is the floor, not the plan — routers rate-limit
ICMP unpredictably.

---

## 4. Build and flash

```bash
. $HOME/esp/esp-idf-v4.3/export.sh

cd firmware/single_esp32_csi
idf.py set-target esp32
idf.py menuconfig            # SenseThrough single-ESP32 CSI -> mode, SSID, password
idf.py -p /dev/ttyUSB0 -b 115200 flash monitor
```

Flash at `-b 115200`; faster flashing baud rates time out over USB/IP. That is unrelated to
the **console** baud (921600), which is set in `sdkconfig.defaults`.

Three configuration traps, all of which cost time here:

1. **`CONFIG_ESP32_WIFI_CSI_ENABLED=y`** — without it, `esp_wifi_set_csi()` fails and the
   board reboot-loops. Already in `sdkconfig.defaults`; never remove it.
2. **Console baud needs `CONFIG_ESP_CONSOLE_UART_CUSTOM=y`.** The baud symbol only has a
   prompt when CUSTOM is selected, and kconfiglib *silently discards* values for
   prompt-less symbols. Set the baud alone and it stays 115200 while your config file
   claims 921600 — which then looks exactly like line corruption when you read at the rate
   you thought you set.
3. **Baud is the real rate cap.** One CSI line is ~500 bytes. At 115200 the board produced
   24 Hz and **dropped 59 of 257 packets**; at 921600 the same setup dropped zero. Drops
   are worse than a low rate, because they make the sampling *uneven*.

---

## 5. Bring-up, with a go/no-go at each step

Do these in order. Each one either passes or tells you exactly what is wrong — this is the
sequence that stops you discovering a problem during a demo.

### Step 1 — the board is talking

```bash
python scripts/serial_check.py --port /dev/ttyUSB0 --baud 921600
```

A healthy result:

```
subcarriers: {62: 302}  (STABLE)
measured rate: 33.2 Hz
board-reported rate: 31.4 Hz   dropped: 0
VERDICT: CSI IS FLOWING and the parser understands it.
```

The script distinguishes the failure modes that look identical from outside — wrong baud,
no link, linked but no traffic — and tells you which one you have. If CSI is flowing but
`link=down`, read the `reason=` on the board's `CSI_LINK` line: the firmware prints a
plain-English cause (wrong password, SSID not found, AP refused).

### Step 2 — the rate is what you asked for

```bash
python scripts/traffic.py --host <board-ip> --hz 50      # IP from the board's CSI_INFO line
```

Leave it running. Re-run `serial_check`: the measured rate should climb and `dropped` should
stay at 0. If `dropped` grows, the UART cannot carry that rate — lower `--hz` or raise the
console baud.

### Step 3 — the placement can support detection  ← **the decisive step**

```bash
python scripts/run_live.py --serial /dev/ttyUSB0 --baud 921600 --traffic-host <board-ip>
```

Move around during the calibration window, then read the line that matters:

```
still->occupied separation: 9.2x  [EXCELLENT]
```

| Separation | Meaning |
| --- | --- |
| **≥ 5×** | excellent — detection will be comfortable |
| **2–5×** | usable |
| **< 2×** | **unusable.** Move the hardware; no amount of tuning helps |

This is not advisory. A real run here measured **1.6×** and produced a confident "slow
collapse" alert from an empty, quiet room within a minute — because when the still and
active levels overlap, ordinary quiet *is* what a collapse looks like. Fix the geometry
before you believe a single alert.

### Step 4 — a staged fall is caught

Move clearly for 3–4 s → drop → lie still for ~10 s. Expect
`DISTURBANCE → STILL → CONFIRMED`, then the escalation countdown.

### Step 5 — the dashboard

```bash
python server/app.py --serial /dev/ttyUSB0 --baud 921600 --room "Bedroom" --escalate-s 30
```

Open `http://localhost:8000`. The traffic generator starts itself from the board's
announced IP; add `--no-traffic` if you are running `scripts/traffic.py` separately.

---

## 6. Placement — this decides everything

```
        2-3 m apart, person crosses the line between them
   [ROUTER / hotspot] · · · · · person walks HERE · · · · · [ESP32 + USB]
     wherever it lives                                  ~1 m high, antenna clear
```

- **The person must cross the path between the transmitter and the board.** Movement off
  to the side barely registers. This is the whole game.
- With one board you cannot move the router, so **move the ESP32** until the doorway, bed,
  or chair you care about sits on the line between them.
- Waist-to-chest height, antenna clear of metal and of the laptop lid.
- Away from fans and anything else that moves constantly.
- **Never move the board while monitoring.** Moving it changes the channel more than a
  person does, and setting it down looks exactly like "activity → stillness", i.e. a fall.
  If you reposition, recalibrate.

A common mistake with one board: leaving the ESP32 and the phone-hotspot next to each other
on the desk. There is no path between them for a body to cross, and separation comes out
near 1×.

---

## 7. What the numbers mean

| Number | Where | Healthy | Meaning |
| --- | --- | --- | --- |
| `separation` | calibration, dashboard | ≥ 2× | can this placement tell moving from still |
| `measured rate` | `serial_check`, dashboard | 20–100 Hz | what the windows are actually sized from |
| `dropped` | board's `CSI_STAT` | 0 | CSI the board could not print in time (UART too slow) |
| `gaps` | dashboard `link` | 0 | dropouts in the stream; each one resets detection |
| `rssi` | board's `CSI_STAT` | > −70 | link margin to the transmitter |

Rate is **measured, not configured**. A `--rate` flag is a guess, and with one board the
real rate is whatever the transmitter and the UART settle on. Everything downstream —
window length, stillness timing, latency — is sized from the measurement.

---

## 8. Troubleshooting

**`/dev/ttyUSB0` disappears every few minutes (WSL).** The usual explanation is "usbipd is
flaky". It usually is not: **WSL shuts itself down when no process is running inside it,
and that drops the USB attachment.** Keep something alive:

```powershell
Start-Process wsl -ArgumentList '-d','Ubuntu','--','sleep','infinity' -WindowStyle Hidden
usbipd attach --wsl --busid <busid>
```

Verify with `usbipd list` (should say `Attached`) and `ls /dev/ttyUSB*`.

**No COM port on Windows, device shows an error.** Problem code 28 means no driver: install
the Silicon Labs CP210x VCP driver. If the device is bound to usbipd it will not appear on
Windows at all while attached to WSL — `usbipd detach --busid <busid>` to give it back.

**Board associates but never gets an IP (`ip=0.0.0.0`).** If you have modified the firmware,
check the order in `wifi_common_init`: `esp_netif_create_default_wifi_sta()` must come after
`esp_netif_init()` and the default event loop, because that is when the DHCP client's
handlers are attached. Wrong order associates fine, reports a good RSSI, and never gets an
address — with no error printed anywhere.

**`reason=202 AUTH REFUSED` / association refused temporarily.** Modern routers and phone
hotspots require Protected Management Frames. The firmware declares `pmf_cfg.capable`, which
handles it; an older build without that flag fails here in a way that looks like a wrong
password.

**Garbled serial lines.** Baud mismatch, nearly always. Check
`CONFIG_ESP_CONSOLE_UART_BAUDRATE` in the built `sdkconfig` (not just in
`sdkconfig.defaults` — see §4 trap 2) and pass the same `--baud`.

**`dropped` climbing in `CSI_STAT`.** The UART cannot carry the packet rate. Lower
`--traffic-hz` or `CONFIG_WISP_PING_INTERVAL_MS`, or raise the console baud.

**False alarms in an empty room.** Check `separation` first (§5 step 3) — below 2× this is
expected and not fixable by tuning. Above 2×, raise `--min-active-s` (require more genuine
activity before a collapse can confirm) and `--smooth`.

**Alerts never fire / the meter never reads "still".** The still line sits below the room's
resting noise floor. Recalibrate while the room is genuinely quiet, or pin the line with
`--still <value>` just above the resting peak.

**A dropout produced an alert.** It should not: `--gap-reset-s` (default 3 s) discards the
pattern in progress after a CSI gap, because stillness that was accumulating when the link
died would otherwise be credited with the whole dead period. If you set it to 0, you get
that bug back.

---

## 9. Honest limits

- **One occupant.** The sensor measures the *sum* of motion in the channel. With several
  people moving, the room never goes quiet and a collapse cannot confirm.
- **"Fell" vs "walked away."** Both are activity → stillness. The sustained-activity gate,
  the sharp-impact requirement, and the "I'm OK" button reduce this; nothing removes it.
- **Placement-bound.** A poor geometry gives a signal no algorithm can rescue, and the
  router's position is not yours to choose.
- **The router is not under your control.** Band steering, channel hopping, or a reboot
  changes the channel mid-run. Fix the AP to one 2.4 GHz channel if you can.
- **The gate is unproven.** Everything above gets you a working sensor. Whether it produces
  **< ~1 false alarm per week** over weeks in a real occupied room is the measurement the
  [evaluation harness](../wisp/evaluate/harness.py) exists to make, and it has not been run
  yet. That number, not a working demo, is what decides whether this is trustworthy.

---

## 10. Recording, and the gate

```bash
python scripts/record.py --port /dev/ttyUSB0 --seconds 600 \
    --out data/normal_evening.csv --traffic-host <board-ip>

python scripts/calibrate.py --replay data/normal_evening.csv
python scripts/evaluate.py  --replay data/fall_01.csv
```

Record early and often: an hour of your real room is worth more than any amount of tuning,
it is the input the harness replays, and it is the demo that still works when the hardware
does not.
