---
name: Intern ticket
about: One piece of work on the C++ flight software (format in B20SS/ofp/docs/TICKETS.md)
title: "OFP-000: state the fault or the need, not the fix"
labels: intern-ticket
---

<!-- The format, its rules and a ticket written out: B20SS/ofp/docs/TICKETS.md.
     Every field stays; one that does not apply says "none". Run it before you write it. -->

**Kind**: Defect | Feature | Hardening | Investigation
**Level**: 1 (one function) | 2 (one partition) | 3 (crosses the bus)
**Partition**: name, RT number

## Background

Two to five sentences a newcomer can follow: what this part of the aircraft is for and why the behaviour
matters. No solution.

## What happens now

The observed behaviour, with the command that shows it and its pasted output.

```text
$ command
output
```

## What should happen

- A statement that can be checked.
- Another.

## Where to start

Files and function names, ICD message ids, the row in `B20SS/icd/README.md`, the oracle test if one pins this
behaviour. For an Investigation: only the symptom and the command that shows it.

## Done when

- The named tests exist and pass: ...
- If an oracle test pins the old behaviour, it is split as TICKETS.md section 4 says.
- The standing list of TICKETS.md section 3 holds (build, tests, cppcheck, lint, coverage, `verify.sh`,
  documents, one commit on `ticket/OFP-<number>`, a reviewed pull request).

## Out of scope

What must not change while here.

## Hints

none
