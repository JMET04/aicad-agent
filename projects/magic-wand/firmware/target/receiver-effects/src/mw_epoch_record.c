#include "mw_epoch_record.h"

#include <string.h>

#define MW_EPOCH_MAGIC_0 ((uint8_t)'M')
#define MW_EPOCH_MAGIC_1 ((uint8_t)'W')
#define MW_EPOCH_MAGIC_2 ((uint8_t)'E')
#define MW_EPOCH_MAGIC_3 ((uint8_t)'P')
#define MW_EPOCH_CRC_OFFSET 28U
#define MW_EPOCH_CRC32_POLYNOMIAL UINT32_C(0xEDB88320)

static void zero_record(mw_epoch_record_t *record)
{
    if (record != NULL) {
        const mw_epoch_record_t zero = {0};
        *record = zero;
    }
}

static void put_u32_be(uint8_t *destination, uint32_t value)
{
    destination[0] = (uint8_t)(value >> 24U);
    destination[1] = (uint8_t)(value >> 16U);
    destination[2] = (uint8_t)(value >> 8U);
    destination[3] = (uint8_t)value;
}

static uint32_t get_u32_be(const uint8_t *source)
{
    return ((uint32_t)source[0] << 24U)
        | ((uint32_t)source[1] << 16U)
        | ((uint32_t)source[2] << 8U)
        | (uint32_t)source[3];
}

static uint32_t crc32_iso_hdlc(const uint8_t *data, size_t length)
{
    uint32_t crc = UINT32_MAX;
    size_t byte_index;

    for (byte_index = 0U; byte_index < length; ++byte_index) {
        unsigned int bit_index;
        crc ^= (uint32_t)data[byte_index];
        for (bit_index = 0U; bit_index < 8U; ++bit_index) {
            const uint32_t mask = 0U - (crc & 1U);
            crc = (crc >> 1U) ^ (MW_EPOCH_CRC32_POLYNOMIAL & mask);
        }
    }
    return ~crc;
}

static bool counter_is_active(uint32_t value)
{
    return (value != 0U) && (value != UINT32_MAX);
}

static bool identities_are_valid(uint32_t receiver_id, uint32_t wand_id)
{
    return (receiver_id != 0U)
        && (wand_id != 0U)
        && (receiver_id != wand_id);
}

static bool record_values_are_valid(const mw_epoch_record_t *record)
{
    if ((record == NULL)
        || (record->logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || (record->copy_index >= MW_EPOCH_SLOT_COUNT)
        || !counter_is_active(record->generation)
        || !identities_are_valid(record->receiver_id, record->wand_id)) {
        return false;
    }

    if (record->session_id == 0U) {
        return (record->generation == 1U)
            && (record->sequence_ceiling == 0U);
    }

    return counter_is_active(record->session_id)
        && counter_is_active(record->sequence_ceiling);
}

bool mw_epoch_record_encode(
    const mw_epoch_record_t *record,
    uint8_t encoded[MW_EPOCH_RECORD_ENCODED_SIZE]
)
{
    uint32_t crc;

    if (encoded == NULL) {
        return false;
    }
    (void)memset(encoded, 0, MW_EPOCH_RECORD_ENCODED_SIZE);
    if (!record_values_are_valid(record)) {
        return false;
    }

    encoded[0] = MW_EPOCH_MAGIC_0;
    encoded[1] = MW_EPOCH_MAGIC_1;
    encoded[2] = MW_EPOCH_MAGIC_2;
    encoded[3] = MW_EPOCH_MAGIC_3;
    encoded[4] = MW_EPOCH_RECORD_SCHEMA_V1;
    encoded[5] = record->logical_channel;
    encoded[6] = record->copy_index;
    encoded[7] = 0U;
    put_u32_be(&encoded[8], record->generation);
    put_u32_be(&encoded[12], record->receiver_id);
    put_u32_be(&encoded[16], record->wand_id);
    put_u32_be(&encoded[20], record->session_id);
    put_u32_be(&encoded[24], record->sequence_ceiling);
    crc = crc32_iso_hdlc(encoded, MW_EPOCH_CRC_OFFSET);
    put_u32_be(&encoded[MW_EPOCH_CRC_OFFSET], crc);
    return true;
}

bool mw_epoch_record_decode(
    const uint8_t *encoded,
    size_t encoded_length,
    mw_epoch_record_t *record
)
{
    mw_epoch_record_t decoded;
    uint32_t stored_crc;
    uint32_t computed_crc;

    zero_record(record);
    if ((encoded == NULL)
        || (record == NULL)
        || (encoded_length != MW_EPOCH_RECORD_ENCODED_SIZE)) {
        return false;
    }
    if ((encoded[0] != MW_EPOCH_MAGIC_0)
        || (encoded[1] != MW_EPOCH_MAGIC_1)
        || (encoded[2] != MW_EPOCH_MAGIC_2)
        || (encoded[3] != MW_EPOCH_MAGIC_3)
        || (encoded[4] != MW_EPOCH_RECORD_SCHEMA_V1)
        || (encoded[7] != 0U)) {
        return false;
    }

    stored_crc = get_u32_be(&encoded[MW_EPOCH_CRC_OFFSET]);
    computed_crc = crc32_iso_hdlc(encoded, MW_EPOCH_CRC_OFFSET);
    if (stored_crc != computed_crc) {
        return false;
    }

    decoded.logical_channel = encoded[5];
    decoded.copy_index = encoded[6];
    decoded.generation = get_u32_be(&encoded[8]);
    decoded.receiver_id = get_u32_be(&encoded[12]);
    decoded.wand_id = get_u32_be(&encoded[16]);
    decoded.session_id = get_u32_be(&encoded[20]);
    decoded.sequence_ceiling = get_u32_be(&encoded[24]);
    if (!record_values_are_valid(&decoded)) {
        return false;
    }

    *record = decoded;
    return true;
}

bool mw_epoch_record_make_factory_baseline(
    uint8_t logical_channel,
    uint8_t copy_index,
    uint32_t receiver_id,
    uint32_t wand_id,
    mw_epoch_record_t *record
)
{
    mw_epoch_record_t baseline;

    zero_record(record);
    if (record == NULL) {
        return false;
    }
    baseline.logical_channel = logical_channel;
    baseline.copy_index = copy_index;
    baseline.generation = 1U;
    baseline.receiver_id = receiver_id;
    baseline.wand_id = wand_id;
    baseline.session_id = 0U;
    baseline.sequence_ceiling = 0U;
    if (!record_values_are_valid(&baseline)) {
        return false;
    }
    *record = baseline;
    return true;
}

bool mw_epoch_record_prepare_next(
    const mw_epoch_record_t *current,
    uint32_t next_session_id,
    uint32_t sequence_ceiling,
    mw_epoch_record_t *next
)
{
    mw_epoch_record_t candidate;

    zero_record(next);
    if ((next == NULL)
        || !record_values_are_valid(current)
        || !counter_is_active(next_session_id)
        || !counter_is_active(sequence_ceiling)
        || (current->generation >= (UINT32_MAX - 1U))
        || (next_session_id <= current->session_id)) {
        return false;
    }

    candidate.logical_channel = current->logical_channel;
    candidate.copy_index = (uint8_t)(1U - current->copy_index);
    candidate.generation = current->generation + 1U;
    candidate.receiver_id = current->receiver_id;
    candidate.wand_id = current->wand_id;
    candidate.session_id = next_session_id;
    candidate.sequence_ceiling = sequence_ceiling;
    if (!record_values_are_valid(&candidate)) {
        return false;
    }
    *next = candidate;
    return true;
}

static bool slot_view_contract_is_valid(const mw_epoch_slot_view_t *slot)
{
    if (slot->state == MW_EPOCH_SLOT_PRESENT) {
        return slot->data != NULL;
    }
    if ((slot->state == MW_EPOCH_SLOT_ENOENT)
        || (slot->state == MW_EPOCH_SLOT_IO_ERROR)) {
        return (slot->data == NULL) && (slot->length == 0U);
    }
    return false;
}

mw_epoch_select_result_t mw_epoch_record_select(
    const mw_epoch_slot_view_t slots[MW_EPOCH_SLOT_COUNT],
    uint8_t expected_logical_channel,
    uint32_t expected_receiver_id,
    uint32_t expected_wand_id,
    mw_epoch_provisioning_policy_t provisioning_policy,
    mw_epoch_record_t *selected
)
{
    mw_epoch_record_t decoded[MW_EPOCH_SLOT_COUNT] = {0};
    unsigned int present_count = 0U;
    unsigned int slot_index;

    zero_record(selected);
    if ((slots == NULL)
        || (selected == NULL)
        || (expected_logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || !identities_are_valid(expected_receiver_id, expected_wand_id)
        || ((provisioning_policy != MW_EPOCH_REQUIRE_EXISTING)
            && (provisioning_policy != MW_EPOCH_ALLOW_EXPLICIT_PROVISIONING))) {
        return MW_EPOCH_SELECT_INVALID_ARGUMENT;
    }

    /* Validate both views and give any backend I/O error global precedence. */
    for (slot_index = 0U; slot_index < MW_EPOCH_SLOT_COUNT; ++slot_index) {
        if (!slot_view_contract_is_valid(&slots[slot_index])) {
            return MW_EPOCH_SELECT_INVALID_ARGUMENT;
        }
    }
    for (slot_index = 0U; slot_index < MW_EPOCH_SLOT_COUNT; ++slot_index) {
        if (slots[slot_index].state == MW_EPOCH_SLOT_IO_ERROR) {
            return MW_EPOCH_SELECT_IO_ERROR;
        }
    }

    for (slot_index = 0U; slot_index < MW_EPOCH_SLOT_COUNT; ++slot_index) {
        const mw_epoch_slot_view_t *slot = &slots[slot_index];
        if (slot->state == MW_EPOCH_SLOT_ENOENT) {
            continue;
        }
        if (!mw_epoch_record_decode(slot->data, slot->length, &decoded[slot_index])
            || (decoded[slot_index].copy_index != (uint8_t)slot_index)
            || (decoded[slot_index].logical_channel != expected_logical_channel)
            || (decoded[slot_index].receiver_id != expected_receiver_id)
            || (decoded[slot_index].wand_id != expected_wand_id)) {
            return MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT;
        }
        ++present_count;
    }

    if (present_count == 0U) {
        if (provisioning_policy == MW_EPOCH_ALLOW_EXPLICIT_PROVISIONING) {
            return MW_EPOCH_SELECT_PROVISIONING_REQUIRED;
        }
        return MW_EPOCH_SELECT_NOT_FOUND;
    }
    if (present_count == 1U) {
        *selected = (slots[0].state == MW_EPOCH_SLOT_PRESENT)
            ? decoded[0]
            : decoded[1];
        return MW_EPOCH_SELECT_OK;
    }

    if (decoded[0].generation == decoded[1].generation) {
        return MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT;
    }
    {
        const mw_epoch_record_t *newer = (decoded[0].generation > decoded[1].generation)
            ? &decoded[0]
            : &decoded[1];
        const mw_epoch_record_t *older = (newer == &decoded[0])
            ? &decoded[1]
            : &decoded[0];
        if ((older->generation >= (UINT32_MAX - 1U))
            || (newer->generation != (older->generation + 1U))
            || (newer->session_id <= older->session_id)) {
            return MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT;
        }
        *selected = *newer;
    }
    return MW_EPOCH_SELECT_OK;
}
