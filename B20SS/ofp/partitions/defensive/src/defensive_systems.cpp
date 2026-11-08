#include <fmofp/defensive/defensive_systems.hpp>

#include <algorithm>
#include <cmath>

namespace fmofp::defensive {

using icd::TerminalState;

namespace {

constexpr std::size_t kNone = kMaxContacts;
constexpr double kPi = 3.14159265358979323846;

bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

// defensiveService.BAND_NAMES: the lower bound in, the upper out, in Hz.
struct BandLimits {
    double low;
    double high;
    icd::RwrBand band;
};
constexpr std::array<BandLimits, 7> kBands = {{{0.5e9, 2e9, icd::RwrBand::L},
                                               {2e9, 4e9, icd::RwrBand::S},
                                               {4e9, 8e9, icd::RwrBand::C},
                                               {8e9, 12e9, icd::RwrBand::X},
                                               {12e9, 18e9, icd::RwrBand::KU},
                                               {18e9, 27e9, icd::RwrBand::K},
                                               {27e9, 40e9, icd::RwrBand::KA}}};

struct Signal {
    double frequency_mhz;
    double bearing_deg;
    double range_nm;
};

// PLANT_ESM carries its five signals as numbered fields.
Signal signal_of(const icd::PlantEsm& e, std::size_t i) noexcept {
    switch (i) {
        case 0:
            return {e.frequency_1, e.bearing_1, e.range_1};
        case 1:
            return {e.frequency_2, e.bearing_2, e.range_2};
        case 2:
            return {e.frequency_3, e.bearing_3, e.range_3};
        case 3:
            return {e.frequency_4, e.bearing_4, e.range_4};
        default:
            return {e.frequency_5, e.bearing_5, e.range_5};
    }
}

std::uint8_t add_wrapped(std::uint8_t a, std::uint8_t b) noexcept {
    return static_cast<std::uint8_t>((static_cast<unsigned>(a) + static_cast<unsigned>(b)) & 0xFFU);
}

}  // namespace

ThreatEntry threat_entry(icd::TargetClass classification) noexcept {
    switch (classification) {
        case icd::TargetClass::FIGHTER:
            return {icd::RwrBand::X, icd::ThreatType::AIR, 2};
        case icd::TargetClass::BOMBER:
            return {icd::RwrBand::S, icd::ThreatType::AIR, 3};
        default:
            return {icd::RwrBand::UNKNOWN, icd::ThreatType::UNK, kLowestPriority};
    }
}

icd::RwrBand classify_frequency(double hz) noexcept {
    if (!std::isfinite(hz)) {
        return icd::RwrBand::UNKNOWN;
    }
    const auto it = std::find_if(kBands.begin(), kBands.end(),
                                 [hz](const BandLimits& b) { return b.low <= hz && hz < b.high; });
    return it == kBands.end() ? icd::RwrBand::UNKNOWN : it->band;
}

// math.degrees(math.atan2(x, y)) % 360: a Python float modulo is never negative.
double bearing_of(double east, double north) noexcept {
    double deg = std::fmod(std::atan2(east, north) * (180.0 / kPi), 360.0);
    if (deg < 0.0) {
        deg += 360.0;
    }
    return deg;
}

double range_nm_of(double east, double north, double up) noexcept {
    return std::sqrt(east * east + north * north + up * up) / kMetresPerNm;
}

Status DefensiveSystems::init() noexcept {
    table_.fill(Contact{});
    next_order_ = 0;
    chaff_ = kChaffMax;
    flares_ = kFlareMax;
    has_dispensed_ = false;
    last_dispense_ = 0;
    ecm_mode_ = icd::EcmMode::STANDBY;
    jamming_active_ = false;
    cmd_status_ = icd::CmdStatus::NONE;
    auto_salvos_ = 0;
    chaff_released_ = 0;
    flares_released_ = 0;
    dropped_ = 0;
    updates_ = 0;
    fused_ = icd::RdrFusedTracks{};
    have_fused_ = false;
    fused_frame_ = 0;
    esm_ = icd::PlantEsm{};
    have_esm_ = false;
    esm_frame_ = 0;
    esm_consumed_ = true;
    status_ = icd::DefStatus{};
    status_.state = TerminalState::INITIALIZING;
    status_.healthy = true;
    self_test_started_ = 0;
    self_test_running_ = false;
    bit_ = bus::BitWord{};
    mode_seq_ = bus::CommandSequence{};
    cmd_seq_ = bus::CommandSequence{};
    build_contacts();
    contacts_update_ = true;  // the empty table goes out at start, so the displays read CLEAR rather than nothing
    fill_status(0);
    return Status::kOk;
}

void DefensiveSystems::reset() noexcept { (void)init(); }

void DefensiveSystems::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

void DefensiveSystems::step(const icd::RdrFusedTracks* fused, const icd::PlantEsm* esm, std::uint32_t frame) noexcept {
    frame_ = frame;
    if (fused != nullptr) {
        fused_ = *fused;
        have_fused_ = true;
        fused_frame_ = frame;
    }
    if (esm != nullptr) {
        // The plant republishes a set until the next one; only a new epoch is a new detection.
        if (!have_esm_ || esm->epoch != esm_.epoch) {
            esm_consumed_ = false;
        }
        esm_ = *esm;
        have_esm_ = true;
        esm_frame_ = frame;
    }
    const bool esm_fresh = have_esm_ && frame >= esm_frame_ && frame - esm_frame_ < kEsmStaleFrames;
    const bool fused_fresh = have_fused_ && frame >= fused_frame_ && frame - fused_frame_ < kFusedStaleFrames;

    if (self_test_running_) {
        if (self_test_started_ == 0) {
            self_test_started_ = frame == 0 ? 1 : frame;
        } else if (frame - self_test_started_ >= kSelfTestFrames) {
            self_test_running_ = false;
            self_test_started_ = 0;
            bit_.in_progress = false;
        }
    }

    if (frame % kUpdatePeriodFrames == 0) {
        const bool esm_new = esm_fresh && !esm_consumed_;
        update_rwr(fused_fresh ? &fused_ : nullptr, esm_new ? &esm_ : nullptr, frame);
        if (esm_new) {
            esm_consumed_ = true;
        }
    }

    // The receiver has a world to listen to while the plant's intercepts arrive; the fused tracks come and go
    // with the radars and are reported as a bit, as the Python ran on without its fusion.
    if (status_.state == TerminalState::INITIALIZING && esm_fresh) {
        status_.state = TerminalState::NORMAL;
    } else if (status_.state == TerminalState::NORMAL && !esm_fresh) {
        status_.state = TerminalState::DEGRADED;
    } else if (status_.state == TerminalState::DEGRADED && esm_fresh) {
        status_.state = TerminalState::NORMAL;
    }
    status_.mode_transition = false;
    fill_status(frame);
}

// _update_rwr then _auto_dispense: the fusion's hostile tracks, the ESM's signals, the stale contacts out,
// the salvo if a priority-1 hostile contact is in the table.
void DefensiveSystems::update_rwr(const icd::RdrFusedTracks* fused, const icd::PlantEsm* esm,
                                  std::uint32_t frame) noexcept {
    frame_ = frame;
    if (fused != nullptr) {
        ingest_fused(*fused, frame);
    }
    if (esm != nullptr) {
        ingest_esm(*esm, frame);
    }
    expire(frame);
    auto_dispense(frame);
    ++updates_;
    build_contacts();
    contacts_update_ = true;
    fill_status(frame);
}

std::size_t DefensiveSystems::find(icd::RwrSource source, icd::RwrBand band, std::uint16_t id) const noexcept {
    // The Python's keys: FUS-<track id>, ESM-<band>-<whole bearing>, SCEN-<name>.
    const auto it = std::find_if(table_.begin(), table_.end(), [source, band, id](const Contact& c) {
        return c.used && c.source == source && c.id == id && (source != icd::RwrSource::ESM || c.band == band);
    });
    return it == table_.end() ? kNone : static_cast<std::size_t>(it - table_.begin());
}

std::size_t DefensiveSystems::add(const Contact& contact) noexcept {
    const auto it = std::find_if(table_.begin(), table_.end(), [](const Contact& c) { return !c.used; });
    if (it == table_.end()) {
        dropped_ = add_wrapped(dropped_, 1);
        return kNone;
    }
    *it = contact;
    it->used = true;
    it->order = next_order_++;
    return static_cast<std::size_t>(it - table_.begin());
}

// One contact per hostile fused track (RadarDataFusion.get_threat_tracks), rebuilt every update so it never
// expires while the track is hostile; THREAT_DB by the track's classification.
void DefensiveSystems::ingest_fused(const icd::RdrFusedTracks& fused, std::uint32_t frame) noexcept {
    const std::size_t n = std::min<std::size_t>(fused.track_count, fused.track.size());
    for (std::size_t i = 0; i < n; ++i) {
        const icd::RdrFusedTracksTrack& t = fused.track[i];
        if (t.threat != icd::Threat::HOSTILE || !std::isfinite(t.x) || !std::isfinite(t.y) || !std::isfinite(t.z)) {
            continue;
        }
        const ThreatEntry entry = threat_entry(t.classification);
        Contact c{};
        c.used = true;
        c.source = icd::RwrSource::FUSION;
        c.band = entry.band;
        c.id = t.track_id;
        c.bearing_deg = bearing_of(t.x, t.y);
        c.range_nm = range_nm_of(t.x, t.y, t.z);
        c.type = entry.type;
        c.priority = entry.priority;
        c.hostile = true;
        c.last_seen = frame;
        const std::size_t at = find(icd::RwrSource::FUSION, entry.band, t.track_id);
        if (at != kNone) {
            c.order = table_[at].order;  // a dict assignment keeps the key's place
            table_[at] = c;
        } else {
            (void)add(c);
        }
    }
}

// One contact per ESM signal the table has not seen (the band of its frequency and the whole degrees of its
// bearing name it); a signal seen before only refreshes last_seen. The range is the plant's draw.
void DefensiveSystems::ingest_esm(const icd::PlantEsm& esm, std::uint32_t frame) noexcept {
    const std::size_t n = std::min<std::size_t>(esm.count, kMaxEsmSignals);
    for (std::size_t i = 0; i < n; ++i) {
        const Signal s = signal_of(esm, i);
        if (!std::isfinite(s.frequency_mhz) || !std::isfinite(s.bearing_deg) || !std::isfinite(s.range_nm) ||
            s.bearing_deg < 0.0 || s.bearing_deg >= 360.0) {
            continue;
        }
        const icd::RwrBand band = classify_frequency(s.frequency_mhz * 1e6);
        const auto whole = static_cast<std::uint16_t>(s.bearing_deg);  // int(bearing)
        const std::size_t at = find(icd::RwrSource::ESM, band, whole);
        if (at != kNone) {
            table_[at].last_seen = frame;
            continue;
        }
        Contact c{};
        c.used = true;
        c.source = icd::RwrSource::ESM;
        c.band = band;
        c.id = whole;
        c.bearing_deg = s.bearing_deg;
        c.range_nm = s.range_nm;
        c.type = icd::ThreatType::UNK;
        c.priority = kEsmPriority;
        c.hostile = true;
        c.last_seen = frame;
        (void)add(c);
    }
}

void DefensiveSystems::expire(std::uint32_t frame) noexcept {
    std::replace_if(
        table_.begin(), table_.end(),
        [frame](const Contact& c) { return c.used && frame > c.last_seen && frame - c.last_seen > kTrackTtlFrames; },
        Contact{});
}

// _auto_dispense: a salvo when a hostile priority-1 contact is present and the cooldown has passed (strictly);
// an empty dispenser changes nothing, not even the cooldown.
void DefensiveSystems::auto_dispense(std::uint32_t frame) noexcept {
    if (high_priority_count() == 0) {
        return;
    }
    const bool cooling = has_dispensed_ && (frame < last_dispense_ || frame - last_dispense_ <= kCooldownFrames);
    if (cooling) {
        return;
    }
    const std::uint8_t released = std::min(kSalvoSize, flares_);
    if (released == 0) {
        return;
    }
    flares_ = static_cast<std::uint8_t>(flares_ - released);
    last_dispense_ = frame;
    has_dispensed_ = true;
    auto_salvos_ = add_wrapped(auto_salvos_, 1);
    flares_released_ = add_wrapped(flares_released_, released);
}

std::uint8_t DefensiveSystems::dispense_chaff(std::uint8_t count) noexcept {
    const std::uint8_t asked = count == 0 ? std::uint8_t{1} : count;
    const std::uint8_t released = std::min(asked, chaff_);
    chaff_ = static_cast<std::uint8_t>(chaff_ - released);
    chaff_released_ = add_wrapped(chaff_released_, released);
    fill_status(frame_);
    return released;
}

// dispense_flares: nothing while the cooldown runs (strictly under 3 s); otherwise what remains, and the
// cooldown restarts even when nothing was left to release.
std::uint8_t DefensiveSystems::dispense_flares(std::uint8_t count, std::uint32_t frame) noexcept {
    frame_ = frame;
    const bool cooling = has_dispensed_ && (frame < last_dispense_ || frame - last_dispense_ < kCooldownFrames);
    if (cooling) {
        fill_status(frame_);
        return 0;
    }
    const std::uint8_t asked = count == 0 ? std::uint8_t{1} : count;
    const std::uint8_t released = std::min(asked, flares_);
    flares_ = static_cast<std::uint8_t>(flares_ - released);
    last_dispense_ = frame;
    has_dispensed_ = true;
    flares_released_ = add_wrapped(flares_released_, released);
    fill_status(frame_);
    return released;
}

bool DefensiveSystems::set_ecm_mode(icd::EcmMode mode) noexcept {
    if (!icd::is_valid(mode)) {
        return false;
    }
    ecm_mode_ = mode;
    jamming_active_ = mode == icd::EcmMode::ACTIVE;
    fill_status(frame_);
    return true;
}

// scenarioEngine._inject_threat: a hostile contact SCEN-<id> written straight into the table.
bool DefensiveSystems::inject_threat(std::uint8_t threat_id, double bearing_deg, double range_nm, icd::RwrBand band,
                                     icd::ThreatType type, std::uint8_t priority, std::uint32_t frame) noexcept {
    if (!std::isfinite(bearing_deg) || !std::isfinite(range_nm) || priority < 1 || priority > kLowestPriority ||
        !icd::is_valid(band) || !icd::is_valid(type)) {
        return false;
    }
    Contact c{};
    c.used = true;
    c.source = icd::RwrSource::SCENARIO;
    c.band = band;
    c.id = threat_id;
    c.bearing_deg = bearing_deg;
    c.range_nm = range_nm;
    c.type = type;
    c.priority = priority;
    c.hostile = true;
    c.last_seen = frame;
    frame_ = frame;
    const std::size_t at = find(icd::RwrSource::SCENARIO, band, threat_id);
    bool placed = false;
    if (at != kNone) {
        c.order = table_[at].order;
        table_[at] = c;
        placed = true;
    } else {
        placed = add(c) != kNone;
    }
    fill_status(frame_);
    return placed;
}

void DefensiveSystems::command_mode(const icd::DefModeCmd& cmd) noexcept {
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

void DefensiveSystems::command(const icd::DefCmd& cmd, std::uint32_t frame) noexcept {
    if (!cmd_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    frame_ = frame;
    cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
    switch (cmd.command) {
        case icd::DefensiveCommand::DISPENSE_CHAFF:
            cmd_status_ = dispense_chaff(cmd.count) > 0 ? icd::CmdStatus::ACCEPTED : icd::CmdStatus::FAILED;
            break;
        case icd::DefensiveCommand::DISPENSE_FLARES:
            cmd_status_ = dispense_flares(cmd.count, frame) > 0 ? icd::CmdStatus::ACCEPTED : icd::CmdStatus::FAILED;
            break;
        case icd::DefensiveCommand::SET_ECM_MODE:
            if (set_ecm_mode(cmd.ecm_mode)) {
                cmd_status_ = icd::CmdStatus::ACCEPTED;
            }
            break;
        case icd::DefensiveCommand::INJECT_THREAT:
            if (cmd.priority >= 1 && cmd.priority <= kLowestPriority && icd::is_valid(cmd.band) &&
                icd::is_valid(cmd.threat_type) && std::isfinite(cmd.bearing) && std::isfinite(cmd.range)) {
                cmd_status_ = inject_threat(cmd.threat_id, cmd.bearing, cmd.range, cmd.band, cmd.threat_type,
                                            cmd.priority, frame)
                                  ? icd::CmdStatus::ACCEPTED
                                  : icd::CmdStatus::FAILED;
            }
            break;
        case icd::DefensiveCommand::NONE:
            break;
    }
    fill_status(frame);
}

std::uint8_t DefensiveSystems::high_priority_count() const noexcept {
    return static_cast<std::uint8_t>(std::count_if(
        table_.begin(), table_.end(), [](const Contact& c) { return c.used && c.priority == 1 && c.hostile; }));
}

std::size_t DefensiveSystems::contact_count() const noexcept {
    return static_cast<std::size_t>(std::count_if(table_.begin(), table_.end(), [](const Contact& c) { return c.used; }));
}

bool DefensiveSystems::take_contacts_update() noexcept {
    const bool pending = contacts_update_;
    contacts_update_ = false;
    return pending;
}

void DefensiveSystems::refresh_contacts() noexcept { build_contacts(); }

// get_rwr_contacts(): every contact sorted by priority, the Python's stable sort keeping the table's order
// within a priority.
void DefensiveSystems::build_contacts() noexcept {
    contacts_ = icd::DefRwrContacts{};
    contacts_.update = updates_;
    contacts_.dropped = dropped_;
    contacts_.high_priority_count = high_priority_count();
    std::array<std::size_t, kMaxContacts> order{};
    std::size_t n = 0;
    for (std::size_t i = 0; i < table_.size(); ++i) {
        if (table_[i].used) {
            order[n++] = i;
        }
    }
    std::sort(order.begin(), order.begin() + static_cast<std::ptrdiff_t>(n), [this](std::size_t a, std::size_t b) {
        const Contact& ca = table_[a];
        const Contact& cb = table_[b];
        return ca.priority != cb.priority ? ca.priority < cb.priority : ca.order < cb.order;
    });
    for (std::size_t k = 0; k < n; ++k) {
        const Contact& c = table_[order[k]];
        icd::DefRwrContactsContact& r = contacts_.contact[k];
        r.bearing = c.bearing_deg;
        r.range = c.range_nm;
        r.band = c.band;
        r.threat_type = c.type;
        r.priority = c.priority;
        r.hostile = c.hostile;
        r.source = c.source;
        r.id = c.id;
    }
    contacts_.contact_count = static_cast<std::uint16_t>(n);
}

void DefensiveSystems::fill_status(std::uint32_t frame) noexcept {
    status_.ecm_mode = ecm_mode_;
    status_.jamming_active = jamming_active_;
    status_.defensive_cmd_status = cmd_status_;
    status_.fused_valid = have_fused_ && frame >= fused_frame_ && frame - fused_frame_ < kFusedStaleFrames;
    status_.esm_valid = have_esm_ && frame >= esm_frame_ && frame - esm_frame_ < kEsmStaleFrames;
    status_.healthy = !bit_.failed;
    status_.chaff_remaining = chaff_;
    status_.flares_remaining = flares_;
    status_.contact_count = static_cast<std::uint8_t>(contact_count());
    status_.high_priority_count = high_priority_count();
    status_.auto_salvos = auto_salvos_;
    std::uint32_t left = 0;
    if (has_dispensed_) {
        if (frame < last_dispense_) {
            left = kCooldownFrames;
        } else {
            const std::uint32_t since = frame - last_dispense_;
            left = since < kCooldownFrames ? kCooldownFrames - since : 0;
        }
    }
    status_.cooldown_frames = static_cast<std::uint8_t>(std::min<std::uint32_t>(left, 255U));
    status_.chaff_released = chaff_released_;
    status_.flares_released = flares_released_;
}

}  // namespace fmofp::defensive
