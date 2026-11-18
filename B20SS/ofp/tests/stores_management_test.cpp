// The stores management terminal against sms.py: the default loadout, the
// master-arm rule, the load and armed count with their quirk; and the new
// commands (select, modes, arm, safe, release, jettison) with their refusals.
#include <gtest/gtest.h>

#include <cstdint>

#include <fmofp/stores/stores_management.hpp>

namespace {

using fmofp::Status;
using namespace fmofp::stores;  // NOLINT: test
using namespace fmofp::icd;     // NOLINT: test

FmsStatus fms_with(WeaponsState weapons) {
    FmsStatus f{};
    f.weapons = weapons;
    return f;
}

struct Sms {
    StoresManagement sms;
    std::uint8_t seq{0};

    Sms() { EXPECT_EQ(Status::kOk, sms.init()); }

    CmdStatus send(SmsCommand command, std::uint8_t station = 0, ReleaseMode release = ReleaseMode::SINGLE,
                   DeliveryMode delivery = DeliveryMode::AUTO) {
        SmsCmd cmd{};
        cmd.cmd_seq = ++seq;
        cmd.command = command;
        cmd.station = station;
        cmd.release_mode = release;
        cmd.delivery_mode = delivery;
        sms.command(cmd);
        return sms.status().sms_cmd_status;
    }

    void arm_master(std::uint32_t frame = 1) {
        const FmsStatus f = fms_with(WeaponsState::ARMED);
        sms.step(&f, frame);
    }
};

TEST(StoresManagement, TheDefaultLoadoutAndItsSums) {
    const Loadout l = default_loadout();
    EXPECT_EQ(StoreKind::MK_82, l[0].kind);
    EXPECT_EQ(StoreState::ARMED, l[0].state);
    EXPECT_EQ(4U, l[0].qty);
    EXPECT_EQ(StoreState::EMPTY, l[3].state);
    EXPECT_EQ(StoreKind::AN_ALQ, l[10].kind);
    // 227x4 + 910x2 + 1021 + 227x4 + 910x2 + 1021 + 8x8 x2 + 180: the empty bays not counted.
    EXPECT_EQ(7806.0, total_weight_kg(l));
    EXPECT_EQ(2U, armed_count(l));
}

TEST(StoresManagement, ACarriedStoreWithNoneLeftWeighsOne) {
    Loadout l = default_loadout();
    l[1].qty = 0;  // JDAM, SAFE, none left: max(qty, 1) counts one
    EXPECT_EQ(7806.0 - 910.0, total_weight_kg(l));
    l[1].state = StoreState::EXPENDED;
    EXPECT_EQ(7806.0 - 1820.0, total_weight_kg(l));
}

TEST(StoresManagement, TheMasterArmFollowsTheWeaponsState) {
    EXPECT_EQ(MasterArm::SAFE, master_arm_from(nullptr));
    FmsStatus f = fms_with(WeaponsState::ARMED);
    EXPECT_EQ(MasterArm::ARMED, master_arm_from(&f));
    f.weapons = WeaponsState::READY;
    EXPECT_EQ(MasterArm::TRAIN, master_arm_from(&f));
    f.weapons = WeaponsState::SAFE;
    EXPECT_EQ(MasterArm::SAFE, master_arm_from(&f));
}

TEST(StoresManagement, TheTerminalFollowsTheFmsAndGoesSafeWithoutIt) {
    Sms s;
    EXPECT_EQ(TerminalState::INITIALIZING, s.sms.state());
    s.arm_master(1);
    EXPECT_EQ(TerminalState::NORMAL, s.sms.state());
    EXPECT_EQ(MasterArm::ARMED, s.sms.status().master_arm);
    EXPECT_TRUE(s.sms.status().fms_valid);
    s.sms.step(nullptr, 100);
    EXPECT_EQ(MasterArm::ARMED, s.sms.master_arm());
    s.sms.step(nullptr, 101);
    EXPECT_EQ(MasterArm::SAFE, s.sms.master_arm());
    EXPECT_FALSE(s.sms.status().fms_valid);
    EXPECT_EQ(TerminalState::DEGRADED, s.sms.state());
}

TEST(StoresManagement, SelectAndTheModes) {
    Sms s;
    EXPECT_EQ(1U, s.sms.status().selected_station);
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::SELECT_STATION, 5));
    EXPECT_EQ(5U, s.sms.status().selected_station);
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, s.send(SmsCommand::SELECT_STATION, 12));
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, s.send(SmsCommand::SELECT_STATION, 0));
    EXPECT_EQ(5U, s.sms.status().selected_station);
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::SET_RELEASE_MODE, 0, ReleaseMode::SALVO));
    EXPECT_EQ(ReleaseMode::SALVO, s.sms.status().release_mode);
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::SET_DELIVERY_MODE, 0, ReleaseMode::SINGLE, DeliveryMode::CCRP));
    EXPECT_EQ(DeliveryMode::CCRP, s.sms.status().delivery_mode);
    EXPECT_EQ(ReleaseMode::SALVO, s.sms.status().release_mode) << "the delivery command leaves the release mode";
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, s.send(SmsCommand::NONE));
}

TEST(StoresManagement, ArmAndSafeOnlyWeaponsWithStoresLeft) {
    Sms s;
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::ARM_STATION, 2));  // JDAM, SAFE
    EXPECT_EQ(StoreState::ARMED, s.sms.loadout()[1].state);
    EXPECT_EQ(3U, s.sms.status().armed_count);
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::ARM_STATION, 2)) << "already armed";
    EXPECT_EQ(CmdStatus::REJECTED_STATE, s.send(SmsCommand::ARM_STATION, 4)) << "an empty bay";
    EXPECT_EQ(CmdStatus::REJECTED_STATE, s.send(SmsCommand::ARM_STATION, 9)) << "a decoy is READY, not a weapon";
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::SAFE_STATION, 1));
    EXPECT_EQ(StoreState::SAFE, s.sms.loadout()[0].state);
    EXPECT_EQ(CmdStatus::REJECTED_STATE, s.send(SmsCommand::SAFE_STATION, 11)) << "a pod is READY";
    EXPECT_EQ(CmdStatus::REJECTED_INVALID, s.send(SmsCommand::ARM_STATION, 13));
    EXPECT_EQ(2U, s.sms.status().armed_count);
}

TEST(StoresManagement, ReleaseNeedsTheMasterArmAndAnArmedStation) {
    Sms s;
    EXPECT_EQ(CmdStatus::REJECTED_STATE, s.send(SmsCommand::RELEASE)) << "master arm SAFE";
    const FmsStatus train = fms_with(WeaponsState::READY);
    s.sms.step(&train, 1);
    EXPECT_EQ(CmdStatus::REJECTED_STATE, s.send(SmsCommand::RELEASE)) << "TRAIN releases nothing";
    s.arm_master(2);
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::RELEASE));  // station 1, SINGLE
    EXPECT_EQ(3U, s.sms.loadout()[0].qty);
    EXPECT_EQ(1U, s.sms.status().stores_released);
    EXPECT_EQ(7806.0 - 227.0, s.sms.status().total_weight);
    EXPECT_EQ(CmdStatus::REJECTED_STATE, s.send(SmsCommand::RELEASE, 2)) << "SAFE station";
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::SET_RELEASE_MODE, 0, ReleaseMode::RIPPLE));
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::RELEASE, 5));
    EXPECT_EQ(2U, s.sms.loadout()[4].qty);
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::SET_RELEASE_MODE, 0, ReleaseMode::SALVO));
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::RELEASE, 1));
    EXPECT_EQ(0U, s.sms.loadout()[0].qty);
    EXPECT_EQ(StoreState::EXPENDED, s.sms.loadout()[0].state);
    EXPECT_EQ(6U, s.sms.status().stores_released);
    EXPECT_EQ(1U, s.sms.status().armed_count);
    EXPECT_EQ(CmdStatus::REJECTED_STATE, s.send(SmsCommand::RELEASE, 1)) << "expended";
}

TEST(StoresManagement, JettisonDropsEveryStoreLeft) {
    Sms s;
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::JETTISON)) << "whatever the master arm";
    for (const Station& st : s.sms.loadout()) {
        EXPECT_TRUE(st.state == StoreState::JETTISONED || st.state == StoreState::EMPTY);
        EXPECT_EQ(0U, st.qty);
    }
    EXPECT_EQ(StoreState::EMPTY, s.sms.loadout()[3].state) << "an empty bay stays empty";
    EXPECT_TRUE(s.sms.status().jettisoned);
    EXPECT_EQ(0.0, s.sms.status().total_weight);
    EXPECT_EQ(0U, s.sms.status().armed_count);
}

TEST(StoresManagement, TheCommandRuleAndTheModeCommand) {
    Sms s;
    SmsCmd cmd{};
    cmd.cmd_seq = 9;
    cmd.command = SmsCommand::SELECT_STATION;
    cmd.station = 3;
    s.sms.command(cmd);
    cmd.station = 4;
    s.sms.command(cmd);  // the same number: not a new command
    EXPECT_EQ(3U, s.sms.status().selected_station);
    EXPECT_EQ(9U, s.sms.status().cmd_seq_last_sms);

    SmsModeCmd mode{};
    mode.cmd_seq = 1;
    mode.requested_state = TerminalState::STANDBY;
    s.sms.command_mode(mode);
    EXPECT_EQ(TerminalState::STANDBY, s.sms.state());
    mode.cmd_seq = 2;
    mode.requested_state = TerminalState::FAILURE;
    s.sms.command_mode(mode);
    EXPECT_TRUE(s.sms.status().cmd_rejected);
}

TEST(StoresManagement, TheSelfTestAndTheResetAndTheEncoding) {
    Sms s;
    s.sms.start_self_test();
    s.sms.step(nullptr, 1);
    s.sms.step(nullptr, 11);
    EXPECT_FALSE(s.sms.bit().in_progress);
    s.arm_master(12);
    EXPECT_EQ(CmdStatus::COMPLETED, s.send(SmsCommand::RELEASE));
    SmsStatus::Words w{};
    ASSERT_TRUE(fmofp::ok(s.sms.status().encode(w)));
    SmsStatus back{};
    ASSERT_EQ(Status::kOk, SmsStatus::decode(w, back));
    EXPECT_EQ(3U, back.station_1_qty);
    EXPECT_EQ(StoreKind::AN_ALQ, back.station_11_kind);
    EXPECT_EQ(StoreState::READY, back.station_9_state);
    EXPECT_EQ(MasterArm::ARMED, back.master_arm);
    s.sms.reset();
    EXPECT_EQ(4U, s.sms.loadout()[0].qty);
    EXPECT_EQ(0U, s.sms.status().stores_released);
}

TEST(StoresManagement, TheUnitWeights) {
    EXPECT_EQ(227.0, unit_weight_kg(StoreKind::MK_82));
    EXPECT_EQ(1021.0, unit_weight_kg(StoreKind::JASSM));
    EXPECT_EQ(0.0, unit_weight_kg(StoreKind::NONE));
    EXPECT_TRUE(is_weapon(StoreKind::JDAM));
    EXPECT_FALSE(is_weapon(StoreKind::ALE_55));
}

}  // namespace
