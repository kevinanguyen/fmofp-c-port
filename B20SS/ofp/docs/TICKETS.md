# Intern tickets: the format

> **DRAFT, 2026-11-12, for Alee and Kevin to review.** Nothing here is decided. The open questions are at the
> end; change anything, then remove this box.

A ticket is one piece of work on the C++ flight software that one intern can finish and prove finished. This
page says what a ticket carries, what "done" means for every ticket, and shows one written out. Read
`ARCHITECTURE.md` and `DEBUGGING.md` first: a ticket assumes both.

## 1. Where tickets come from

The port kept the Python's behaviour, defects included, and wrote each one down. Those records are the ticket
supply:

| Source | What is there | Kind of ticket it makes |
|---|---|---|
| `B20SS/icd/README.md` section 2 | every quirk kept and every departure made, with the oracle test that proves the Python's behaviour | **Defect**: the code does what the Python did, and that is wrong |
| `B20SS/icd/README.md` section 12 | the backlog: things the port left out on purpose | **Feature**: something the aircraft should do and does not |
| The lint, cppcheck, the coverage floors, the timing test | a rule held by a tool | **Hardening**: a module below its floor, a check to add, a slow answer |
| A hidden fault put into a branch by the author | nothing, by design | **Investigation**: find it with the debugger, then fix it |

## 2. What a ticket carries

A ticket is an issue on the tracker, opened from the "Intern ticket" template
(`.github/ISSUE_TEMPLATE/intern-ticket.md`), which lays these fields out. Every ticket has these fields, in this order. A field that does not apply says "none", it is not left out.

| Field | What goes in it |
|---|---|
| **ID and title** | `OFP-<number>`, and a title that states the fault or the need, not the fix ("The fitness check never fires", not "Change == to >=") |
| **Kind** | Defect, Feature, Hardening or Investigation (section 1) |
| **Level** | 1 (one function, one file), 2 (one partition, perhaps its tool and tests), 3 (crosses the bus: the ICD, two programs, a display) |
| **Partition** | the subsystem and its terminal number, for example "avionics, RT 1" |
| **Background** | Two to five sentences a newcomer can follow: what this part of the aircraft is for and why the behaviour matters. No solution |
| **What happens now** | The observed behaviour, with a way to see it that was run by the author: a command and its output |
| **What should happen** | The required behaviour as statements that can be checked. For a Defect, the requirement, not the code change |
| **Where to start** | Files and function names, the ICD message ids involved, the README row. For an Investigation: only the symptom and the command that shows it |
| **Done when** | The acceptance list: the tests that must exist and pass, named, plus the standing list of section 3 |
| **Out of scope** | What the intern must not change while here (other quirks nearby, the frozen Python, the ICD if the ticket is level 1 or 2) |
| **Hints** | Optional, and collapsed or on a separate page: given on request, each one costs nothing but is recorded |

Rules for the author:

- **Run it before you write it.** "What happens now" is pasted output, not a description from memory.
- **One fault a ticket.** Two quirks in one function are two tickets; say in "Out of scope" that the other stays.
- **Name the oracle.** Most Defect tickets change behaviour an oracle test pins to the Python's. The ticket
  says which test, and that changing it is part of the work (section 4).
- **Level 3 needs a reviewer who knows the ICD.** A change to `fmofp_icd.xml` moves both programs' generated
  code, the message counts and the load.

## 3. Done, for every ticket

A ticket is done when all of this is true, from `B20SS/ofp/` unless said otherwise:

1. A test fails without the change and passes with it (a GoogleTest in `tests/`, and the Python test named in
   the ticket if it has one).
2. `cmake --build --preset <preset>` is clean (every warning is an error) and `ctest --preset <preset>` passes.
3. `cmake --build build/<preset> --target cppcheck` and `--target lint` report nothing. No `// NOLINT` and no
   suppression without a reason on the line that a reviewer accepts.
4. `cmake --preset coverage && cmake --build --preset coverage` keeps every module at its floor.
5. `bash B20SS/verify.sh` from the repository root is green.
6. The documents say what the code now does: the row in `B20SS/icd/README.md` section 2 (or the section 12
   item struck), `ofp/README.md` if a command line or a message changed.
7. One commit on a branch `ticket/OFP-<number>`, its message saying what was wrong, what changed and how it
   was tested, and a pull request into `port/cpp` that a reviewer approves.

`B20SS/ofp/CLAUDE.md` holds the coding rules the review checks.

## 4. Changing behaviour the oracle pins

An oracle test runs the frozen Python beside the C++ and demands the same answer. A Defect ticket makes them
differ on purpose, so the test is split, never deleted:

- the part that proves **what the Python does** stays, against the Python alone (it is the evidence for the
  README's row);
- the part that compared the two is replaced by a test of **the required behaviour** against the C++;
- the README's section 2 row moves from "kept as written" to a departure, with the ticket's id.

The frozen Python under `B20SS/FMOFP/` is never edited.

## 5. A ticket written out

> ### OFP-001: The flight management fitness check never fires
>
> **Kind** Defect · **Level** 1 · **Partition** avionics, RT 1
>
> **Background.** The avionics computer watches three flight management components and grades each one OK,
> WARNING or CRITICAL from its processor and memory use. The grades go to the EICAS in `AVN_STATUS`, where the
> crew would see a computer in trouble before it fails.
>
> **What happens now.** A component at 99 % processor use is graded OK. From `B20SS/ofp/build/windows-ucrt64`:
>
> ```text
> $ printf 'fitness 99 99\nfitness 90 10\nfitness 80 10\nfitness 81 10\n' | partitions/fmofp_avionics_tool.exe
> OK
> CRITICAL
> WARNING
> OK
> ```
>
> Only a reading exactly on a threshold is graded.
>
> **What should happen.**
> - A reading at or above the critical threshold of either measure is CRITICAL.
> - Otherwise a reading at or above the warning threshold of either measure is WARNING.
> - Otherwise OK.
>
> **Where to start.** `FmFitness::check_thresholds` in `partitions/avionics/src/avionics.cpp`; the test
> `AvionicsFmFitness.EqualityNotAThreshold` in `tests/avionics_test.cpp`; the row "The fitness check is an
> equality" in `B20SS/icd/README.md` section 2; the oracle `test_check_thresholds_is_an_equality` in
> `B20SS/fmofp_bus/tests/test_avionics_oracle.py`.
>
> **Done when.** The same four lines print CRITICAL, CRITICAL, WARNING, WARNING. A GoogleTest covers a reading
> below, on and above each threshold for each measure. The oracle test is split as section 4 says. The README
> row is a departure naming OFP-001. Section 3 holds.
>
> **Expect this side effect.** The readings the terminal grades are fixed placeholders, processor 75 and memory
> 80, and the memory warning threshold is 75: once the check is a threshold, all three components read WARNING
> on the bus and on the EICAS, for good. That is the fixed rule judging a placeholder, not a new fault. Say so
> in the pull request, and update any test that expected OK in `AVN_STATUS` (find them: `verify.sh` will).
>
> **Out of scope.** Feeding the check real readings instead of the placeholders is another ticket.
> `handle_redundancy` stays as it is.
>
> **Hints.** (1) Put a breakpoint on `check_thresholds` and run the tool with `fitness 99 99` (`DEBUGGING.md`
> section 3). (2) Read the comparison operators.

The example's output was run as shown, and its side effect was found by running it: the author who writes
"What happens now" from memory would have promised the status on the bus stays OK.

## 6. Open questions for Alee and Kevin

1. **Where do tickets live?** *Answered, Alee, 2026-11-12: issues on the tracker.* The fields of section 2 are
   the issue template `.github/ISSUE_TEMPLATE/intern-ticket.md` (label `intern-ticket`); a ticket's id is in
   its title. *The tracker, Alee, 2026-11-12: the fork's GitHub*, `kevinanguyen/fmofp-c-port`, beside the
   code and its pull requests. **To do, Kevin (the owner)**: issues are switched off there, a GitHub default
   for forks: turn them on under Settings > General > Features > Issues, and create the label
   `intern-ticket`. Until then the template shows nowhere.
2. **Hints**: in the ticket, on a separate page the mentor holds, or none?
3. **Are Investigation tickets wanted** (a fault planted on a branch for the intern to find)? They teach the
   debugger best and cost the author the most.
4. **Do interns work by pull request into `port/cpp`**, as section 3 item 7 assumes, or on their own forks, or on
   a training branch that is never merged, so every intern can be given the same ticket?
5. **Is the level scale (1-3) enough**, or is an estimate in hours wanted as well?
6. **The Python-era SSTR tickets** are not in this repository. If their format should be followed, or their
   numbering continued, one of them is needed as a model.
