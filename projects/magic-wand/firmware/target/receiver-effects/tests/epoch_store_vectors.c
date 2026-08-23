#include "mw_epoch_store.h"

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

typedef struct {
    mw_epoch_slot_state_t state[MW_EPOCH_LOGICAL_CHANNEL_COUNT][MW_EPOCH_SLOT_COUNT];
    uint8_t data[MW_EPOCH_LOGICAL_CHANNEL_COUNT][MW_EPOCH_SLOT_COUNT]
        [MW_EPOCH_RECORD_ENCODED_SIZE];
    size_t length[MW_EPOCH_LOGICAL_CHANNEL_COUNT][MW_EPOCH_SLOT_COUNT];
    bool force_io[MW_EPOCH_LOGICAL_CHANNEL_COUNT][MW_EPOCH_SLOT_COUNT];
    bool override_length[MW_EPOCH_LOGICAL_CHANNEL_COUNT][MW_EPOCH_SLOT_COUNT];
    size_t reported_length[MW_EPOCH_LOGICAL_CHANNEL_COUNT][MW_EPOCH_SLOT_COUNT];
    bool corrupt_read[MW_EPOCH_LOGICAL_CHANNEL_COUNT][MW_EPOCH_SLOT_COUNT];
    uint8_t corrupt_byte[MW_EPOCH_LOGICAL_CHANNEL_COUNT][MW_EPOCH_SLOT_COUNT];
    int32_t next_write_result;
    bool store_on_full_write;
    unsigned int read_calls[MW_EPOCH_LOGICAL_CHANNEL_COUNT];
    unsigned int write_calls[MW_EPOCH_LOGICAL_CHANNEL_COUNT];
} fake_backend_t;

static void fake_reset(fake_backend_t *fake)
{
    unsigned int channel;
    unsigned int copy_index;
    (void)memset(fake, 0, sizeof(*fake));
    for (channel = 0U; channel < MW_EPOCH_LOGICAL_CHANNEL_COUNT; ++channel) {
        for (copy_index = 0U; copy_index < MW_EPOCH_SLOT_COUNT; ++copy_index) {
            fake->state[channel][copy_index] = MW_EPOCH_SLOT_ENOENT;
        }
    }
    fake->next_write_result = (int32_t)MW_EPOCH_RECORD_ENCODED_SIZE;
    fake->store_on_full_write = true;
}

static mw_epoch_slot_state_t fake_read_slot(
    void *context,
    uint8_t logical_channel,
    uint8_t copy_index,
    uint8_t data_out[MW_EPOCH_RECORD_ENCODED_SIZE],
    size_t *stored_length_out
)
{
    fake_backend_t *fake = (fake_backend_t *)context;
    mw_epoch_slot_state_t state;
    size_t copy_length;

    if ((fake == NULL)
        || (logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || (copy_index >= MW_EPOCH_SLOT_COUNT)
        || (data_out == NULL)
        || (stored_length_out == NULL)) {
        return MW_EPOCH_SLOT_IO_ERROR;
    }
    ++fake->read_calls[logical_channel];
    if (fake->force_io[logical_channel][copy_index]) {
        *stored_length_out = 0U;
        return MW_EPOCH_SLOT_IO_ERROR;
    }
    state = fake->state[logical_channel][copy_index];
    if (state != MW_EPOCH_SLOT_PRESENT) {
        *stored_length_out = 0U;
        return state;
    }

    copy_length = fake->length[logical_channel][copy_index];
    if (copy_length > MW_EPOCH_RECORD_ENCODED_SIZE) {
        copy_length = MW_EPOCH_RECORD_ENCODED_SIZE;
    }
    (void)memcpy(data_out, fake->data[logical_channel][copy_index], copy_length);
    *stored_length_out = fake->override_length[logical_channel][copy_index]
        ? fake->reported_length[logical_channel][copy_index]
        : fake->length[logical_channel][copy_index];
    if (fake->corrupt_read[logical_channel][copy_index]
        && (fake->corrupt_byte[logical_channel][copy_index] < copy_length)) {
        data_out[fake->corrupt_byte[logical_channel][copy_index]] ^= 1U;
    }
    return state;
}

static int32_t fake_write_slot(
    void *context,
    uint8_t logical_channel,
    uint8_t copy_index,
    const uint8_t *data,
    size_t data_length
)
{
    fake_backend_t *fake = (fake_backend_t *)context;
    int32_t result;

    if ((fake == NULL)
        || (logical_channel >= MW_EPOCH_LOGICAL_CHANNEL_COUNT)
        || (copy_index >= MW_EPOCH_SLOT_COUNT)
        || (data == NULL)
        || (data_length != MW_EPOCH_RECORD_ENCODED_SIZE)) {
        return -1;
    }
    ++fake->write_calls[logical_channel];
    result = fake->next_write_result;
    if ((result == (int32_t)MW_EPOCH_RECORD_ENCODED_SIZE)
        && fake->store_on_full_write) {
        (void)memcpy(fake->data[logical_channel][copy_index], data, data_length);
        fake->length[logical_channel][copy_index] = data_length;
        fake->state[logical_channel][copy_index] = MW_EPOCH_SLOT_PRESENT;
    }
    return result;
}

static mw_epoch_store_backend_t make_backend(fake_backend_t *fake)
{
    mw_epoch_store_backend_t backend;
    backend.read_slot = fake_read_slot;
    backend.write_slot = fake_write_slot;
    backend.context = fake;
    return backend;
}

static mw_epoch_record_t make_active(
    uint8_t channel,
    uint8_t copy_index,
    uint32_t generation,
    uint32_t receiver_id,
    uint32_t wand_id,
    uint32_t session_id,
    uint32_t ceiling
)
{
    mw_epoch_record_t record;
    record.logical_channel = channel;
    record.copy_index = copy_index;
    record.generation = generation;
    record.receiver_id = receiver_id;
    record.wand_id = wand_id;
    record.session_id = session_id;
    record.sequence_ceiling = ceiling;
    return record;
}

static bool seed_record(fake_backend_t *fake, const mw_epoch_record_t *record)
{
    if (!mw_epoch_record_encode(
            record,
            fake->data[record->logical_channel][record->copy_index])) {
        return false;
    }
    fake->length[record->logical_channel][record->copy_index] =
        MW_EPOCH_RECORD_ENCODED_SIZE;
    fake->state[record->logical_channel][record->copy_index] =
        MW_EPOCH_SLOT_PRESENT;
    return true;
}

static int new_provisioned_store(
    fake_backend_t *fake,
    mw_epoch_store_t *store
)
{
    mw_epoch_store_backend_t backend;
    fake_reset(fake);
    backend = make_backend(fake);
    CHECK(mw_epoch_store_init(store, &backend));
    CHECK(mw_epoch_store_load_channel(
        store, 0U, 11U, 21U, 1000U,
        MW_EPOCH_ALLOW_EXPLICIT_PROVISIONING)
        == MW_EPOCH_STORE_PROVISIONING_REQUIRED);
    CHECK(mw_epoch_store_provision_channel(store, 0U) == MW_EPOCH_STORE_OK);
    return 0;
}

static int check_provision_commit_and_callback(void)
{
    fake_backend_t fake;
    mw_epoch_store_t store;
    mw_epoch_store_backend_t backend;
    mw_epoch_store_channel_context_t callback_context;
    mw_epoch_record_t snapshot;

    fake_reset(&fake);
    backend = make_backend(&fake);
    CHECK(mw_epoch_store_init(&store, &backend));
    CHECK(mw_epoch_store_load_channel(
        &store, 0U, 11U, 21U, 1000U, MW_EPOCH_REQUIRE_EXISTING)
        == MW_EPOCH_STORE_NOT_FOUND);
    CHECK(!mw_epoch_store_channel_ready(&store, 0U));
    CHECK(mw_epoch_store_load_channel(
        &store, 0U, 11U, 21U, 1000U,
        MW_EPOCH_ALLOW_EXPLICIT_PROVISIONING)
        == MW_EPOCH_STORE_PROVISIONING_REQUIRED);
    CHECK(mw_epoch_store_provision_channel(&store, 0U) == MW_EPOCH_STORE_OK);
    CHECK(mw_epoch_store_snapshot(&store, 0U, &snapshot));
    CHECK(snapshot.generation == 1U);
    CHECK(snapshot.session_id == 0U);
    CHECK(snapshot.sequence_ceiling == 0U);

    CHECK(mw_epoch_store_commit_session(&store, 0U, 10U) == MW_EPOCH_STORE_OK);
    CHECK(mw_epoch_store_snapshot(&store, 0U, &snapshot));
    CHECK(snapshot.copy_index == 1U);
    CHECK(snapshot.generation == 2U);
    CHECK(snapshot.session_id == 10U);
    CHECK(snapshot.sequence_ceiling == 1000U);
    CHECK(fake.read_calls[0] >= 6U);

    CHECK(mw_epoch_store_channel_context_init(&callback_context, &store, 0U));
    CHECK(mw_epoch_store_commit_session_epoch(&callback_context, 11U));
    CHECK(mw_epoch_store_snapshot(&store, 0U, &snapshot));
    CHECK(snapshot.copy_index == 0U);
    CHECK(snapshot.generation == 3U);
    CHECK(snapshot.session_id == 11U);
    CHECK(!mw_epoch_store_commit_session_epoch(&callback_context, 11U));
    CHECK(mw_epoch_store_channel_ready(&store, 0U));
    return 0;
}

static int check_write_zero_idempotent_readback(void)
{
    fake_backend_t fake;
    mw_epoch_store_t store;
    mw_epoch_record_t baseline;
    mw_epoch_record_t candidate;
    mw_epoch_record_t snapshot;

    CHECK(new_provisioned_store(&fake, &store) == 0);
    CHECK(mw_epoch_store_snapshot(&store, 0U, &baseline));
    CHECK(mw_epoch_record_prepare_next(&baseline, 7U, 1000U, &candidate));
    CHECK(seed_record(&fake, &candidate));
    fake.next_write_result = 0;
    CHECK(mw_epoch_store_commit_session(&store, 0U, 7U) == MW_EPOCH_STORE_OK);
    CHECK(mw_epoch_store_snapshot(&store, 0U, &snapshot));
    CHECK(snapshot.session_id == 7U);
    CHECK(snapshot.generation == 2U);
    return 0;
}

static int check_transaction_failures(void)
{
    fake_backend_t fake;
    mw_epoch_store_t store;
    mw_epoch_store_t rebooted;
    mw_epoch_store_backend_t backend;
    mw_epoch_record_t conflict;
    mw_epoch_record_t snapshot;

    CHECK(new_provisioned_store(&fake, &store) == 0);
    fake.next_write_result = -5;
    CHECK(mw_epoch_store_commit_session(&store, 0U, 2U) == MW_EPOCH_STORE_IO_ERROR);
    CHECK(!mw_epoch_store_channel_ready(&store, 0U));

    CHECK(new_provisioned_store(&fake, &store) == 0);
    fake.next_write_result = 31;
    CHECK(mw_epoch_store_commit_session(&store, 0U, 2U)
        == MW_EPOCH_STORE_BACKEND_CONTRACT_ERROR);
    CHECK(!mw_epoch_store_channel_ready(&store, 0U));

    CHECK(new_provisioned_store(&fake, &store) == 0);
    fake.store_on_full_write = false;
    CHECK(mw_epoch_store_commit_session(&store, 0U, 2U)
        == MW_EPOCH_STORE_CORRUPT_OR_CONFLICT);
    CHECK(!mw_epoch_store_channel_ready(&store, 0U));

    CHECK(new_provisioned_store(&fake, &store) == 0);
    fake.override_length[0][1] = true;
    fake.reported_length[0][1] = 31U;
    CHECK(mw_epoch_store_commit_session(&store, 0U, 2U)
        == MW_EPOCH_STORE_CORRUPT_OR_CONFLICT);
    CHECK(!mw_epoch_store_channel_ready(&store, 0U));

    CHECK(new_provisioned_store(&fake, &store) == 0);
    fake.corrupt_read[0][1] = true;
    fake.corrupt_byte[0][1] = 12U;
    CHECK(mw_epoch_store_commit_session(&store, 0U, 2U)
        == MW_EPOCH_STORE_CORRUPT_OR_CONFLICT);
    CHECK(!mw_epoch_store_channel_ready(&store, 0U));
    /* The write may have persisted even though ACK is forbidden; reboot burns it. */
    fake.corrupt_read[0][1] = false;
    backend = make_backend(&fake);
    CHECK(mw_epoch_store_init(&rebooted, &backend));
    CHECK(mw_epoch_store_load_channel(
        &rebooted, 0U, 11U, 21U, 1000U, MW_EPOCH_REQUIRE_EXISTING)
        == MW_EPOCH_STORE_OK);
    CHECK(mw_epoch_store_snapshot(&rebooted, 0U, &snapshot));
    CHECK(snapshot.session_id == 2U);

    CHECK(new_provisioned_store(&fake, &store) == 0);
    fake.force_io[0][1] = true;
    CHECK(mw_epoch_store_commit_session(&store, 0U, 2U) == MW_EPOCH_STORE_IO_ERROR);
    CHECK(!mw_epoch_store_channel_ready(&store, 0U));

    CHECK(new_provisioned_store(&fake, &store) == 0);
    conflict = make_active(0U, 0U, 2U, 11U, 21U, 1U, 1000U);
    CHECK(seed_record(&fake, &conflict));
    CHECK(mw_epoch_store_commit_session(&store, 0U, 2U)
        == MW_EPOCH_STORE_CORRUPT_OR_CONFLICT);
    CHECK(!mw_epoch_store_channel_ready(&store, 0U));

    CHECK(new_provisioned_store(&fake, &store) == 0);
    fake.next_write_result = 0;
    CHECK(mw_epoch_store_commit_session(&store, 0U, 2U)
        == MW_EPOCH_STORE_CORRUPT_OR_CONFLICT);
    CHECK(!mw_epoch_store_channel_ready(&store, 0U));
    return 0;
}

static int check_interrupted_write_is_enoent_after_reboot(void)
{
    fake_backend_t fake;
    mw_epoch_store_t before_reset;
    mw_epoch_store_t after_reset;
    mw_epoch_store_backend_t backend;
    mw_epoch_record_t snapshot;

    CHECK(new_provisioned_store(&fake, &before_reset) == 0);
    /* Incomplete data has no valid NVS metadata, so slot B remains ENOENT. */
    CHECK(fake.state[0][1] == MW_EPOCH_SLOT_ENOENT);
    backend = make_backend(&fake);
    CHECK(mw_epoch_store_init(&after_reset, &backend));
    CHECK(mw_epoch_store_load_channel(
        &after_reset, 0U, 11U, 21U, 1000U, MW_EPOCH_REQUIRE_EXISTING)
        == MW_EPOCH_STORE_OK);
    CHECK(mw_epoch_store_snapshot(&after_reset, 0U, &snapshot));
    CHECK(snapshot.generation == 1U);
    CHECK(snapshot.session_id == 0U);
    CHECK(mw_epoch_store_commit_session(&after_reset, 0U, 5U)
        == MW_EPOCH_STORE_OK);
    return 0;
}

static int check_eight_channel_isolation(void)
{
    fake_backend_t fake;
    mw_epoch_store_t store;
    mw_epoch_store_backend_t backend;
    mw_epoch_record_t snapshot;
    unsigned int channel;

    fake_reset(&fake);
    backend = make_backend(&fake);
    CHECK(mw_epoch_store_init(&store, &backend));
    for (channel = 0U; channel < MW_EPOCH_LOGICAL_CHANNEL_COUNT; ++channel) {
        CHECK(mw_epoch_store_load_channel(
            &store,
            (uint8_t)channel,
            100U,
            200U + (uint32_t)channel,
            5000U,
            MW_EPOCH_ALLOW_EXPLICIT_PROVISIONING)
            == MW_EPOCH_STORE_PROVISIONING_REQUIRED);
        CHECK(mw_epoch_store_provision_channel(&store, (uint8_t)channel)
            == MW_EPOCH_STORE_OK);
    }

    for (channel = 0U; channel < MW_EPOCH_LOGICAL_CHANNEL_COUNT; ++channel) {
        fake.next_write_result = (channel == 3U)
            ? -5
            : (int32_t)MW_EPOCH_RECORD_ENCODED_SIZE;
        if (channel == 3U) {
            CHECK(mw_epoch_store_commit_session(
                &store, (uint8_t)channel, 10U + (uint32_t)channel)
                == MW_EPOCH_STORE_IO_ERROR);
        } else {
            CHECK(mw_epoch_store_commit_session(
                &store, (uint8_t)channel, 10U + (uint32_t)channel)
                == MW_EPOCH_STORE_OK);
        }
    }

    for (channel = 0U; channel < MW_EPOCH_LOGICAL_CHANNEL_COUNT; ++channel) {
        if (channel == 3U) {
            CHECK(!mw_epoch_store_channel_ready(&store, (uint8_t)channel));
        } else {
            CHECK(mw_epoch_store_channel_ready(&store, (uint8_t)channel));
            CHECK(mw_epoch_store_snapshot(&store, (uint8_t)channel, &snapshot));
            CHECK(snapshot.logical_channel == (uint8_t)channel);
            CHECK(snapshot.wand_id == 200U + (uint32_t)channel);
            CHECK(snapshot.session_id == 10U + (uint32_t)channel);
        }
        CHECK(fake.write_calls[channel] == 2U);
    }
    return 0;
}

static int check_io_precedence_and_failed_init(void)
{
    fake_backend_t fake;
    mw_epoch_store_t store;
    mw_epoch_store_backend_t backend;
    const mw_epoch_store_backend_t *alias_backend;
    mw_epoch_store_channel_context_t context;

    CHECK(new_provisioned_store(&fake, &store) == 0);
    alias_backend = &store.backend;
    CHECK(mw_epoch_store_init(&store, alias_backend));
    CHECK(store.initialized);
    CHECK(store.backend.read_slot == fake_read_slot);
    CHECK(store.backend.write_slot == fake_write_slot);
    CHECK(store.backend.context == &fake);
    CHECK(!mw_epoch_store_channel_ready(&store, 0U));
    CHECK(mw_epoch_store_load_channel(
        &store, 0U, 11U, 21U, 1000U, MW_EPOCH_REQUIRE_EXISTING)
        == MW_EPOCH_STORE_OK);

    fake.corrupt_read[0][0] = true;
    fake.corrupt_byte[0][0] = 0U;
    fake.force_io[0][1] = true;
    backend = make_backend(&fake);
    CHECK(mw_epoch_store_init(&store, &backend));
    CHECK(mw_epoch_store_load_channel(
        &store, 0U, 11U, 21U, 1000U, MW_EPOCH_REQUIRE_EXISTING)
        == MW_EPOCH_STORE_IO_ERROR);

    CHECK(!mw_epoch_store_init(&store, NULL));
    CHECK(!store.initialized);
    context.store = &store;
    context.logical_channel = 7U;
    CHECK(!mw_epoch_store_channel_context_init(&context, &store, 0U));
    CHECK(context.store == NULL);
    CHECK(context.logical_channel == 0U);
    return 0;
}

int main(void)
{
    CHECK(check_provision_commit_and_callback() == 0);
    CHECK(check_write_zero_idempotent_readback() == 0);
    CHECK(check_transaction_failures() == 0);
    CHECK(check_interrupted_write_is_enoent_after_reboot() == 0);
    CHECK(check_eight_channel_isolation() == 0);
    CHECK(check_io_precedence_and_failed_init() == 0);
    (void)puts("epoch store transaction vectors passed; ACK remains target-adapter gated");
    return 0;
}
