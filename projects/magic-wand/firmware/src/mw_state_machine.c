#include "mw_state_machine.h"

#include <string.h>

static bool deadline_reached(uint32_t now_ms, uint32_t deadline_ms)
{
    return ((int32_t)(now_ms - deadline_ms) >= 0);
}

static void clear_outputs(mw_state_machine_t *machine)
{
    machine->outputs.aux_active = false;
    machine->outputs.isolated_oc_active = false;
    machine->outputs.low_side_active = false;
    machine->output_deadline_ms = 0U;
}

static void enter_safe_state(mw_state_machine_t *machine, mw_state_t next_state)
{
    clear_outputs(machine);
    machine->arm_lease_deadline_ms = 0U;
    machine->link_deadline_ms = 0U;
    machine->state = next_state;
}

void mw_state_machine_init(mw_state_machine_t *machine, mw_role_t role)
{
    if (machine == NULL) {
        return;
    }

    (void)memset(machine, 0, sizeof(*machine));
    machine->role = role;
    machine->state = MW_STATE_BOOT;
}

void mw_state_machine_boot_complete(mw_state_machine_t *machine, bool paired)
{
    if (machine == NULL) {
        return;
    }

    clear_outputs(machine);
    machine->paired = paired;
    if ((machine->role == MW_ROLE_WAND) && machine->physical_arm_pressed) {
        machine->state = MW_STATE_FAULT;
    } else {
        machine->state = paired ? MW_STATE_DISARMED : MW_STATE_UNPAIRED;
    }
}

void mw_state_machine_set_pairing(mw_state_machine_t *machine, bool authorized)
{
    if (machine == NULL) {
        return;
    }

    enter_safe_state(machine, authorized ? MW_STATE_DISARMED : MW_STATE_UNPAIRED);
    machine->paired = authorized;
}

void mw_state_machine_arm_input(mw_state_machine_t *machine, bool pressed, uint32_t now_ms)
{
    if ((machine == NULL) || (machine->role != MW_ROLE_WAND)) {
        return;
    }

    machine->physical_arm_pressed = pressed;
    if ((machine->state == MW_STATE_BOOT) || (machine->state == MW_STATE_UNPAIRED) ||
        (machine->state == MW_STATE_PAIRING_AUTH) || (machine->state == MW_STATE_FAULT) ||
        (machine->state == MW_STATE_DFU)) {
        return;
    }

    if (!pressed) {
        enter_safe_state(machine, MW_STATE_DISARMED);
        machine->pending_disarm_frames = UINT8_C(3);
        return;
    }

    if (machine->state == MW_STATE_DISARMED) {
        machine->arm_pressed_at_ms = now_ms;
        machine->state = MW_STATE_ARM_PENDING;
    }
}

void mw_state_machine_tick(mw_state_machine_t *machine, uint32_t now_ms)
{
    if (machine == NULL) {
        return;
    }

    if ((machine->role == MW_ROLE_WAND) &&
        (machine->state == MW_STATE_ARM_PENDING) &&
        machine->physical_arm_pressed &&
        deadline_reached(now_ms, machine->arm_pressed_at_ms + MW_ARM_HOLD_MS)) {
        machine->state = MW_STATE_ARMED;
    }

    if (machine->role != MW_ROLE_RECEIVER) {
        return;
    }

    if (((machine->state == MW_STATE_ARMED) ||
         (machine->state == MW_STATE_COMMAND_PENDING)) &&
        deadline_reached(now_ms, machine->arm_lease_deadline_ms)) {
        enter_safe_state(machine, MW_STATE_DISARMED);
        return;
    }

    if (((machine->state == MW_STATE_ARMED) ||
         (machine->state == MW_STATE_COMMAND_PENDING)) &&
        deadline_reached(now_ms, machine->link_deadline_ms)) {
        enter_safe_state(machine, MW_STATE_DISARMED);
        return;
    }

    if ((machine->state == MW_STATE_COMMAND_PENDING) &&
        (machine->output_deadline_ms != 0U) &&
        deadline_reached(now_ms, machine->output_deadline_ms)) {
        clear_outputs(machine);
        machine->state = MW_STATE_ARMED;
    }
}

void mw_state_machine_link_lost(mw_state_machine_t *machine)
{
    if (machine == NULL) {
        return;
    }
    enter_safe_state(machine, machine->paired ? MW_STATE_DISARMED : MW_STATE_UNPAIRED);
}

void mw_state_machine_fault(mw_state_machine_t *machine)
{
    if (machine == NULL) {
        return;
    }
    enter_safe_state(machine, MW_STATE_FAULT);
}

bool mw_state_machine_receiver_command(
    mw_state_machine_t *machine,
    mw_command_t command,
    uint16_t argument,
    uint32_t now_ms)
{
    uint32_t pulse_ms;

    if ((machine == NULL) || (machine->role != MW_ROLE_RECEIVER) ||
        !machine->paired || (machine->state == MW_STATE_BOOT) ||
        (machine->state == MW_STATE_UNPAIRED) ||
        (machine->state == MW_STATE_PAIRING_AUTH) ||
        (machine->state == MW_STATE_FAULT) || (machine->state == MW_STATE_DFU)) {
        return false;
    }

    if (command == MW_CMD_DISARM) {
        enter_safe_state(machine, MW_STATE_DISARMED);
        return true;
    }

    if (command == MW_CMD_HEARTBEAT) {
        machine->link_deadline_ms = now_ms + MW_LINK_LOSS_MS;
        return true;
    }

    if (command == MW_CMD_ARM_LEASE) {
        machine->arm_lease_deadline_ms = now_ms + MW_ARM_LEASE_MS;
        machine->link_deadline_ms = now_ms + MW_LINK_LOSS_MS;
        machine->state = MW_STATE_ARMED;
        return true;
    }

    if (((machine->state != MW_STATE_ARMED) &&
         (machine->state != MW_STATE_COMMAND_PENDING)) ||
        deadline_reached(now_ms, machine->arm_lease_deadline_ms)) {
        enter_safe_state(machine, MW_STATE_DISARMED);
        return false;
    }

    machine->link_deadline_ms = now_ms + MW_LINK_LOSS_MS;
    switch (command) {
    case MW_CMD_SET_AUX:
        if (argument > 1U) {
            return false;
        }
        clear_outputs(machine);
        machine->outputs.aux_active = (argument != 0U);
        machine->state = machine->outputs.aux_active ?
            MW_STATE_COMMAND_PENDING : MW_STATE_ARMED;
        return true;
    case MW_CMD_PULSE_ISOLATED_OC:
    case MW_CMD_PULSE_LOW_SIDE:
        if ((argument == 0U) || ((uint32_t)argument > MW_MAX_OUTPUT_PULSE_MS)) {
            return false;
        }
        pulse_ms = (uint32_t)argument;
        clear_outputs(machine);
        machine->outputs.isolated_oc_active =
            (command == MW_CMD_PULSE_ISOLATED_OC);
        machine->outputs.low_side_active =
            (command == MW_CMD_PULSE_LOW_SIDE);
        machine->output_deadline_ms = now_ms + pulse_ms;
        machine->state = MW_STATE_COMMAND_PENDING;
        return true;
    case MW_CMD_DISARM:
    case MW_CMD_HEARTBEAT:
    case MW_CMD_ARM_LEASE:
    case MW_CMD_FEEDBACK:
    default:
        return false;
    }
}

bool mw_state_machine_take_disarm_request(mw_state_machine_t *machine)
{
    if ((machine == NULL) || (machine->role != MW_ROLE_WAND) ||
        (machine->pending_disarm_frames == 0U)) {
        return false;
    }
    machine->pending_disarm_frames--;
    return true;
}

bool mw_state_machine_outputs_safe(const mw_state_machine_t *machine)
{
    if (machine == NULL) {
        return true;
    }
    return !machine->outputs.aux_active &&
        !machine->outputs.isolated_oc_active &&
        !machine->outputs.low_side_active;
}
