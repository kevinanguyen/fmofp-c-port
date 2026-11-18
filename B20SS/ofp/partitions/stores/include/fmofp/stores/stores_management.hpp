#ifndef FMOFP_STORES_STORES_MANAGEMENT_HPP
#define FMOFP_STORES_STORES_MANAGEMENT_HPP

#include <array>
#include <cstdint>

#include <fmofp/bus/remote_terminal.hpp>
#include <fmofp/bus/status.hpp>
#include <fmofp/icd/messages.hpp>

// The stores management terminal's logic (RT 28). The frozen
// Interfaces/userInterface/displays/sms.py had no armament system behind it:
// its eleven stations were its own table (_build_default_loadout), its master
// arm followed the FMS's weapons state (_poll_data), and it computed the load
// and the armed count (_total_weight_kg, _armed_count). Those are ported as
// written. The commands (select a station, the release and delivery modes, arm
// and safe a station, release, jettison) are new, with no Python behind them
// (ICD README section 2). Pure: ICD messages in, ICD messages out.

namespace fmofp::stores {

constexpr std::size_t kStations = 11;
constexpr std::uint32_t kFmsStaleFrames = 100;  // the displays' two seconds
constexpr std::uint32_t kSelfTestFrames = 10;

struct Station {
    icd::StoreKind kind{icd::StoreKind::NONE};
    icd::StoreState state{icd::StoreState::EMPTY};
    std::uint8_t qty{0};
};

using Loadout = std::array<Station, kStations>;

// _build_default_loadout's stations 1-11.
[[nodiscard]] Loadout default_loadout() noexcept;
// A store's unit weight in kg (the loadout's _Store weights), 0 for NONE.
[[nodiscard]] double unit_weight_kg(icd::StoreKind kind) noexcept;
// _Store.store_type "WEAPON": the stores ARM_STATION may arm.
[[nodiscard]] bool is_weapon(icd::StoreKind kind) noexcept;
// _poll_data: ARMED from ARMED, TRAIN from READY, SAFE otherwise (and while the FMS is not heard).
[[nodiscard]] icd::MasterArm master_arm_from(const icd::FmsStatus* fms) noexcept;
// _total_weight_kg: weight x max(qty, 1) over the stores not EMPTY, EXPENDED or JETTISONED.
[[nodiscard]] double total_weight_kg(const Loadout& loadout) noexcept;
// _armed_count: the stations whose store is ARMED.
[[nodiscard]] unsigned armed_count(const Loadout& loadout) noexcept;

class StoresManagement {
public:
    [[nodiscard]] Status init() noexcept;
    void reset() noexcept;
    void start_self_test() noexcept;

    // The partition's frame: the FMS status heard this frame, or null.
    void step(const icd::FmsStatus* fms, std::uint32_t frame) noexcept;

    void command_mode(const icd::SmsModeCmd& cmd) noexcept;
    void command(const icd::SmsCmd& cmd) noexcept;

    [[nodiscard]] const icd::SmsStatus& status() const noexcept { return status_; }
    [[nodiscard]] icd::TerminalState state() const noexcept { return status_.state; }
    [[nodiscard]] bus::BitWord bit() const noexcept { return bit_; }
    [[nodiscard]] const Loadout& loadout() const noexcept { return loadout_; }
    [[nodiscard]] icd::MasterArm master_arm() const noexcept { return master_arm_; }
    [[nodiscard]] std::uint8_t selected_station() const noexcept { return selected_; }

    // The master arm the next frame would derive, applied now (for the oracle tool).
    void set_master_arm(icd::MasterArm arm) noexcept;

private:
    [[nodiscard]] icd::CmdStatus arm_station(std::size_t index) noexcept;
    [[nodiscard]] icd::CmdStatus safe_station(std::size_t index) noexcept;
    [[nodiscard]] icd::CmdStatus release(std::size_t index) noexcept;
    void jettison() noexcept;
    [[nodiscard]] bool fms_fresh(std::uint32_t frame) const noexcept;
    void fill_status() noexcept;

    Loadout loadout_{};
    icd::MasterArm master_arm_{icd::MasterArm::SAFE};
    icd::ReleaseMode release_mode_{icd::ReleaseMode::SINGLE};
    icd::DeliveryMode delivery_mode_{icd::DeliveryMode::AUTO};
    std::uint8_t selected_{1};
    std::uint8_t released_{0};
    bool jettisoned_{false};
    icd::FmsStatus fms_{};
    bool have_fms_{false};
    std::uint32_t fms_frame_{0};
    std::uint32_t frame_{0};
    icd::CmdStatus cmd_status_{icd::CmdStatus::NONE};
    icd::SmsStatus status_{};
    std::uint32_t self_test_started_{0};
    bool self_test_running_{false};
    bus::BitWord bit_{};
    bus::CommandSequence mode_seq_{};
    bus::CommandSequence cmd_seq_{};
};

}  // namespace fmofp::stores

#endif
