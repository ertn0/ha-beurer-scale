# Beurer BF500 Scale for Home Assistant

Custom integration that reads the **Beurer BF 500** bathroom scale over
Bluetooth: weight, BMI, body fat, body water, muscle, basal metabolic rate and
impedance, per user slot of the scale. It also imports your history from the
Beurer HealthManager Pro app.

> Not affiliated with or endorsed by Beurer. Tested with one BF 500 and Home
> Assistant OS 2026.8 on a Raspberry Pi with its built-in Bluetooth adapter.

## Important: press SET on every sync

With a Linux (BlueZ) Bluetooth adapter the scale does not keep its pairing
with Home Assistant. Every time Home Assistant reads it, the scale shows
**`PAIr` and a 6-digit number. Press SET on the scale once** to confirm.
Without it, no data is transferred.

In practice: weigh yourself, step off, wait a few seconds for the number,
press SET. See [Limitations](#limitations) for the background.

## Features

- Auto-discovery of the scale (`BF500`).
- One config entry per user slot (1–4), each with its own sensors:
  Weight, BMI, Body fat, Body water, Muscle, Basal metabolic rate, Impedance
  (disabled by default) and Last measurement.
- Reads only when the scale reports a new measurement for that user, so
  weighings of other users do not trigger anything.
- Keeps the last body analysis when you weigh with shoes on.
- Button **Fetch measurements** to read on demand.
- Action **`beurer_scale.import_history`** to import a HealthManager Pro CSV
  export as long-term statistics.
- English and German translations.

## Requirements

- Home Assistant 2026.8 or newer.
- A **local** Bluetooth adapter handled by BlueZ (e.g. Raspberry Pi built-in or
  a USB dongle). ESPHome Bluetooth proxies are not supported (see below).
- **Active scanning** on that adapter: *Settings → Devices & services →
  Bluetooth → your adapter → Configure → turn off "Passive scanning"*. The
  scale announces new measurements only in its scan response.
- The scale within range of the adapter (about −80 dBm or better worked).
- The **PIN of each user slot**. You set it when adding the scale in the
  Beurer HealthManager Pro app.

## Installation

### HACS

1. HACS → three-dot menu → *Custom repositories* → add
   `https://github.com/ertn0/ha-beurer-scale`, type *Integration*.
2. Install **Beurer BF500 Scale** and restart Home Assistant.

### Manual

Copy `custom_components/beurer_scale` into your `config/custom_components`
folder and restart Home Assistant.

## Setup

1. Wake the scale (step on it). Home Assistant should show it as discovered;
   otherwise *Add integration → Beurer BF500 Scale*.
2. Enter the **user slot** (1–4) and its **PIN**.
3. Weigh yourself as that user, then press SET when the number appears.

For more users, use *Add integration* again with another slot and PIN.

### Finding the PIN

The PIN is chosen per user in
the Beurer HealthManager Pro app. If you do not know it, remove the scale in
the app and add it again; the app then asks for it. **Warning:** removing the
scale in the app deletes that user slot on the scale, including measurements
not yet transferred. Export your data from the app first.

If the PIN changes, Home Assistant asks for the new one (*Re-authenticate*),
or use *Reconfigure* on the entry.

## The Beurer app

The app on your phone keeps working. Whoever connects first gets the new
measurements: if the app syncs a measurement before Home Assistant does, Home
Assistant will not see it. Turning off Bluetooth on the phone, or closing the
app, avoids that.

## Importing history

1. In the HealthManager Pro app, export your data as CSV.
2. Copy the file into your Home Assistant config folder, e.g.
   `config/beurer_export.csv`.
3. *Developer tools → Actions*:

   ```yaml
   action: beurer_scale.import_history
   data:
     file: beurer_export.csv
     user: 2
   ```

Weight, BMI, body fat, body water and muscle are imported as hourly long-term
statistics of the user's sensors. Only hours before the sensors were created
are imported, so nothing recorded by Home Assistant is overwritten. The
sensors need at least one measurement in Home Assistant first. Delete the CSV
afterwards; it contains health data.

Imported values show in the history view for longer periods and in
*Statistics graph* cards.

## Limitations

- **SET on every sync.** The scale asks the connecting device for its
  identity key (IRK) while pairing. BlueZ only sends one with LE privacy
  enabled, and the scale seems to forget bonds without it. The integration
  therefore removes the stale bond before every read, pairs again and confirms
  the number on the Home Assistant side. An ESP32-based client that sends an
  IRK might avoid the button press; not tested yet.
- **BlueZ pairing agent.** To confirm the number, the integration registers
  its own BlueZ pairing agent and requests to be the default agent. It only
  accepts requests from configured scales and rejects all others. If another
  integration or tool on the same host relies on its own default agent, they
  can interfere.
- **No ESPHome proxies.** Pairing and the agent use the local BlueZ adapter via
  D-Bus.
- Tested only with the BF 500. Other Beurer or Sanitas scales may use the same
  services, but the device filter only matches `BF500`.

## How it works

See [docs/PROTOCOL.md](docs/PROTOCOL.md) for the Bluetooth protocol.

## Troubleshooting

Enable debug logging on the integration (*Settings → Devices & services →
Beurer BF500 Scale → ⋮ → Enable debug logging*), weigh yourself and look at
the log. A sync logs each step: removing the stale bond, pairing (with the
number), connected, clock set, consent sent, records received.

`sync failed (was SET pressed when the number showed?)` usually means the
number was not confirmed in time.

## Privacy

All data stays local. Debug logs contain raw measurement packets; do not post
them publicly without removing them.

## License

MIT
