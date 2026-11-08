#include <fmofp/sensor/sensor_management.hpp>

#include <algorithm>
#include <bitset>
#include <cmath>

namespace fmofp::sensor {

using icd::TerminalState;

namespace {

bool commandable(TerminalState s) noexcept {
    return s == TerminalState::STANDBY || s == TerminalState::NORMAL || s == TerminalState::TEST ||
           s == TerminalState::MAINTENANCE || s == TerminalState::CALIBRATION;
}

// sensorDataFusion._BAND_MAP: the lower bound in, the upper out, in Hz.
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
    double strength_dbm;
    double bearing_deg;
};

// PLANT_ESM carries its five signals as numbered fields.
Signal signal_of(const icd::PlantEsm& e, std::size_t i) noexcept {
    switch (i) {
        case 0:
            return {e.frequency_1, e.strength_1, e.bearing_1};
        case 1:
            return {e.frequency_2, e.strength_2, e.bearing_2};
        case 2:
            return {e.frequency_3, e.strength_3, e.bearing_3};
        case 3:
            return {e.frequency_4, e.strength_4, e.bearing_4};
        default:
            return {e.frequency_5, e.strength_5, e.bearing_5};
    }
}

constexpr std::size_t index_of(icd::SensorId sensor) noexcept { return static_cast<std::size_t>(sensor); }

bool valid_sensor(icd::SensorId sensor) noexcept { return icd::is_valid(sensor) && index_of(sensor) < kSensorCount; }

std::uint8_t add_wrapped(std::uint8_t a, std::uint8_t b) noexcept {
    return static_cast<std::uint8_t>((static_cast<unsigned>(a) + static_cast<unsigned>(b)) & 0xFFU);
}

}  // namespace

const char* to_string(Source s) noexcept {
    switch (s) {
        case Source::RADAR:
            return "RADAR";
        case Source::LIDAR:
            return "LIDAR";
        case Source::IR:
            return "IR";
        case Source::ESM:
            return "ESM";
        case Source::FUSED:
            return "FUSED";
    }
    return "?";
}

const char* to_string(ContactClass c) noexcept {
    switch (c) {
        case ContactClass::UNKNOWN:
            return "UNKNOWN";
        case ContactClass::AIR:
            return "AIR";
        case ContactClass::GROUND:
            return "GROUND";
        case ContactClass::SURFACE:
            return "SURFACE";
        case ContactClass::EMITTER:
            return "EMITTER";
    }
    return "?";
}

icd::RwrBand classify_band(double hz) noexcept {
    if (!std::isfinite(hz)) {
        return icd::RwrBand::UNKNOWN;
    }
    const auto it = std::find_if(kBands.begin(), kBands.end(),
                                 [hz](const BandLimits& b) { return b.low <= hz && hz < b.high; });
    return it == kBands.end() ? icd::RwrBand::UNKNOWN : it->band;
}

// _bearing_delta: abs(a - b) % 360, then the shorter way round; a missing bearing never gates.
double bearing_delta(bool has_a, double a, bool has_b, double b) noexcept {
    if (!has_a || !has_b) {
        return 360.0;
    }
    const double delta = std::fmod(std::fabs(a - b), 360.0);
    return std::min(delta, 360.0 - delta);
}

Status SensorManagement::init() noexcept {
    table_.fill(Contact{});
    count_ = 0;
    active_.fill(true);  // SensorService.start: activate_all on both managers
    seq_ = 0;
    dropped_ = 0;
    updated_ = false;
    frame_ = 0;
    cmd_status_ = icd::CmdStatus::NONE;
    scan_ = icd::PlantSensorScan{};
    have_scan_ = false;
    scan_frame_ = 0;
    scan_consumed_ = true;
    esm_ = icd::PlantEsm{};
    have_esm_ = false;
    esm_frame_ = 0;
    esm_consumed_ = true;
    status_ = icd::SnsStatus{};
    status_.state = TerminalState::INITIALIZING;
    status_.healthy = true;
    self_test_started_ = 0;
    self_test_running_ = false;
    bit_ = bus::BitWord{};
    mode_seq_ = bus::CommandSequence{};
    cmd_seq_ = bus::CommandSequence{};
    fill_status(0);
    return Status::kOk;
}

void SensorManagement::reset() noexcept { (void)init(); }

void SensorManagement::start_self_test() noexcept {
    self_test_running_ = true;
    bit_.in_progress = true;
}

void SensorManagement::step(const icd::PlantSensorScan* scan, const icd::PlantEsm* esm, std::uint32_t frame) noexcept {
    frame_ = frame;
    if (scan != nullptr) {
        if (!have_scan_ || scan->epoch != scan_.epoch) {
            scan_consumed_ = false;
        }
        scan_ = *scan;
        have_scan_ = true;
        scan_frame_ = frame;
    }
    if (esm != nullptr) {
        if (!have_esm_ || esm->epoch != esm_.epoch) {
            esm_consumed_ = false;
        }
        esm_ = *esm;
        have_esm_ = true;
        esm_frame_ = frame;
    }
    const bool scan_fresh = have_scan_ && frame >= scan_frame_ && frame - scan_frame_ < kScanStaleFrames;
    const bool esm_fresh = have_esm_ && frame >= esm_frame_ && frame - esm_frame_ < kEsmStaleFrames;

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
        const bool scan_new = scan_fresh && !scan_consumed_;
        const bool esm_new = esm_fresh && !esm_consumed_;
        update(scan_new ? &scan_ : nullptr, esm_new ? &esm_ : nullptr, frame);
        if (scan_new) {
            scan_consumed_ = true;
        }
        if (esm_new) {
            esm_consumed_ = true;
        }
    }

    // The sensors have a world to scan while the plant's sets arrive.
    if (status_.state == TerminalState::INITIALIZING && scan_fresh) {
        status_.state = TerminalState::NORMAL;
    } else if (status_.state == TerminalState::NORMAL && !scan_fresh) {
        status_.state = TerminalState::DEGRADED;
    } else if (status_.state == TerminalState::DEGRADED && scan_fresh) {
        status_.state = TerminalState::NORMAL;
    }
    status_.mode_transition = false;
    fill_status(frame);
}

// SensorService._update: SensorDataFusion.update (the active sensors' scans, the passive sensors' detections,
// the stale contacts out), then the health from the sensors' states.
void SensorManagement::update(const icd::PlantSensorScan* scan, const icd::PlantEsm* esm, std::uint32_t frame) noexcept {
    frame_ = frame;
    if (scan != nullptr) {
        ingest_scan(*scan, frame);
    }
    if (esm != nullptr) {
        ingest_esm(*esm, frame);
    }
    expire(frame);
    updated_ = true;
    fill_status(frame);
}

std::uint16_t SensorManagement::next_id() noexcept {
    ++seq_;  // _next_id: every detection takes a number, merged or not
    return seq_;
}

// _ingest_active then the infrared half of _ingest_passive, in the managers' order: main radar, terrain-following
// radar, LIDAR, forward-looking infrared, missile approach warning. A sensor switched off contributes nothing.
void SensorManagement::ingest_scan(const icd::PlantSensorScan& scan, std::uint32_t frame) noexcept {
    const std::size_t radars = std::min<std::size_t>(scan.radar_count, scan.radar.size());
    for (std::size_t i = 0; i < radars; ++i) {
        const icd::PlantSensorScanRadar& r = scan.radar[i];
        if (!valid_sensor(r.sensor) || index_of(r.sensor) > index_of(icd::SensorId::TFR_RADAR) ||
            !active_[index_of(r.sensor)] || !std::isfinite(r.distance) || !std::isfinite(r.angle) ||
            !std::isfinite(r.speed)) {
            continue;
        }
        Contact c{};
        c.used = true;
        c.id = next_id();
        c.origin = Source::RADAR;
        c.source = Source::RADAR;
        c.contact_class = ContactClass::UNKNOWN;  // a radar detection has no elevation
        c.has_range = true;
        c.range_m = r.distance;
        c.has_bearing = true;
        c.bearing_deg = r.angle;
        c.has_speed = true;
        c.speed_ms = r.speed;
        c.confidence = r.sensor == icd::SensorId::MAIN_RADAR ? kMainRadarAccuracy : kTfrRadarAccuracy;
        c.last_seen = frame;
        merge_or_add(c, frame);
    }
    if (active_[index_of(icd::SensorId::LIDAR)]) {
        const std::size_t points = std::min<std::size_t>(scan.lidar_count, scan.lidar.size());
        for (std::size_t i = 0; i < points; ++i) {
            const icd::PlantSensorScanLidar& p = scan.lidar[i];
            if (!std::isfinite(p.distance) || !std::isfinite(p.elevation)) {
                continue;
            }
            Contact c{};
            c.used = true;
            c.id = next_id();
            c.origin = Source::LIDAR;
            c.source = Source::LIDAR;
            c.contact_class = p.elevation > kAirAboveDeg ? ContactClass::AIR : ContactClass::GROUND;
            c.has_range = true;
            c.range_m = p.distance;
            // The point's key is azimuth and the fusion read angle: no bearing, so a LIDAR point never merges.
            c.has_elevation = true;
            c.elevation_deg = p.elevation;
            c.has_speed = true;  // det.get("speed", 0.0)
            c.speed_ms = 0.0;
            c.confidence = kLidarAccuracy;
            c.last_seen = frame;
            merge_or_add(c, frame);
        }
    }
    const std::size_t objects = std::min<std::size_t>(scan.infrared_count, scan.infrared.size());
    for (std::size_t i = 0; i < objects; ++i) {
        const icd::PlantSensorScanInfrared& o = scan.infrared[i];
        if (!valid_sensor(o.sensor) || (o.sensor != icd::SensorId::FLIR && o.sensor != icd::SensorId::MAWS) ||
            !active_[index_of(o.sensor)] || !std::isfinite(o.angle) || !std::isfinite(o.distance)) {
            continue;
        }
        Contact c{};
        c.used = true;
        c.id = next_id();
        c.origin = Source::IR;
        c.source = Source::IR;
        c.contact_class = ContactClass::AIR;
        c.has_range = true;
        c.range_m = o.distance;
        c.has_bearing = true;
        c.bearing_deg = o.angle;
        c.confidence = kIrConfidence;
        c.last_seen = frame;
        merge_or_add(c, frame);
    }
}

// The ESM half of _ingest_passive: an EMITTER contact per signal, with its band.
void SensorManagement::ingest_esm(const icd::PlantEsm& esm, std::uint32_t frame) noexcept {
    if (!active_[index_of(icd::SensorId::ESM)]) {
        return;
    }
    const std::size_t n = std::min<std::size_t>(esm.count, std::size_t{5});
    for (std::size_t i = 0; i < n; ++i) {
        const Signal s = signal_of(esm, i);
        if (!std::isfinite(s.frequency_mhz) || !std::isfinite(s.bearing_deg) || !std::isfinite(s.strength_dbm)) {
            continue;
        }
        Contact c{};
        c.used = true;
        c.id = next_id();
        c.origin = Source::ESM;
        c.source = Source::ESM;
        c.contact_class = ContactClass::EMITTER;
        c.has_bearing = true;
        c.bearing_deg = s.bearing_deg;
        c.has_frequency = true;
        c.frequency_hz = s.frequency_mhz * 1e6;
        c.signal_dbm = s.strength_dbm;
        c.band = classify_band(c.frequency_hz);
        c.confidence = kEsmConfidence;
        c.last_seen = frame;
        merge_or_add(c, frame);
    }
}

// _merge_or_add: the first contact in table order within the bearing gate takes the detection (seen again, more
// confident, corroborated by the detection's source, FUSED from the second source, its missing kinematics
// filled); otherwise the detection is a new contact at the end of the table.
void SensorManagement::merge_or_add(Contact& fresh, std::uint32_t frame) noexcept {
    const auto it = std::find_if(table_.begin(), table_.begin() + static_cast<std::ptrdiff_t>(count_),
                                 [&fresh](const Contact& e) {
                                     return bearing_delta(e.has_bearing, e.bearing_deg, fresh.has_bearing,
                                                          fresh.bearing_deg) < kGateDeg;
                                 });
    if (it != table_.begin() + static_cast<std::ptrdiff_t>(count_)) {
        Contact& e = *it;
        e.last_seen = frame;
        e.confidence = std::min(1.0, e.confidence + kCorroborationStep);
        e.corroborated = static_cast<std::uint8_t>(e.corroborated | source_bit(fresh.source));
        if (std::bitset<8>(e.corroborated).count() >= 2) {
            e.source = Source::FUSED;
        }
        if (!e.has_range && fresh.has_range) {
            e.has_range = true;
            e.range_m = fresh.range_m;
        }
        if (!e.has_speed && fresh.has_speed) {
            e.has_speed = true;
            e.speed_ms = fresh.speed_ms;
        }
        if (!e.has_frequency && fresh.has_frequency) {
            e.has_frequency = true;
            e.frequency_hz = fresh.frequency_hz;
            e.signal_dbm = fresh.signal_dbm;
            e.band = fresh.band;
        }
        return;
    }
    if (count_ >= kMaxContacts) {
        dropped_ = add_wrapped(dropped_, 1);
        return;
    }
    table_[count_] = fresh;
    ++count_;
}

// _expire_stale: contacts not seen for over CONTACT_TTL_S go; the rest keep their order (a dict deletion).
void SensorManagement::expire(std::uint32_t frame) noexcept {
    const auto end = table_.begin() + static_cast<std::ptrdiff_t>(count_);
    const auto kept = std::remove_if(table_.begin(), end, [frame](const Contact& c) {
        return frame > c.last_seen && frame - c.last_seen > kContactTtlFrames;
    });
    std::fill(kept, end, Contact{});
    count_ = static_cast<std::size_t>(kept - table_.begin());
}

bool SensorManagement::set_active(icd::SensorId sensor, bool on) noexcept {
    if (!valid_sensor(sensor)) {
        return false;
    }
    active_[index_of(sensor)] = on;
    fill_status(frame_);
    return true;
}

bool SensorManagement::active(icd::SensorId sensor) const noexcept {
    return valid_sensor(sensor) && active_[index_of(sensor)];
}

// SensorService._update's rule: NOMINAL when both suites are whole, DEGRADED when one is, FAULT otherwise.
icd::SensorHealth SensorManagement::health() const noexcept {
    if (!updated_) {
        return icd::SensorHealth::INITIALISING;
    }
    const bool active_ok = std::all_of(active_.begin(), active_.begin() + 3, [](bool on) { return on; });
    const bool passive_ok = std::all_of(active_.begin() + 3, active_.end(), [](bool on) { return on; });
    if (active_ok && passive_ok) {
        return icd::SensorHealth::NOMINAL;
    }
    return (active_ok || passive_ok) ? icd::SensorHealth::DEGRADED : icd::SensorHealth::FAULT;
}

void SensorManagement::command_mode(const icd::SnsModeCmd& cmd) noexcept {
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

void SensorManagement::command(const icd::SnsCmd& cmd, std::uint32_t frame) noexcept {
    if (!cmd_seq_.accept(cmd.cmd_seq)) {
        return;
    }
    frame_ = frame;
    cmd_status_ = icd::CmdStatus::REJECTED_INVALID;
    switch (cmd.command) {
        case icd::SensorCommand::ACTIVATE:
            if (set_active(cmd.sensor, true)) {
                cmd_status_ = icd::CmdStatus::ACCEPTED;
            }
            break;
        case icd::SensorCommand::DEACTIVATE:
            if (set_active(cmd.sensor, false)) {
                cmd_status_ = icd::CmdStatus::ACCEPTED;
            }
            break;
        case icd::SensorCommand::NONE:
            break;
    }
    fill_status(frame);
}

void SensorManagement::fill_status(std::uint32_t frame) noexcept {
    status_.health = health();
    status_.sensor_cmd_status = cmd_status_;
    status_.scan_valid = have_scan_ && frame >= scan_frame_ && frame - scan_frame_ < kScanStaleFrames;
    status_.esm_valid = have_esm_ && frame >= esm_frame_ && frame - esm_frame_ < kEsmStaleFrames;
    status_.healthy = !bit_.failed;
    status_.main_radar_active = active_[index_of(icd::SensorId::MAIN_RADAR)];
    status_.tfr_radar_active = active_[index_of(icd::SensorId::TFR_RADAR)];
    status_.lidar_active = active_[index_of(icd::SensorId::LIDAR)];
    status_.flir_active = active_[index_of(icd::SensorId::FLIR)];
    status_.maws_active = active_[index_of(icd::SensorId::MAWS)];
    status_.esm_active = active_[index_of(icd::SensorId::ESM)];
    status_.contact_count = static_cast<std::uint8_t>(count_);
    status_.dropped = dropped_;
    status_.sequence = seq_;
}

}  // namespace fmofp::sensor
