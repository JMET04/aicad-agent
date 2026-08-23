#ifndef MW_RECEIVER_MULTICHANNEL_H
#define MW_RECEIVER_MULTICHANNEL_H

#include "mw_effect_scheduler.h"
#include "mw_receiver_runtime.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_RECEIVER_LOGICAL_CHANNELS UINT8_C(8)
#define MW_RECEIVER_NO_OUTPUT_OWNER INT8_C(-1)

typedef enum {
    MW_RECEIVER_CHANNEL_ACCEPTED_NO_ACTUATION = 0,
    MW_RECEIVER_CHANNEL_ACCEPTED_OUTPUT_POLICY,
    MW_RECEIVER_CHANNEL_REJECTED_NOT_CONFIGURED,
    MW_RECEIVER_CHANNEL_REJECTED_RUNTIME,
    MW_RECEIVER_CHANNEL_REJECTED_BINDING,
    MW_RECEIVER_CHANNEL_REJECTED_ARM_INACTIVE,
    MW_RECEIVER_CHANNEL_REJECTED_OUTPUT_DISABLED,
    MW_RECEIVER_CHANNEL_REJECTED_OUTPUT_CONFLICT
} mw_receiver_channel_result_t;

typedef struct {
    bool configured;
    uint8_t logical_channel;
    uint32_t peer_device_id;
    mw_receiver_runtime_t runtime;
} mw_receiver_channel_slot_t;

typedef struct {
    uint32_t local_device_id;
    mw_receiver_channel_slot_t channels[MW_RECEIVER_LOGICAL_CHANNELS];
    mw_effect_scheduler_t effects;
    int8_t output_owner;
    bool dangerous_output_authority_enabled;
} mw_receiver_multichannel_t;

void mw_receiver_multichannel_init(
    mw_receiver_multichannel_t *manager,
    uint32_t local_device_id);
bool mw_receiver_multichannel_set_effect_readiness(
    mw_receiver_multichannel_t *manager,
    bool display_ready,
    bool audio_ready);
bool mw_receiver_multichannel_set_output_authority(
    mw_receiver_multichannel_t *manager,
    bool enabled);
bool mw_receiver_multichannel_configure(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    uint32_t peer_device_id,
    uint32_t persisted_session_id,
    bool session_storage_ready);
bool mw_receiver_multichannel_boot_channel(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    bool target_self_test_passed,
    bool power_good,
    bool credentials_ready);
bool mw_receiver_multichannel_begin_handshake(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    uint32_t peer_device_id,
    uint32_t session_id,
    uint32_t now_ms);
bool mw_receiver_multichannel_complete_handshake(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    const mw_receiver_handshake_security_t *security,
    uint32_t now_ms,
    mw_commit_session_epoch_fn commit_session_epoch,
    void *session_persistence_context);
bool mw_receiver_multichannel_bind_durable_session_window(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    uint32_t durable_session_id,
    uint32_t reserved_sequence_ceiling);
mw_receiver_channel_result_t mw_receiver_multichannel_receive(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel,
    const mw_encrypted_frame_t *frame,
    uint32_t now_ms,
    mw_ccm_decrypt_fn decrypt,
    void *decrypt_context,
    mw_commit_high_water_fn commit_high_water,
    void *sequence_persistence_context);
void mw_receiver_multichannel_tick(
    mw_receiver_multichannel_t *manager,
    uint32_t now_ms);
void mw_receiver_multichannel_link_lost(
    mw_receiver_multichannel_t *manager,
    uint8_t logical_channel);
const mw_output_state_t *mw_receiver_multichannel_outputs(
    const mw_receiver_multichannel_t *manager);
size_t mw_receiver_multichannel_active_sessions(
    const mw_receiver_multichannel_t *manager);

#ifdef __cplusplus
}
#endif

#endif
