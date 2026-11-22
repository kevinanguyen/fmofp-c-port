# 11. The Bus: Messages, the ICD and the Tools That Read It

**Navigation:** [← Flight Management](10_Flight_Management_Integration.md) | [Table of Contents](00_Title_and_TOC.md) | [Operating Procedures →](12_Operational_Procedures.md)

---

The old Python messaging (`local_messaging`, the Python `MIL_STD_1553B` library, the messengers and handlers) is
retired. Every program now talks over one simulated MIL-STD-1553B bus run by one bus controller. This chapter says
how the bus works and how to look at it.

## 11.1 The interface control document (ICD)

`B20SS/icd/fmofp_icd.xml` defines every terminal, enum, message, field, relay and block. It is the only definition: the
C++ structs, encoders and decoders (`ofp/build/<preset>/icd/generated`) and the Python message classes
(`fmofp_bus/icd/`) are generated from it.

| File | What it is |
|---|---|
| `icd/fmofp_icd.xml` | the source of truth (version 1.29 today) |
| `icd/ICD_TABLES.md` | every message, field by field, generated |
| `icd/README.md` | the conventions, every decision, every departure from the frozen Python (section 2), the backlog (section 12) |
| `icd/tools/icd_tool.py` | `check`, `render`, `gen-py`, `gen-cpp` |

```bash
py icd/tools/icd_tool.py check
```

prints the counts: 28 terminals, 168 message definitions, 24 block streams, 9 mode codes.

## 11.2 Words, messages and blocks

- A **message** is up to 32 words. Each field has its word and bits, a type (unsigned, signed, enum, boolean, SSM) and,
  for a scaled value, its least significant bit and range. A value out of range encodes CLAMPED to its limit.
- A **block** carries anything longer (a radar's products, an image, a plan): a descriptor and segments of 31 payload
  words with a CRC; a version number tells a consumer when a new block is complete.
- **SSM**: every measured value has a two-bit validity beside it. NO_COMPUTED_DATA means unknown or stale.

## 11.3 Who sends what

- **Periodic messages** are polled by the controller at their rate. A message with one consumer is relayed into that
  consumer's own receive subaddress; one with several is broadcast to RT 31, and each listener accepts only the
  broadcast subaddresses it listens to.
- **Commands** are aperiodic receive messages with a `cmd_seq`. A terminal acts on a command only when its number
  differs from the last one it accepted. Senders keep to their own number ranges so they never collide: the display
  windows count 1 to 100 (and withdraw a command after a second), the bus controller numbers its clients' commands
  101 to 200, the demo's script uses 201 and up.
- **Mode codes**: synchronise (every frame), reset, self test, and the others MIL-STD-1553B defines.

## 11.4 The controller's ports

| Port | What |
|---|---|
| `port_base + RT` | each terminal's socket |
| `port_base + 32` | the controller |
| `port_base + 33` | the fixed monitor port: a copy of every transaction (one listener; the demo's dashboard takes it) |
| `port_base + 34` | the command port: a client queues a command (the controller numbers it if `cmd_seq` is 0 and answers with the frame and the number given), or asks for its own copy of the monitor stream (up to four clients, renewed every second) |

The port base is 51000 unless `--port-base` says otherwise.

## 11.5 Tools that read the bus

- **The demo's dashboard**: one line a second per subsystem (chapter 12).
- **The prompt** `py -m fmofp_cli`: `terminals`, `status`, `msgs`, `msg ID`, `send`, `do`, `mode` (chapter 12).
- **The recorder** `py -m fmofp_recorder`: the services' database tables from the bus (chapter 12).
- **`fmofp_bc --report`**: per terminal the transactions, retries, missed answers, mean and worst answer times and the
  overrun frames it held up; the demo writes it to `logs/demo/bc.log`.
- **`fmofp_bc --schedule --rt ...`**: the schedule and its load estimate, frame by frame.
- **Python**: `fmofp_bus.bus_view.BusView` (the latest decoded message of every kind) and `fmofp_bus.monitor.Monitor`
  for scripts and tests.

## 11.6 Tests

`fmofp_bus/tests/test_word.py`, `test_command_word.py`, `test_transport.py`, `test_remote_terminal.py`,
`test_block.py`, `test_bus_integration.py`, `test_messages.py` (the counts and the relays), `test_command_port.py`;
`ofp/tests/` for the C++ side and the generated round-trip tests; `test bus` from the prompt (upstream's
`test_1553b`).
