# Secure Command Protocol

Status: EVT review-only; specification intent, not a deployed or audited protocol.

## Pairing and key hierarchy

- Radio bearer: BLE 1M PHY.
- BLE security: LE Secure Connections, SC-only. Pairing starts only during a physical provisioning action and uses an authenticated out-of-band channel. `Just Works`, a fixed passkey, default debug credential or fleet-wide secret is prohibited.
- Every wand/receiver receives a unique 128-bit-or-stronger provisioning secret and unique non-zero device ID. Manufacturing must detect duplicates and protect/key-erase failed units.
- Derive direction-specific application traffic keys from the device secret, both device identities, protocol version and a fresh authenticated session identifier using an SDK-reviewed KDF. Do not use the long-term OOB value directly as the AES-CCM traffic key.
- The authenticated application-handshake transcript explicitly negotiates one GESTURE_EVENT payload profile: LEGACY_V1 or MULTICHANNEL_V2. A replay guard initializes to UNSUPPORTED; the selected profile is bound to both traffic keys and explicitly installed before any event is accepted. Length sniffing, fallback after decode failure and unauthenticated profile switching are prohibited.
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

Nonce reuse under the same traffic key is catastrophic. Sequence exhaustion, persistent-state uncertainty, session collision or interrupted counter commit forces disarm and authenticated reprovisioning/rekey; no wraparound is allowed. The portable receiver runtime treats session_id as a strictly increasing persistent epoch and commits it before activating a session; a target may use another independently reviewed uniqueness construction only after updating this contract.

## Receive transaction order

1. Force outputs safe until boot, credentials and replay storage are healthy.
2. Check version, direction, allow-listed command, device, session, the exact payload length required by the authenticated session profile, non-zero sequence, strict sequence greater than receive_high_water and freshness.
3. Build canonical nonce/AAD and verify/decrypt AES-CCM in constant-time library code.
4. Atomically persist the new receive high-water mark. If commit fails, erase plaintext and reject.
5. Only then deliver plaintext to the state machine. A protocol rejection never activates an output; the receiver runtime closes the suspect session and forces every desired output inactive.

Flash endurance requires a reviewed journal/monotonic storage design, not writing one flash word per radio packet. Options include authenticated session epochs backed by atomic wear-levelled storage plus a RAM sequence window. The selected construction needs an independent security review and power-cut campaign.

## Command allow-list

| ID | Command | Receiver behavior |
|---:|---|---|
| 1 | DISARM | Immediately clear every output and physical-arm lease; sender transmits three prompt copies with unique sequences. |
| 2 | HEARTBEAT | Refresh link liveness only; does not refresh physical-arm authorization. |
| 3 | ARM_LEASE | Valid only from the paired wand while its dedicated switch is continuously held; renews receiver lease for 100 ms. Refresh preserves any COMMAND_PENDING state and immutable pulse deadline. Wand sends at ≤25 ms interval. |
| 16 | SET_AUX | Set a documented non-flight-critical low-voltage AUX signal while lease remains valid. Never map to flight arming/propulsion/primary control. |
| 17 | PULSE_ISOLATED_OC | Pulse floating open collector for 1–500 ms, still gated by the 100 ms renewable arm lease. |
| 18 | PULSE_LOW_SIDE | Pulse common-ground 5–12 V low-side output for 1–500 ms, still gated by the arm lease and hardware limits. |
| 32 | FEEDBACK | Receiver→wand state/result indication; never causes a receiver output. |
| 33 | GESTURE_EVENT | Wand-to-receiver media telemetry. LEGACY_V1 is exactly 2 bytes; negotiated MULTICHANNEL_V2 is exactly 14 bytes. Neither profile directly changes a dangerous output. |

FEEDBACK is the only receiver-to-wand command. Every other listed command is wand-to-receiver; a command used in the wrong direction is rejected before decryption or replay-state commit. Only HEARTBEAT and ARM_LEASE renew the receiver heartbeat deadline. Output commands and GESTURE_EVENT do not extend liveness or physical authorization.

GESTURE_EVENT has two non-ambiguous profiles. LEGACY_V1 is exactly two bytes (gesture_id, confidence_percent) and is restricted to the compatibility channel. MULTICHANNEL_V2 is exactly 14 bytes: payload schema byte 2, logical channel 0..7, gesture ID, confidence, battery percent or 0xff unknown, status flags, sender device ID (BE32) and session ID (BE32). Frame version 1 and V2 payload schema 2 are different namespaces.

The receiver never infers a profile from a permissive length check. A V1 session rejects 14 bytes, a V2 session rejects 2 bytes, and an unsupported or uninstalled profile rejects every gesture event. After authenticated decryption, V2 duplicates are cross-checked against the authenticated frame device, session and selected route channel. A mismatch closes only that channel and session safe. V2 media routing additionally requires the authenticated `ARM_ACTIVE` status bit, which represents the wand's continuously asserted physical control; a missing bit closes that slot silently before pattern or audio scheduling. `ARM_ACTIVE` is not an output authorization and does not renew the receiver's 100 ms output lease. Battery 0xff without BATTERY_KNOWN means no battery information and does not suppress a valid effect; a known value at or below the low-battery threshold selects the warning.

LEGACY_V1 has no authenticated physical-arm field, so channel zero accepts it only as a compatibility boundary. This is a deliberate weaker profile: production multi-wand/effects sessions should negotiate V2, and a legacy gesture must never be treated as evidence for a physical arm, an `ARM_LEASE` or any dangerous-output authorization.

Display animation, RGB status and volume-limited synthesized audio are low-risk media feedback only. Their scheduler is separate from the output state machine and has no API that can arm AUX, optocoupler, low-side, propulsion or any other dangerous actuator. Unknown commands or flags, zero-length-required violations, range errors, cross-profile lengths or mixed directions are rejected. There is intentionally no mains command, emergency-stop command, flight arm, propulsion, motor or primary flight-control command.

## Required negative tests

Duplicate or stale sequence, sequence 0/max/wrap, old/future timestamp, wrong device/session/direction/channel, V2 gesture without authenticated `ARM_ACTIVE`, changed header, changed ciphertext/tag, truncated/oversized length, V1-with-14-byte, V2-with-2-byte, unsupported/uninstalled profile, unknown command/flags, nonce collision, reboot/counter rollback, interrupted persistence, cross-pair packet and absent CCM callback must all reject with outputs unchanged and safe. State-machine vectors must also prove that continuous ARM_LEASE refresh cannot extend a pulse and that an active deadline whose uint32 value is zero still expires.
