#include "mw_board_pins.h"
#include "mw_gesture.h"
#include "mw_protocol.h"
#include "mw_state_machine.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition) \
    do { \
        if (!(condition)) { \
            (void)fprintf(stderr, "host review check failed at line %d\n", __LINE__); \
            return 1; \
        } \
    } while (false)

typedef struct {
    uint32_t committed_high_water;
} host_persistence_t;

/* Host harness adapter only: it tests callback plumbing, not cryptography. */
static bool host_noncrypto_decrypt(
    void *context,
    const uint8_t nonce[MW_NONCE_BYTES],
    const uint8_t *aad,
    size_t aad_length,
    const uint8_t *ciphertext,
    size_t ciphertext_length,
    const uint8_t tag[MW_TAG_BYTES],
    uint8_t *plaintext_out)
{
    (void)context;
    (void)nonce;
    (void)aad;
    (void)aad_length;
    (void)tag;
    if ((ciphertext == NULL) || (plaintext_out == NULL)) {
        return false;
    }
    (void)memcpy(plaintext_out, ciphertext, ciphertext_length);
    return true;
}

static bool host_commit_high_water(void *context, uint32_t sequence)
{
    host_persistence_t *persistence = (host_persistence_t *)context;
    if ((persistence == NULL) || (sequence <= persistence->committed_high_water)) {
        return false;
    }
    persistence->committed_high_water = sequence;
    return true;
}

static int check_protocol(void)
{
    mw_replay_guard_t guard;
    mw_encrypted_frame_t frame;
    host_persistence_t persistence = {0U};
    uint8_t plaintext[MW_MAX_PAYLOAD_BYTES] = {0};
    uint8_t nonce[MW_NONCE_BYTES] = {0};
    uint8_t aad[MW_AAD_BYTES] = {0};

    (void)memset(&frame, 0, sizeof(frame));
    frame.header.version = MW_PROTOCOL_VERSION;
    frame.header.direction = (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER;
    frame.header.command = (uint8_t)MW_CMD_SET_AUX;
    frame.header.device_id = UINT32_C(0x01020304);
    frame.header.session_id = UINT32_C(0x11223344);
    frame.header.sequence = 1U;
    frame.header.issued_ms = 1000U;
    frame.header.payload_length = 1U;
    frame.ciphertext[0] = UINT8_C(0xA5);

    mw_protocol_build_nonce(&frame.header, nonce);
    CHECK(nonce[0] == (uint8_t)MW_DIRECTION_WAND_TO_RECEIVER);
    CHECK(nonce[1] == UINT8_C(0x01));
    CHECK(nonce[12] == UINT8_C(0x01));
    CHECK(mw_protocol_encode_aad(&frame.header, aad) == MW_AAD_BYTES);
    CHECK(aad[0] == MW_PROTOCOL_VERSION);
    CHECK(aad[21] == UINT8_C(0x01));

    mw_replay_guard_init(
        &guard,
        frame.header.device_id,
        frame.header.session_id,
        0U,
        false);
    CHECK(!mw_protocol_accept_and_decrypt(
        &guard,
        &frame,
        MW_DIRECTION_WAND_TO_RECEIVER,
        1050U,
        host_noncrypto_decrypt,
        NULL,
        host_commit_high_water,
        &persistence,
        plaintext));

    guard.persistence_ready = true;
    frame.header.payload_length = 2U;
    CHECK(!mw_protocol_accept_and_decrypt(
        &guard,
        &frame,
        MW_DIRECTION_WAND_TO_RECEIVER,
        1050U,
        host_noncrypto_decrypt,
        NULL,
        host_commit_high_water,
        &persistence,
        plaintext));
    frame.header.payload_length = 1U;
    frame.header.flags = 1U;
    CHECK(!mw_protocol_accept_and_decrypt(
        &guard,
        &frame,
        MW_DIRECTION_WAND_TO_RECEIVER,
        1050U,
        host_noncrypto_decrypt,
        NULL,
        host_commit_high_water,
        &persistence,
        plaintext));
    frame.header.flags = 0U;

    CHECK(mw_protocol_accept_and_decrypt(
        &guard,
        &frame,
        MW_DIRECTION_WAND_TO_RECEIVER,
        1050U,
        host_noncrypto_decrypt,
        NULL,
        host_commit_high_water,
        &persistence,
        plaintext));
    CHECK(plaintext[0] == UINT8_C(0xA5));
    CHECK(guard.receive_high_water == 1U);
    CHECK(!mw_protocol_accept_and_decrypt(
        &guard,
        &frame,
        MW_DIRECTION_WAND_TO_RECEIVER,
        1050U,
        host_noncrypto_decrypt,
        NULL,
        host_commit_high_water,
        &persistence,
        plaintext));

    frame.header.command = (uint8_t)MW_CMD_GESTURE_EVENT;
    frame.header.sequence = 2U;
    frame.header.payload_length = 1U;
    frame.ciphertext[0] = (uint8_t)MW_GESTURE_CIRCLE_CW;
    frame.ciphertext[1] = UINT8_C(82);
    CHECK(!mw_protocol_accept_and_decrypt(
        &guard,
        &frame,
        MW_DIRECTION_WAND_TO_RECEIVER,
        1050U,
        host_noncrypto_decrypt,
        NULL,
        host_commit_high_water,
        &persistence,
        plaintext));
    frame.header.payload_length = 2U;
    CHECK(mw_protocol_accept_and_decrypt(
        &guard,
        &frame,
        MW_DIRECTION_WAND_TO_RECEIVER,
        1050U,
        host_noncrypto_decrypt,
        NULL,
        host_commit_high_water,
        &persistence,
        plaintext));
    CHECK(plaintext[0] == (uint8_t)MW_GESTURE_CIRCLE_CW);
    CHECK(plaintext[1] == UINT8_C(82));
    return 0;
}

static int check_state_machine(void)
{
    mw_state_machine_t wand;
    mw_state_machine_t receiver;

    mw_state_machine_init(&wand, MW_ROLE_WAND);
    mw_state_machine_boot_complete(&wand, true);
    CHECK(wand.state == MW_STATE_DISARMED);
    mw_state_machine_arm_input(&wand, true, 100U);
    mw_state_machine_tick(&wand, 899U);
    CHECK(wand.state == MW_STATE_ARM_PENDING);
    mw_state_machine_tick(&wand, 900U);
    CHECK(wand.state == MW_STATE_ARMED);
    mw_state_machine_arm_input(&wand, false, 901U);
    CHECK(wand.state == MW_STATE_DISARMED);
    CHECK(mw_state_machine_take_disarm_request(&wand));
    CHECK(mw_state_machine_take_disarm_request(&wand));
    CHECK(mw_state_machine_take_disarm_request(&wand));
    CHECK(!mw_state_machine_take_disarm_request(&wand));

    mw_state_machine_init(&receiver, MW_ROLE_RECEIVER);
    CHECK(mw_state_machine_outputs_safe(&receiver));
    mw_state_machine_boot_complete(&receiver, true);
    CHECK(!mw_state_machine_receiver_command(
        &receiver, MW_CMD_PULSE_LOW_SIDE, 50U, 1000U));
    CHECK(mw_state_machine_receiver_command(
        &receiver, MW_CMD_ARM_LEASE, 0U, 1000U));
    CHECK(!mw_state_machine_receiver_command(
        &receiver, MW_CMD_SET_AUX, 2U, 1000U));
    CHECK(!mw_state_machine_receiver_command(
        &receiver, MW_CMD_PULSE_LOW_SIDE, 0U, 1000U));
    CHECK(!mw_state_machine_receiver_command(
        &receiver, MW_CMD_PULSE_LOW_SIDE, 501U, 1000U));
    CHECK(mw_state_machine_receiver_command(
        &receiver, MW_CMD_PULSE_LOW_SIDE, 500U, 1000U));
    CHECK(receiver.outputs.low_side_active);
    mw_state_machine_tick(&receiver, 1099U);
    CHECK(receiver.outputs.low_side_active);
    mw_state_machine_tick(&receiver, 1100U);
    CHECK(mw_state_machine_outputs_safe(&receiver));
    CHECK(receiver.state == MW_STATE_DISARMED);
    return 0;
}

static int check_board_pin_authority(void)
{
    CHECK(MW_HAPTIC_EN_GPIO_PORT == 0U);
    CHECK(MW_HAPTIC_EN_GPIO_PIN == 13U);
    CHECK(MW_I2C_SCL_GPIO_PORT == 0U);
    CHECK(MW_I2C_SCL_GPIO_PIN == 11U);
    CHECK(MW_I2C_SDA_GPIO_PORT == 1U);
    CHECK(MW_I2C_SDA_GPIO_PIN == 9U);
    CHECK(MW_ARM_N_GPIO_PORT == 0U);
    CHECK(MW_ARM_N_GPIO_PIN == 6U);
    return 0;
}

static int check_gesture_rejection(void)
{
    const mw_gesture_result_t result =
        mw_gesture_classify_relative_window(NULL, 0U);
    CHECK(result.id == MW_GESTURE_NONE);
    CHECK(result.rejected);
    return 0;
}

int main(void)
{
    CHECK(check_board_pin_authority() == 0);
    CHECK(check_protocol() == 0);
    CHECK(check_state_machine() == 0);
    CHECK(check_gesture_rejection() == 0);
    (void)puts("host review checks passed; no target/crypto claim");
    return 0;
}
