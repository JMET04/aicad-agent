# Secure Command Protocol

Status: EVT review-only; specification intent, not a deployed or audited protocol.

## Pairing and key hierarchy

- Radio bearer: BLE 1M PHY.
- BLE security: LE Secure Connections, SC-only. Pairing starts only during a physical provisioning action and uses an authenticated out-of-band channel. `Just Works`, a fixed passkey, default debug credential or fleet-wide secret is prohibited.
- Every wand/receiver receives a unique 128-bit-or-stronger provisioning secret and unique non-zero device ID. Manufacturing must detect duplicates and protect/key-erase failed units.
- Derive direction-specific application traffic keys from the device secret, both device identities, protocol version and a fresh authenticated session identifier using an SDK-reviewed KDF. Do not use the long-term OOB value directly as the AES-CCM traffic key.
- AES-128-CCM uses a 16-byte authentication tag. The platform binds to a reviewed SDK/hardware implementation; there is no custom cipher code in this skeleton.

BLE encryption and application encryption are deliberately layered: BLE protects the link; the application frame binds command semantics, device/session/direction, freshness and replay state end-to-end.

## Canonical frame

All integers are unsigned big-endian. C structure layout/padding is never transmitted directly.

| Field | Bytes | Authenticated | Meaning |
|---|---:|---|---|
| version | 1 | AAD | Must equal 1. |
| direction | 1 | AAD + nonce | 1 wand→receiver; 2 receiver→wand. |
| command | 1 | AAD | Allow-listed command ID. |
| flags | 1 | AAD | Must be zero until defined by a reviewed protocol revision. |
| device_id | 4 | AAD + nonce | Provisioned sender identity; collision prohibited. |
| session_id | 4 | AAD + nonce | Fresh authenticated session identifier; never reused with a traffic key. |
| sequence | 4 | AAD + nonce | Starts at 1 and strictly increases per direction/session. |
| issued_ms | 4 | AAD | Sender monotonic session time; receiver accepts age ≤150 ms. |
| payload_length | 2 | AAD | 0–32 bytes; exact length authenticated. |
| ciphertext | variable | encrypted/authenticated | Command argument. |
| tag | 16 | — | AES-CCM authentication tag. |

AAD is the exact 22-byte header. The 13-byte CCM nonce is:

`direction[1] || device_id[4] || session_id[4] || sequence[4]`

Nonce reuse under the same traffic key is catastrophic. Sequence exhaustion, persistent-state uncertainty, session collision or interrupted counter commit forces disarm and authenticated reprovisioning/rekey; no wraparound is allowed.

## Receive transaction order

1. Force outputs safe until boot, credentials and replay storage are healthy.
2. Check version, direction, allow-listed command, device, session, length, non-zero sequence, strict `sequence > receive_high_water` and freshness.
3. Build canonical nonce/AAD and verify/decrypt AES-CCM in constant-time library code.
4. Atomically persist the new receive high-water mark. If commit fails, erase plaintext and reject.
5. Only then deliver plaintext to the state machine. A protocol rejection never changes an output.

Flash endurance requires a reviewed journal/monotonic storage design, not writing one flash word per radio packet. Options include authenticated session epochs backed by atomic wear-levelled storage plus a RAM sequence window. The selected construction needs an independent security review and power-cut campaign.

## Command allow-list

| ID | Command | Receiver behavior |
|---:|---|---|
| 1 | DISARM | Immediately clear every output and physical-arm lease; sender transmits three prompt copies with unique sequences. |
| 2 | HEARTBEAT | Refresh link liveness only; does not refresh physical-arm authorization. |
| 3 | ARM_LEASE | Valid only from the paired wand while its dedicated switch is continuously held; renews receiver lease for 100 ms. Wand sends at ≤25 ms interval. |
| 16 | SET_AUX | Set a documented non-flight-critical low-voltage AUX signal while lease remains valid. Never map to flight arming/propulsion/primary control. |
| 17 | PULSE_ISOLATED_OC | Pulse floating open collector for 1–500 ms, still gated by the 100 ms renewable arm lease. |
| 18 | PULSE_LOW_SIDE | Pulse common-ground 5–12 V low-side output for 1–500 ms, still gated by the arm lease and hardware limits. |
| 32 | FEEDBACK | Receiver→wand state/result indication; never causes a receiver output. |
| 33 | GESTURE_EVENT | Wand-to-receiver two-byte payload: validated gesture ID then confidence percent (70-100). It is telemetry only at the protocol layer and never directly changes an output. |

GESTURE_EVENT is accepted only with an exact two-byte authenticated payload; the receiver application must decode it with `mw_gesture_decode_event()` before any reviewed policy mapping. Unknown commands/flags, zero-length-required violations, range errors or mixed directions are rejected. There is intentionally no mains command, emergency-stop command, flight arm, propulsion, motor or primary flight-control command.

## Required negative tests

Duplicate/stale sequence, sequence 0/max/wrap, old/future timestamp, wrong device/session/direction, changed header, changed ciphertext/tag, truncated/oversized length, unknown command/flags, nonce collision, reboot/counter rollback, interrupted persistence, cross-pair packet and absent CCM callback must all reject with outputs unchanged and safe.
