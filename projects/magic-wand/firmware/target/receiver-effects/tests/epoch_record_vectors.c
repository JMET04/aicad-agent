#include "mw_epoch_record.h"

#include <stdio.h>
#include <string.h>

#define CHECK(expression) \
    do { \
        if (!(expression)) { \
            (void)fprintf(stderr, "CHECK failed at %s:%d: %s\n", \
                __FILE__, __LINE__, #expression); \
            return 1; \
        } \
    } while (0)

static mw_epoch_record_t active_record(
    uint8_t channel,
    uint8_t copy_index,
    uint32_t generation,
    uint32_t receiver_id,
    uint32_t wand_id,
    uint32_t session_id,
    uint32_t sequence_ceiling
)
{
    mw_epoch_record_t record;
    record.logical_channel = channel;
    record.copy_index = copy_index;
    record.generation = generation;
    record.receiver_id = receiver_id;
    record.wand_id = wand_id;
    record.session_id = session_id;
    record.sequence_ceiling = sequence_ceiling;
    return record;
}

static bool records_equal(
    const mw_epoch_record_t *left,
    const mw_epoch_record_t *right
)
{
    return (left->logical_channel == right->logical_channel)
        && (left->copy_index == right->copy_index)
        && (left->generation == right->generation)
        && (left->receiver_id == right->receiver_id)
        && (left->wand_id == right->wand_id)
        && (left->session_id == right->session_id)
        && (left->sequence_ceiling == right->sequence_ceiling);
}

static bool record_is_zero(const mw_epoch_record_t *record)
{
    const mw_epoch_record_t zero = {0};
    return records_equal(record, &zero);
}

static void set_present(
    mw_epoch_slot_view_t *slot,
    const uint8_t *data,
    size_t length
)
{
    slot->state = MW_EPOCH_SLOT_PRESENT;
    slot->data = data;
    slot->length = length;
}

static void set_missing(mw_epoch_slot_view_t *slot)
{
    slot->state = MW_EPOCH_SLOT_ENOENT;
    slot->data = NULL;
    slot->length = 0U;
}

static void set_io_error(mw_epoch_slot_view_t *slot)
{
    slot->state = MW_EPOCH_SLOT_IO_ERROR;
    slot->data = NULL;
    slot->length = 0U;
}

static int check_canonical_encoding_and_crc(void)
{
    const mw_epoch_record_t source = active_record(
        3U, 0U, 2U, UINT32_C(0x11223344), UINT32_C(0x55667788),
        9U, UINT32_MAX - 1U
    );
    const uint8_t expected[MW_EPOCH_RECORD_ENCODED_SIZE] = {
        0x4dU, 0x57U, 0x45U, 0x50U, 0x01U, 0x03U, 0x00U, 0x00U,
        0x00U, 0x00U, 0x00U, 0x02U, 0x11U, 0x22U, 0x33U, 0x44U,
        0x55U, 0x66U, 0x77U, 0x88U, 0x00U, 0x00U, 0x00U, 0x09U,
        0xffU, 0xffU, 0xffU, 0xfeU, 0xb3U, 0xd7U, 0x35U, 0x49U
    };
    uint8_t encoded[MW_EPOCH_RECORD_ENCODED_SIZE];
    uint8_t damaged[MW_EPOCH_RECORD_ENCODED_SIZE];
    mw_epoch_record_t decoded;
    size_t byte_index;

    CHECK(mw_epoch_record_encode(&source, encoded));
    for (byte_index = 0U; byte_index < sizeof(expected); ++byte_index) {
        CHECK(encoded[byte_index] == expected[byte_index]);
    }
    CHECK(mw_epoch_record_decode(encoded, sizeof(encoded), &decoded));
    CHECK(records_equal(&source, &decoded));
    CHECK(!mw_epoch_record_decode(encoded, sizeof(encoded) - 1U, &decoded));
    CHECK(record_is_zero(&decoded));
    CHECK(!mw_epoch_record_decode(encoded, sizeof(encoded) + 1U, &decoded));
    CHECK(!mw_epoch_record_decode(NULL, sizeof(encoded), &decoded));
    CHECK(!mw_epoch_record_decode(encoded, sizeof(encoded), NULL));

    for (byte_index = 0U; byte_index < sizeof(encoded); ++byte_index) {
        unsigned int bit_index;
        for (bit_index = 0U; bit_index < 8U; ++bit_index) {
            (void)memcpy(damaged, encoded, sizeof(damaged));
            damaged[byte_index] ^= (uint8_t)(1U << bit_index);
            CHECK(!mw_epoch_record_decode(damaged, sizeof(damaged), &decoded));
            CHECK(record_is_zero(&decoded));
        }
    }
    return 0;
}

static int check_record_bounds_and_next(void)
{
    const mw_epoch_record_t valid = active_record(2U, 0U, 7U, 41U, 51U, 10U, 100U);
    mw_epoch_record_t changed;
    mw_epoch_record_t baseline;
    mw_epoch_record_t next;
    uint8_t encoded[MW_EPOCH_RECORD_ENCODED_SIZE];

    changed = valid;
    changed.logical_channel = MW_EPOCH_LOGICAL_CHANNEL_COUNT;
    CHECK(!mw_epoch_record_encode(&changed, encoded));
    changed = valid;
    changed.copy_index = MW_EPOCH_SLOT_COUNT;
    CHECK(!mw_epoch_record_encode(&changed, encoded));
    changed = valid;
    changed.generation = 0U;
    CHECK(!mw_epoch_record_encode(&changed, encoded));
    changed.generation = UINT32_MAX;
    CHECK(!mw_epoch_record_encode(&changed, encoded));
    changed = valid;
    changed.receiver_id = 0U;
    CHECK(!mw_epoch_record_encode(&changed, encoded));
    changed = valid;
    changed.wand_id = 0U;
    CHECK(!mw_epoch_record_encode(&changed, encoded));
    changed = valid;
    changed.wand_id = changed.receiver_id;
    CHECK(!mw_epoch_record_encode(&changed, encoded));
    changed = valid;
    changed.session_id = UINT32_MAX;
    CHECK(!mw_epoch_record_encode(&changed, encoded));
    changed = valid;
    changed.sequence_ceiling = 0U;
    CHECK(!mw_epoch_record_encode(&changed, encoded));
    changed.sequence_ceiling = UINT32_MAX;
    CHECK(!mw_epoch_record_encode(&changed, encoded));
    changed = valid;
    changed.session_id = 0U;
    CHECK(!mw_epoch_record_encode(&changed, encoded));

    CHECK(mw_epoch_record_make_factory_baseline(2U, 0U, 41U, 51U, &baseline));
    CHECK(baseline.generation == 1U);
    CHECK(baseline.session_id == 0U);
    CHECK(baseline.sequence_ceiling == 0U);
    CHECK(mw_epoch_record_encode(&baseline, encoded));
    CHECK(!mw_epoch_record_make_factory_baseline(8U, 0U, 41U, 51U, &next));
    CHECK(!mw_epoch_record_make_factory_baseline(2U, 2U, 41U, 51U, &next));
    CHECK(!mw_epoch_record_make_factory_baseline(2U, 0U, 41U, 41U, &next));

    CHECK(mw_epoch_record_prepare_next(&baseline, 10U, UINT32_MAX - 1U, &next));
    CHECK(next.copy_index == 1U);
    CHECK(next.generation == 2U);
    CHECK(next.session_id == 10U);
    CHECK(!mw_epoch_record_prepare_next(&next, 10U, 20U, &changed));
    CHECK(!mw_epoch_record_prepare_next(&next, 9U, 20U, &changed));
    CHECK(!mw_epoch_record_prepare_next(&next, UINT32_MAX, 20U, &changed));
    CHECK(!mw_epoch_record_prepare_next(&next, 11U, 0U, &changed));
    CHECK(!mw_epoch_record_prepare_next(&next, 11U, UINT32_MAX, &changed));
    changed = next;
    changed.generation = UINT32_MAX - 1U;
    CHECK(!mw_epoch_record_prepare_next(&changed, 11U, 20U, &baseline));
    return 0;
}

static int check_selection_matrix(void)
{
    const uint8_t channel = 2U;
    const uint32_t receiver_id = 41U;
    const uint32_t wand_id = 51U;
    mw_epoch_record_t a = active_record(channel, 0U, 2U, receiver_id, wand_id, 10U, 100U);
    mw_epoch_record_t b = active_record(channel, 1U, 3U, receiver_id, wand_id, 11U, 100U);
    mw_epoch_record_t changed;
    mw_epoch_record_t selected;
    uint8_t encoded_a[MW_EPOCH_RECORD_ENCODED_SIZE];
    uint8_t encoded_b[MW_EPOCH_RECORD_ENCODED_SIZE];
    mw_epoch_slot_view_t slots[MW_EPOCH_SLOT_COUNT];

    CHECK(mw_epoch_record_encode(&a, encoded_a));
    CHECK(mw_epoch_record_encode(&b, encoded_b));
    set_present(&slots[0], encoded_a, sizeof(encoded_a));
    set_present(&slots[1], encoded_b, sizeof(encoded_b));
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_OK);
    CHECK(records_equal(&selected, &b));

    set_missing(&slots[1]);
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_OK);
    CHECK(records_equal(&selected, &a));

    set_missing(&slots[0]);
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_NOT_FOUND);
    CHECK(record_is_zero(&selected));
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_ALLOW_EXPLICIT_PROVISIONING, &selected)
        == MW_EPOCH_SELECT_PROVISIONING_REQUIRED);
    CHECK(record_is_zero(&selected));

    set_present(&slots[0], encoded_a, sizeof(encoded_a));
    set_io_error(&slots[1]);
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_IO_ERROR);
    CHECK(record_is_zero(&selected));

    set_present(&slots[0], encoded_a, 1U);
    set_io_error(&slots[1]);
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_IO_ERROR);
    CHECK(record_is_zero(&selected));

    set_missing(&slots[1]);
    slots[1].data = encoded_b;
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_INVALID_ARGUMENT);
    CHECK(record_is_zero(&selected));

    set_present(&slots[0], encoded_a, sizeof(encoded_a));
    set_present(&slots[1], encoded_b, sizeof(encoded_b));
    changed = b;
    changed.generation = a.generation;
    CHECK(mw_epoch_record_encode(&changed, encoded_b));
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT);
    changed = b;
    changed.generation = a.generation + 2U;
    CHECK(mw_epoch_record_encode(&changed, encoded_b));
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT);
    changed = b;
    changed.session_id = a.session_id;
    CHECK(mw_epoch_record_encode(&changed, encoded_b));
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT);

    changed = a;
    changed.copy_index = 1U;
    CHECK(mw_epoch_record_encode(&changed, encoded_a));
    set_missing(&slots[1]);
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT);
    CHECK(record_is_zero(&selected));

    CHECK(mw_epoch_record_encode(&a, encoded_a));
    changed = b;
    changed.receiver_id = receiver_id + 1U;
    CHECK(mw_epoch_record_encode(&changed, encoded_b));
    set_present(&slots[0], encoded_a, sizeof(encoded_a));
    set_present(&slots[1], encoded_b, sizeof(encoded_b));
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT);

    CHECK(mw_epoch_record_select(NULL, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_INVALID_ARGUMENT);
    CHECK(mw_epoch_record_select(slots, 8U, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_INVALID_ARGUMENT);
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, receiver_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_INVALID_ARGUMENT);
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        (mw_epoch_provisioning_policy_t)99, &selected) == MW_EPOCH_SELECT_INVALID_ARGUMENT);
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, NULL) == MW_EPOCH_SELECT_INVALID_ARGUMENT);
    return 0;
}

static int check_interrupted_write_mapping(void)
{
    const uint8_t channel = 4U;
    const uint32_t receiver_id = 71U;
    const uint32_t wand_id = 81U;
    const mw_epoch_record_t old_record = active_record(
        channel, 0U, 8U, receiver_id, wand_id, 100U, UINT32_MAX - 1U
    );
    const mw_epoch_record_t new_record = active_record(
        channel, 1U, 9U, receiver_id, wand_id, 101U, UINT32_MAX - 1U
    );
    uint8_t old_encoded[MW_EPOCH_RECORD_ENCODED_SIZE];
    uint8_t new_encoded[MW_EPOCH_RECORD_ENCODED_SIZE];
    uint8_t damaged[MW_EPOCH_RECORD_ENCODED_SIZE];
    mw_epoch_slot_view_t slots[MW_EPOCH_SLOT_COUNT];
    mw_epoch_record_t selected;
    size_t cut;

    CHECK(mw_epoch_record_encode(&old_record, old_encoded));
    CHECK(mw_epoch_record_encode(&new_record, new_encoded));
    set_present(&slots[0], old_encoded, sizeof(old_encoded));

    /*
     * Zephyr NVS writes data before metadata. A reset before valid metadata makes
     * the incomplete entry invisible after mount, so the adapter must report
     * ENOENT, never a short PRESENT record. The old committed epoch remains safe.
     */
    for (cut = 0U; cut < sizeof(new_encoded); ++cut) {
        set_missing(&slots[1]);
        CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
            MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_OK);
        CHECK(records_equal(&selected, &old_record));

        set_present(&slots[1], new_encoded, cut);
        CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
            MW_EPOCH_REQUIRE_EXISTING, &selected)
            == MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT);
        CHECK(record_is_zero(&selected));
    }

    set_present(&slots[1], new_encoded, sizeof(new_encoded));
    CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
        MW_EPOCH_REQUIRE_EXISTING, &selected) == MW_EPOCH_SELECT_OK);
    CHECK(records_equal(&selected, &new_record));

    /* A malformed PRESENT never rolls back a previously acknowledged epoch. */
    for (cut = 0U; cut < sizeof(new_encoded); ++cut) {
        unsigned int bit_index;
        for (bit_index = 0U; bit_index < 8U; ++bit_index) {
            (void)memcpy(damaged, new_encoded, sizeof(damaged));
            damaged[cut] ^= (uint8_t)(1U << bit_index);
            set_present(&slots[1], damaged, sizeof(damaged));
            CHECK(mw_epoch_record_select(slots, channel, receiver_id, wand_id,
                MW_EPOCH_REQUIRE_EXISTING, &selected)
                == MW_EPOCH_SELECT_CORRUPT_OR_CONFLICT);
            CHECK(record_is_zero(&selected));
        }
    }
    return 0;
}

int main(void)
{
    CHECK(check_canonical_encoding_and_crc() == 0);
    CHECK(check_record_bounds_and_next() == 0);
    CHECK(check_selection_matrix() == 0);
    CHECK(check_interrupted_write_mapping() == 0);
    (void)puts("epoch record codec vectors passed; Zephyr NVS adapter/HIL gates remain open");
    return 0;
}
