#ifndef MW_STATE_MACHINE_H
#define MW_STATE_MACHINE_H

#include "mw_protocol.h"

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MW_ARM_HOLD_MS UINT32_C(800)
#define MW_ARM_LEASE_MS UINT32_C(100)
#define MW_ARM_LEASE_REFRESH_MS UINT32_C(25)
#define MW_LINK_LOSS_MS UINT32_C(250)
#define MW_MAX_OUTPUT_PULSE_MS UINT32_C(500)

typedef enum {
    MW_ROLE_WAND = 1,
    MW_ROLE_RECEIVER = 2
} mw_role_t;

typedef enum {
    MW_STATE_BOOT = 0,
    MW_STATE_UNPAIRED,
    MW_STATE_PAIRING_AUTH,
    MW_STATE_DISARMED,
    MW_STATE_ARM_PENDING,
    MW_STATE_ARMED,
    MW_STATE_COMMAND_PENDING,
    MW_STATE_FAULT,
    MW_STATE_DFU
} mw_state_t;

typedef struct {
    bool aux_active;
    bool isolated_oc_active;
    bool low_side_active;
} mw_output_state_t;

typedef struct {
    mw_role_t role;
    mw_state_t state;
    mw_output_state_t outputs;
    uint32_t arm_pressed_at_ms;
    uint32_t arm_lease_deadline_ms;
    uint32_t link_deadline_ms;
    uint32_t output_deadline_ms;
    uint8_t pending_disarm_frames;
    bool output_deadline_active;
    bool paired;
    bool physical_arm_pressed;
} mw_state_machine_t;

void mw_state_machine_init(mw_state_machine_t *machine, mw_role_t role);
void mw_state_machine_boot_complete(mw_state_machine_t *machine, bool paired);
void mw_state_machine_set_pairing(mw_state_machine_t *machine, bool authorized);
void mw_state_machine_arm_input(mw_state_machine_t *machine, bool pressed, uint32_t now_ms);
void mw_state_machine_tick(mw_state_machine_t *machine, uint32_t now_ms);
void mw_state_machine_link_lost(mw_state_machine_t *machine);
void mw_state_machine_fault(mw_state_machine_t *machine);
bool mw_state_machine_receiver_command(
    mw_state_machine_t *machine,
    mw_command_t command,
    uint16_t argument,
    uint32_t now_ms);
bool mw_state_machine_take_disarm_request(mw_state_machine_t *machine);
bool mw_state_machine_outputs_safe(const mw_state_machine_t *machine);

#ifdef __cplusplus
}
#endif

#endif
