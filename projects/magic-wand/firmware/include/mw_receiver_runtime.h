#ifndef MW_RECEIVER_RUNTIME_H
#define MW_RECEIVER_RUNTIME_H

#include "mw_gesture.h"
#include "mw_gesture_event_v2.h"
#include "mw_protocol.h"
#include "mw_state_machine.h"

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_RECEIVER_HANDSHAKE_TIMEOUT_MS UINT32_C(1000)

typedef enum {
    MW_RECEIVER_BOOT_SAFE = 0,
    MW_RECEIVER_UNPROVISIONED,
    MW_RECEIVER_WAIT_HANDSHAKE,
    MW_RECEIVER_HANDSHAKE_PENDING,
    MW_RECEIVER_SESSION_ACTIVE,
    MW_RECEIVER_FAULT
} mw_receiver_runtime_state_t;

typedef enum {
    MW_RECEIVER_FRAME_ACCEPTED_NO_ACTUATION = 0,
    MW_RECEIVER_FRAME_ACCEPTED_OUTPUT_POLICY,
    MW_RECEIVER_FRAME_REJECTED_NO_SESSION,
    MW_RECEIVER_FRAME_REJECTED_PROTOCOL,
    MW_RECEIVER_FRAME_REJECTED_APPLICATION,
    MW_RECEIVER_FRAME_REJECTED_FAULT
} mw_receiver_frame_result_t;

typedef struct {
    bool secure_link_authenticated;
    bool application_handshake_authenticated;
    bool direction_specific_traffic_key_ready;
    mw_gesture_payload_profile_t gesture_profile;
} mw_receiver_handshake_security_t;

typedef bool (*mw_commit_session_epoch_fn)(
    void *context,
    uint32_t session_id);

typedef struct {
    mw_receiver_runtime_state_t state;
    mw_state_machine_t output_policy;
    mw_replay_guard_t replay_guard;
    uint32_t local_device_id;
    uint32_t paired_wand_device_id;
    uint32_t pending_session_id;
    uint32_t active_session_id;
    uint32_t last_committed_session_id;
    uint32_t handshake_deadline_ms;
    uint32_t heartbeat_deadline_ms;
    mw_gesture_payload_profile_t negotiated_gesture_profile;
    mw_gesture_result_t last_gesture_event;
    mw_gesture_event_v2_t last_gesture_event_v2;
    bool session_storage_ready;
    bool power_good;
    bool credentials_ready;
    bool last_gesture_valid;
    bool last_gesture_v2_valid;
} mw_receiver_runtime_t;

/*
 * Initialize policy in an output-safe boot state. persisted_session_id is a
 * monotonic epoch loaded from rollback-resistant platform storage. A zero or
 * duplicate device identity, or uncertain storage, makes the runtime fail
 * closed.
 */
void mw_receiver_runtime_init(
    mw_receiver_runtime_t *runtime,
    uint32_t local_device_id,
    uint32_t paired_wand_device_id,
    uint32_t persisted_session_id,
    bool session_storage_ready);

void mw_receiver_runtime_boot_complete(
    mw_receiver_runtime_t *runtime,
    bool target_self_test_passed,
    bool power_good,
    bool credentials_ready);

/*
 * Starts an application handshake only after the platform has established a
 * candidate BLE link. session_id is a strictly increasing, non-zero epoch;
 * wraparound and reuse are rejected.
 */
bool mw_receiver_runtime_begin_handshake(
    mw_receiver_runtime_t *runtime,
    uint32_t peer_device_id,
    uint32_t session_id,
    uint32_t now_ms);

/*
 * Completes the handshake only after the platform proves all three security
 * predicates and atomically persists the new session epoch. This portable
 * core does not implement BLE, a KDF, AES-CCM or flash journalling.
 */
bool mw_receiver_runtime_complete_handshake(
    mw_receiver_runtime_t *runtime,
    const mw_receiver_handshake_security_t *security,
    uint32_t now_ms,
    mw_commit_session_epoch_fn commit_session_epoch,
    void *session_persistence_context);

/*
 * Bind the active session to an epoch that the platform has already committed
 * durably and verified. A target must call this before sending its authenticated
 * ACK or exposing FRAME writes when it wants RAM-only sequence commits. An
 * invalid bind attempt against an active session faults the runtime closed.
 */
bool mw_receiver_runtime_bind_durable_session_window(
    mw_receiver_runtime_t *runtime,
    uint32_t durable_session_id,
    uint32_t reserved_sequence_ceiling);

mw_receiver_frame_result_t mw_receiver_runtime_receive_frame(
    mw_receiver_runtime_t *runtime,
    const mw_encrypted_frame_t *frame,
    uint32_t now_ms,
    mw_ccm_decrypt_fn decrypt,
    void *decrypt_context,
    mw_commit_high_water_fn commit_high_water,
    void *sequence_persistence_context);

void mw_receiver_runtime_tick(
    mw_receiver_runtime_t *runtime,
    uint32_t now_ms);

void mw_receiver_runtime_link_lost(mw_receiver_runtime_t *runtime);
void mw_receiver_runtime_power_good_changed(
    mw_receiver_runtime_t *runtime,
    bool power_good);
void mw_receiver_runtime_fault(mw_receiver_runtime_t *runtime);

bool mw_receiver_runtime_outputs_safe(const mw_receiver_runtime_t *runtime);
const mw_output_state_t *mw_receiver_runtime_outputs(
    const mw_receiver_runtime_t *runtime);

#ifdef __cplusplus
}
#endif

#endif
