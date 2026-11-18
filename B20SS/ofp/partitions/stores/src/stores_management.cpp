#include <fmofp/stores/stores_management.hpp>

#include <algorithm>
#include <numeric>

namespace fmofp::stores {

namespace {

using icd::StoreKind;
using icd::StoreState;
using icd::TerminalState;

bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

// A store still on its station: what the load counts and what a jettison drops.
bool carried(StoreState s) noexcept {
    return s != StoreState::EMPTY && s != StoreState::EXPENDED && s != StoreState::JETTISONED;
}

void put_station(icd::SmsStatus& s, std::size_t index, const Station& st) noexcept {
    switch (index) {
        case 0:
            s.station_1_kind = st.kind;
            s.station_1_state = st.state;
            s.station_1_qty = st.qty;
            break;
        case 1:
            s.station_2_kind = st.kind;
            s.station_2_state = st.state;
            s.station_2_qty = st.qty;
            break;
        case 2:
            s.station_3_kind = st.kind;
            s.station_3_state = st.state;
            s.station_3_qty = st.qty;
            break;
        case 3:
            s.station_4_kind = st.kind;
            s.station_4_state = st.state;
            s.station_4_qty = st.qty;
            break;
        case 4:
            s.station_5_kind = st.kind;
            s.station_5_state = st.state;
            s.station_5_qty = st.qty;
            break;
        case 5:
            s.station_6_kind = st.kind;
            s.station_6_state = st.state;
            s.station_6_qty = st.qty;
            break;
        case 6:
            s.station_7_kind = st.kind;
            s.station_7_state = st.state;
            s.station_7_qty = st.qty;
            break;
        case 7:
            s.station_8_kind = st.kind;
            s.station_8_state = st.state;
            s.station_8_qty = st.qty;
            break;
        case 8:
            s.station_9_kind = st.kind;
            s.station_9_state = st.state;
            s.station_9_qty = st.qty;
            break;
        case 9:
            s.station_10_kind = st.kind;
            s.station_10_state = st.state;
            s.station_10_qty = st.qty;
            break;
        case 10:
            s.station_11_kind = st.kind;
            s.station_11_state = st.state;
            s.station_11_qty = st.qty;
            break;
        default:
            break;
    }
}

}  // namespace

Loadout default_loadout() noexcept {
    // _build_default_loadout: the left bay (1-4), the right bay (5-8), the wingtip decoys (9-10), the ECM pod (11).
    return Loadout{{
        {StoreKind::MK_82, StoreState::ARMED, 4},
        {StoreKind::JDAM, StoreState::SAFE, 2},
        {StoreKind::JASSM, StoreState::SAFE, 1},
        {StoreKind::MK_82, StoreState::EMPTY, 0},
        {StoreKind::MK_82, StoreState::ARMED, 4},
        {StoreKind::JDAM, StoreState::SAFE, 2},
        {StoreKind::JASSM, StoreState::SAFE, 1},
        {StoreKind::MK_82, StoreState::EMPTY, 0},
        {StoreKind::ALE_55, StoreState::READY, 8},
        {StoreKind::ALE_55, StoreState::READY, 8},
        {StoreKind::AN_ALQ, StoreState::READY, 1},
    }};
}

double unit_weight_kg(StoreKind kind) noexcept {
    switch (kind) {
        case StoreKind::MK_82:
            return 227.0;
        case StoreKind::JDAM:
            return 910.0;
        case StoreKind::JASSM:
            return 1021.0;
        case StoreKind::ALE_55:
            return 8.0;
        case StoreKind::AN_ALQ:
            return 180.0;
        case StoreKind::NONE:
        default:
            return 0.0;
    }
}

bool is_weapon(StoreKind kind) noexcept {
    return kind == StoreKind::MK_82 || kind == StoreKind::JDAM || kind == StoreKind::JASSM;
}

icd::MasterArm master_arm_from(const icd::FmsStatus* fms) noexcept {
    if (fms == nullptr) {
        return icd::MasterArm::SAFE;  // the feed gives no tactical systems: weapons "SAFE"
    }
    switch (fms->weapons) {
        case icd::WeaponsState::ARMED:
            return icd::MasterArm::ARMED;
        case icd::WeaponsState::READY:
            return icd::MasterArm::TRAIN;
        case icd::WeaponsState::SAFE:
        default:
            return icd::MasterArm::SAFE;
    }
}

double total_weight_kg(const Loadout& loadout) noexcept {
    // The quirk kept: a carried store with no quantity left weighs one unit (max(qty, 1)).
    return std::accumulate(loadout.begin(), loadout.end(), 0.0, [](double total, const Station& st) {
        if (st.kind == StoreKind::NONE || !carried(st.state)) {
            return total;
        }
        return total + unit_weight_kg(st.kind) * static_cast<double>(std::max<std::uint8_t>(st.qty, 1U));
    });
}

unsigned armed_count(const Loadout& loadout) noexcept {
    return static_cast<unsigned>(std::count_if(loadout.begin(), loadout.end(), [](const Station& st) {
        return st.kind != StoreKind::NONE && st.state == StoreState::ARMED;
    }));
}

Status StoresManagement::init() noexcept {
    loadout_ = default_loadout();
    master_arm_ = icd::MasterArm::SAFE;
    release_mode_ = icd::ReleaseMode::SINGLE;
    delivery_mode_ = icd::DeliveryMode::AUTO;
    selected_ = 1;
    released_ = 0;
    jettisoned_ = false;
    fms_ = icd::FmsStatus{};
    have_fms_ = false;
    fms_frame_ = 0;
    frame_ = 0;
    cmd_status_ = icd::CmdStatus::NONE;
    status_ = icd::SmsStatus{};
    status_.state = TerminalState::INITIALIZING;
    status_.healthy = true;
    self_test_started_ = 0;
    self_test_running_ = false;
    bit_ = bus::BitWord{};
    mode_seq_ = bus::CommandSequence{};
    cmd_seq_ = bus::CommandSequence{};
    fill_status();
    return Status::kOk;
}

void StoresManagement::reset() noexcept { (void)init(); }

void StoresManagement::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

void StoresManagement::set_master_arm(icd::MasterArm arm) noexcept {
    master_arm_ = arm;
    fill_status();
}

bool StoresManagement::fms_fresh(std::uint32_t frame) const noexcept {
    return have_fms_ && frame >= fms_frame_ && frame - fms_frame_ < kFmsStaleFrames;
}

void StoresManagement::step(const icd::FmsStatus* fms, std::uint32_t frame) noexcept {
    frame_ = frame;
    if (fms != nullptr) {
        fms_ = *fms;
        have_fms_ = true;
        fms_frame_ = frame;
    }
    const bool fresh = fms_fresh(frame);
    master_arm_ = master_arm_from(fresh ? &fms_ : nullptr);

    if (self_test_running_) {
        if (self_test_started_ == 0) {
            self_test_started_ = frame == 0 ? 1 : frame;
        } else if (frame - self_test_started_ >= kSelfTestFrames) {
            self_test_running_ = false;
            self_test_started_ = 0;
            bit_.in_progress = false;
        }
    }
    if (status_.state == TerminalState::INITIALIZING && fresh) {
        status_.state = TerminalState::NORMAL;
    } else if (status_.state == TerminalState::NORMAL && !fresh) {
        status_.state = TerminalState::DEGRADED;
    } else if (status_.state == TerminalState::DEGRADED && fresh) {
        status_.state = TerminalState::NORMAL;
    }
    status_.mode_transition = false;
    fill_status();
}

void StoresManagement::command_mode(const icd::SmsModeCmd& cmd) noexcept {
    if (!mode_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    status_.last_cmd_seq = cmd.cmd_seq;
    if (!commandable(cmd.requested_state)) {
        status_.cmd_rejected = true;
        return;
    }
    status_.cmd_rejected = false;
    status_.state = cmd.requested_state;
    status_.mode_transition = false;
}

icd::CmdStatus StoresManagement::arm_station(std::size_t index) noexcept {
    Station& st = loadout_[index];
    if (st.state == StoreState::ARMED) {
        return icd::CmdStatus::COMPLETED;
    }
    if (!is_weapon(st.kind) || st.state != StoreState::SAFE || st.qty == 0U) {
        return icd::CmdStatus::REJECTED_STATE;
    }
    st.state = StoreState::ARMED;
    return icd::CmdStatus::COMPLETED;
}

icd::CmdStatus StoresManagement::safe_station(std::size_t index) noexcept {
    Station& st = loadout_[index];
    if (st.state == StoreState::SAFE) {
        return icd::CmdStatus::COMPLETED;
    }
    if (st.state != StoreState::ARMED) {
        return icd::CmdStatus::REJECTED_STATE;
    }
    st.state = StoreState::SAFE;
    return icd::CmdStatus::COMPLETED;
}

icd::CmdStatus StoresManagement::release(std::size_t index) noexcept {
    Station& st = loadout_[index];
    if (master_arm_ != icd::MasterArm::ARMED || st.state != StoreState::ARMED || st.qty == 0U) {
        return icd::CmdStatus::REJECTED_STATE;
    }
    std::uint8_t count = st.qty;  // SALVO: the rest
    if (release_mode_ == icd::ReleaseMode::SINGLE) {
        count = 1U;
    } else if (release_mode_ == icd::ReleaseMode::RIPPLE) {
        count = std::min<std::uint8_t>(st.qty, 2U);
    }
    st.qty = static_cast<std::uint8_t>(st.qty - count);
    released_ = static_cast<std::uint8_t>(std::min(255, released_ + count));
    if (st.qty == 0U) {
        st.state = StoreState::EXPENDED;
    }
    return icd::CmdStatus::COMPLETED;
}

void StoresManagement::jettison() noexcept {
    for (Station& st : loadout_) {
        if (st.kind != StoreKind::NONE && carried(st.state)) {
            st.state = StoreState::JETTISONED;
            st.qty = 0U;
        }
    }
    jettisoned_ = true;
}

void StoresManagement::command(const icd::SmsCmd& cmd) noexcept {
    if (!cmd_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    status_.cmd_seq_last_sms = cmd.cmd_seq;
    const bool station_given = cmd.station >= 1U && cmd.station <= kStations;
    const std::size_t index = static_cast<std::size_t>((station_given ? cmd.station : selected_) - 1U);
    const bool station_ok = cmd.station == 0U || station_given;
    switch (cmd.command) {
        case icd::SmsCommand::SELECT_STATION:
            if (station_given) {
                selected_ = cmd.station;
                cmd_status_ = icd::CmdStatus::COMPLETED;
            } else {
                cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            }
            break;
        case icd::SmsCommand::SET_RELEASE_MODE:
            if (icd::is_valid(cmd.release_mode)) {
                release_mode_ = cmd.release_mode;
                cmd_status_ = icd::CmdStatus::COMPLETED;
            } else {
                cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            }
            break;
        case icd::SmsCommand::SET_DELIVERY_MODE:
            if (icd::is_valid(cmd.delivery_mode)) {
                delivery_mode_ = cmd.delivery_mode;
                cmd_status_ = icd::CmdStatus::COMPLETED;
            } else {
                cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            }
            break;
        case icd::SmsCommand::ARM_STATION:
            cmd_status_ = station_ok ? arm_station(index) : icd::CmdStatus::REJECTED_INVALID;
            break;
        case icd::SmsCommand::SAFE_STATION:
            cmd_status_ = station_ok ? safe_station(index) : icd::CmdStatus::REJECTED_INVALID;
            break;
        case icd::SmsCommand::RELEASE:
            cmd_status_ = station_ok ? release(index) : icd::CmdStatus::REJECTED_INVALID;
            break;
        case icd::SmsCommand::JETTISON:
            jettison();
            cmd_status_ = icd::CmdStatus::COMPLETED;
            break;
        case icd::SmsCommand::NONE:
        default:
            cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
            break;
    }
    fill_status();
}

void StoresManagement::fill_status() noexcept {
    status_.master_arm = master_arm_;
    status_.sms_cmd_status = cmd_status_;
    status_.fms_valid = fms_fresh(frame_);
    status_.jettisoned = jettisoned_;
    status_.healthy = !bit_.failed;
    status_.release_mode = release_mode_;
    status_.delivery_mode = delivery_mode_;
    status_.selected_station = selected_;
    status_.armed_count = static_cast<std::uint8_t>(armed_count(loadout_));
    status_.total_weight = total_weight_kg(loadout_);
    status_.stores_released = released_;
    for (std::size_t i = 0; i < kStations; ++i) {
        put_station(status_, i, loadout_[i]);
    }
}

}  // namespace fmofp::stores
