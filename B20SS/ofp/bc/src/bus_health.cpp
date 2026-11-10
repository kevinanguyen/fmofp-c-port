#include <fmofp/bc/bus_health.hpp>

namespace fmofp::bc {

namespace {

struct Masks {
    std::uint32_t listed{0};
    std::uint32_t responded{0};
    std::uint32_t answering{0};
    std::uint32_t status{0};
    std::uint32_t healthy{0};
    std::uint32_t bit_failed{0};
    std::uint32_t normal{0};
    std::uint32_t degraded{0};
    std::uint32_t failure{0};
};

std::uint16_t high(std::uint32_t mask) noexcept { return static_cast<std::uint16_t>(mask >> 16U); }
std::uint16_t low(std::uint32_t mask) noexcept { return static_cast<std::uint16_t>(mask & 0xFFFFU); }

// The terminal's last TERM_STATUS, if the controller holds one that is fresh.
bool fresh_status(const BusController& controller, std::uint8_t rt, icd::TermStatus& out) noexcept {
    icd::TermStatus::Words words{};
    std::uint8_t count = 0;
    std::uint32_t frame = 0;
    if (controller.get_latest(rt, icd::TermStatus::kSubaddress, words.data(), icd::TermStatus::kWords, count,
                              frame) != Status::kOk ||
        count != icd::TermStatus::kWords || controller.stats().frames - frame > kTermStatusStaleFrames) {
        return false;
    }
    // A TERM_STATUS whose state is not in the ICD still tells the rest.
    (void)icd::TermStatus::decode(words, out);
    return true;
}

void add_status(const icd::TermStatus& status, std::uint32_t bit, Masks& masks) noexcept {
    masks.status |= bit;
    if (status.healthy) {
        masks.healthy |= bit;
    }
    if (status.bit_failed) {
        masks.bit_failed |= bit;
    }
    if (status.state == icd::TerminalState::NORMAL) {
        masks.normal |= bit;
    } else if (status.state == icd::TerminalState::DEGRADED) {
        masks.degraded |= bit;
    } else if (status.state == icd::TerminalState::FAILURE) {
        masks.failure |= bit;
    } else {
        // Every other state reads as neither of the three.
    }
}

}  // namespace

Status BusHealthReporter::report(BusController& controller) noexcept {
    Masks masks;
    const BcConfig& cfg = controller.config();
    for (std::uint8_t i = 0; i < cfg.terminal_count; ++i) {
        const std::uint8_t rt = cfg.terminals[i];
        if (rt >= bus::kBroadcastRt) {
            continue;
        }
        const std::uint32_t bit = std::uint32_t{1} << rt;
        const TerminalStats& stats = controller.terminal(rt);
        masks.listed |= bit;
        if (stats.responded) {
            masks.responded |= bit;
            if (stats.no_response == no_response_[rt]) {
                masks.answering |= bit;
            }
        }
        no_response_[rt] = stats.no_response;
        icd::TermStatus status{};
        if (fresh_status(controller, rt, status)) {
            add_status(status, bit, masks);
        }
    }

    // 1-255: 0 is "no report yet" to the receiver.
    epoch_ = static_cast<std::uint8_t>(epoch_ == 255U ? 1U : epoch_ + 1U);
    last_ = icd::AvnBusHealth{};
    last_.epoch = epoch_;
    last_.listed_mask_hi = high(masks.listed);
    last_.listed_mask_lo = low(masks.listed);
    last_.responded_mask_hi = high(masks.responded);
    last_.responded_mask_lo = low(masks.responded);
    last_.answering_mask_hi = high(masks.answering);
    last_.answering_mask_lo = low(masks.answering);
    last_.status_mask_hi = high(masks.status);
    last_.status_mask_lo = low(masks.status);
    last_.healthy_mask_hi = high(masks.healthy);
    last_.healthy_mask_lo = low(masks.healthy);
    last_.bit_failed_mask_hi = high(masks.bit_failed);
    last_.bit_failed_mask_lo = low(masks.bit_failed);
    last_.normal_mask_hi = high(masks.normal);
    last_.normal_mask_lo = low(masks.normal);
    last_.degraded_mask_hi = high(masks.degraded);
    last_.degraded_mask_lo = low(masks.degraded);
    last_.failure_mask_hi = high(masks.failure);
    last_.failure_mask_lo = low(masks.failure);

    icd::AvnBusHealth::Words words{};
    const Status encoded = last_.encode(words);
    if (!ok(encoded)) {
        return encoded;
    }
    return controller.set_receive_data(icd::AvnBusHealth::kRt, icd::AvnBusHealth::kSubaddress, words.data(),
                                       icd::AvnBusHealth::kWords);
}

}  // namespace fmofp::bc
