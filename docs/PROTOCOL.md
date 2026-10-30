# Beurer BF500 Bluetooth protocol

Reverse-engineered from iOS PacketLogger traces of the Beurer HealthManager Pro
app and from tests with BlueZ. Example values below are made up.

## Advertisement

| Field | Value |
|---|---|
| Local name | `BF500` |
| Service UUID | `0x181D` (Weight Scale) |
| Manufacturer data | company `0x0611`, payload `02 00` |
| Service data `0x181D` | list of user slots with **unsent measurements**, e.g. `01 03 04` |

The service data is only in the scan response, so the scanner has to scan
actively. A slot number disappears from the list once its measurements were
transferred (to the app or to Home Assistant).

## GATT services

| Service | Characteristics used |
|---|---|
| `0x1805` Current Time | `0x2A2B` Current Time (write) |
| `0x181D` Weight Scale | `0x2A9D` Weight Measurement (indicate) |
| `0x181B` Body Composition | `0x2A9C` Body Composition Measurement (indicate) |
| `0x181C` User Data | `0x2A9F` User Control Point (write, indicate), plus date of birth, gender, height |
| `0xFFF0` vendor | `0xFFF1` (write/notify: list of user profiles), `0xFFF5` (indicate, unknown content), others |
| `0x180A`, `0x180F` | device information, battery |

## Pairing

The scale sends an SMP Security Request right after connecting and asks for
LE Secure Connections with bonding and MITM protection. It declares the IO
capability *DisplayYesNo*, so pairing uses **numeric comparison**: the scale
shows `PAIr` and then a 6-digit number, and the user confirms with the **SET**
button on the scale. Without SET the pairing never completes.

The scale requests the initiator's identity key (IRK) during key
distribution. The iPhone sends it and the scale keeps that bond: the app
reconnects without any button press. BlueZ only distributes an IRK when LE
privacy is enabled on the adapter; with privacy off, the scale forgets the
bond after every connection and asks for a new pairing each time. (That the
missing IRK is the reason is a hypothesis; it matches all observations.)

## Reading measurements

1. Write the current local time to `0x2A2B`:
   `year (uint16 LE), month, day, hours, minutes, seconds, day of week (0), fractions (0), adjust reason (0)`.
2. Enable indications on `0x2A9D`, `0x2A9C`, `0x2A9F` and `0xFFF5`.
3. Write the UCP *Consent* request to `0x2A9F`:
   `02 <user index> <consent code, uint16 LE>`. The consent code is the
   4-digit PIN set for that user in the app, e.g. PIN 1234 for user 3 is
   `02 03 d2 04`.
4. The scale indicates every stored measurement of that user: a Weight
   Measurement, followed by its Body Composition Measurement and a `0xFFF5`
   packet. Then it sends the UCP response `20 02 01`
   (response code, request op code *Consent*, result *Success*).
   A wrong PIN gives a result other than `01`.
5. Disable the indications and disconnect.

Registering a new user (op code `01`) is done by the app; the scale answers
`20 01 01 <new user index>`. Removing the scale in the app deletes the user
slot on the scale, including measurements not yet transferred.

## Weight Measurement (`0x2A9D`)

Standard layout. The BF500 sends flags `0x0e` (SI units, time stamp, user ID,
BMI and height):

| Bytes | Field | Unit |
|---|---|---|
| 1 | flags | |
| 2 | weight | 0.005 kg |
| 7 | time stamp | year (uint16), month, day, h, m, s |
| 1 | user index | |
| 2 | BMI | 0.1 |
| 2 | height | 0.001 m |

Example: `0e 98 3a e9 07 03 01 07 1e 0f 01 e7 00 08 07` is 75.0 kg on
2025-03-01 07:30:15, user 1, BMI 23.1, 1.800 m.

## Body Composition Measurement (`0x2A9C`)

Standard layout. The BF500 sends flags `0x0398` (SI units; basal metabolism,
muscle percentage, soft lean mass, body water mass, impedance):

| Bytes | Field | Unit |
|---|---|---|
| 2 | flags | |
| 2 | body fat | 0.1 % |
| 2 | basal metabolism | kJ |
| 2 | muscle percentage | 0.1 % |
| 2 | soft lean mass | 0.005 kg |
| 2 | body water mass | 0.005 kg |
| 2 | impedance | 0.1 Ω |

Measurements without a body analysis (shoes on) contain zeros for fat,
muscle, masses and impedance.
