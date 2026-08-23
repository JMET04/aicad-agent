# Receiver Effects Target Integration

Status: contract only. No NINA-B302 target was configured, compiled or flashed.

Target API baseline: nRF Connect SDK v3.4.0 / Zephyr v4.4.0. The NVS public
header for that baseline is `<zephyr/kvss/nvs.h>`. Host builds and static
contract checks do not establish that this target configuration compiles.

## Boot order

1. The 100 kOhm hardware pull-down keeps MAX98357A SD/MODE muted. Configure
   P0.16 low, P0.23 backlight gate low/off and common-anode RGB
   P0.24/P0.25/P1.00 high/off before BLE, flash or scheduler initialization.
2. Verify protected 5 V, 3.3 V, reset reason and watchdog ownership. A failed or
   uncertain power/self-test keeps audio muted and backlight off.
3. Load eight independent peer identities, session epochs and replay stores.
   Duplicate IDs or any storage uncertainty leaves the affected slot disabled.
4. Bring up the exact GC9A01A module over SPIM and verify reset, rotation,
   RGB565 byte order, round mask and backlight driver. Then set display_ready.
5. Bring up I2S at mono 16 kHz, signed 16-bit PCM with DMA double buffers.
   Verify zero-fill, gain, clipping and SD/MODE behavior before setting
   audio_ready and releasing mute.
6. Keep mw_receiver_multichannel dangerous output authority at its default
   disabled value. Start BLE SC-only plus authenticated application handshake.
   Install the exact negotiated gesture payload profile in the replay guard;
   its reset default is UNSUPPORTED. Channels 1..7 require MULTICHANNEL_V2,
   and every V2 media event requires authenticated ARM_ACTIVE or the slot is
   closed silently before rendering/audio.
7. Route decrypted frames only through mw_receiver_multichannel_receive.
   Stream mw_pattern_render_row_rgb565 output to SPI and
   mw_audio_synth_render output to I2S. The media adapter must not call or own a
   dangerous actuator driver.

## Durable session epoch candidate

`mw_epoch_record` owns the canonical 32-byte big-endian record and CRC;
`mw_epoch_store` owns the target-independent A/B transaction and full readback;
`mw_epoch_nvs` is only the Zephyr mutex, flash-map and NVS callback adapter.
The local `CMakeLists.txt` is a reusable source fragment that adds the record,
store and adapter to an existing Zephyr `app` target. It is not a standalone
application and the real receiver entrypoint must include it explicitly after
`find_package(Zephyr)`.

The real board overlay must provide a dedicated, erase-page-aligned
`mw_epoch_partition` of at least two sectors. It must not overlap
`storage_partition`, the application image, MCUboot or any settings/filesystem
partition. Channel/copy IDs are fixed at `0x4D00 + channel * 2 + copy`, covering
`0x4D00..0x4D0F` for the frozen eight channels. The candidate `prj.conf`
requires `CONFIG_FLASH`, `CONFIG_FLASH_MAP`, `CONFIG_FLASH_PAGE_LAYOUT`,
`CONFIG_NVS`, `CONFIG_NVS_DATA_CRC` and `CONFIG_MPU_ALLOW_FLASH_WRITE`.

The Zephyr v4.4.0 NVS commit model writes data before metadata; a torn write
without valid metadata is consequently observed as ENOENT after mount. A
present short/oversize record, CRC failure, identity/copy mismatch, generation
conflict or I/O error remains fail-closed. Double ENOENT is accepted only under
an explicit factory/provisioning policy. `nvs_write` may return 32 or zero for
an unchanged record, but either result still requires a full two-slot readback,
canonical decode/CRC verification, exact candidate-byte comparison and A/B
reselection before the transaction succeeds.

The authenticated ACK ordering is frozen as follows:

1. Authenticate and validate the handshake without enabling FRAME writes.
2. Commit the next session epoch through `mw_epoch_store`; failure closes the
   connection and emits no ACK.
3. Snapshot the committed record and bind the portable durable replay window.
4. Bind the matching session/ceiling RAM high-water callback.
5. Build and indicate the authenticated ACK carrying the receiver clock.
6. Enable encrypted FRAME handling only after indication confirmation.
7. On ACK/indication failure, clear the RAM binding and disconnect. The durable
   epoch remains consumed, so a retry must use a strictly higher session.

NVS metadata/data CRCs and the application record CRC detect corruption; they
do not establish rollback-resistant physical security. Power-cut recovery,
partition isolation and the ACK sequence remain target-build/HIL gates.

## Frozen Rev A0 GPIO and connector contract

The independent PCB net table binds TFT SCK/MOSI/CS_N/DC/RESET_N/BL gate to
NINA pads 52/50/51/48/49/47; I2S BCLK/LRCLK/DOUT and AUDIO_SD_CTRL to pads
1/2/3/4; and common-anode active-low RGB R/G/B to pads 5/7/8. AUDIO_SD_CTRL
passes through 2.2 kOhm and has a 100 kOhm hardware pull-down.

The locked Waveshare SKU 19192 display connector J2 is
1=3V3, 2=GND, 3=MOSI/DIN, 4=SCK/CLK, 5=CS, 6=DC, 7=RST, 8=switched BL.
These are target-contract facts, not evidence that the target has compiled or
that a physical display/audio board has passed HIL.

## Buffer and timing budget

A full 240 x 240 x 16-bit framebuffer costs 115200 bytes and is not required.
Use two 240-pixel rows (960 bytes total) for SPI DMA. A candidate pair of
256-sample signed-16-bit audio blocks costs 1024 bytes. At 20 animation frames
per second the renderer produces 1.152 million pixels per second; target CPU,
SPI bandwidth, radio concurrency and watchdog margin must be measured. Exact
Zephyr flash/RAM/map numbers remain open because no target build exists.

The effect core procedurally synthesizes all cues. No external audio asset is
needed. Master digital volume is capped at 40 percent; the boom path is capped
at 25 percent and sample absolute peak 7000. These digital caps do not establish
safe acoustic SPL; enclosure/speaker/amplifier HIL must set a lower product
limit if required.

## Mandatory target/HIL evidence

- pinned nRF Connect SDK v3.4.0 / Zephyr v4.4.0 toolchain, NINA board
  definition, devicetree,
  prj.conf, map, binary and hashes;
- GC9A01A color/order/rotation/tearing, 20 fps target, SPI DMA and BLE
  coexistence;
- MAX98357A I2S clock/data capture, boot/watchdog/fault mute, pop/click, peak
  SPL, speaker/amp temperature and 5 V rail transient;
- 5 V / 2 A USB-C current policy, PTC/inrush/brownout, 3.3 V rail and RF range;
- eight simultaneous sessions, replay/profile/channel negatives, independent
  heartbeat expiry and display/audio arbitration;
- unknown battery 0xff still plays an armed gesture; known low battery selects
  the warning; absent V2 ARM_ACTIVE closes only that slot with no cue;
- FIRE red/orange swirl plus whoosh/crackle, ICE blue/white crystal plus
  chime/crack, EXPLOSION white/yellow shockwave plus limited boom, and all
  remaining mapping-table effects on the real display/speaker.

receiver-effects-overlay-contract.yaml lists the required nodes and aliases but
is deliberately not named as a compileable overlay. Generate the real overlay
only after the receiver flash map supplies an audited, non-overlapping offset
and size for `mw_epoch_partition`.
