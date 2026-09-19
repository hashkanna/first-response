# First Response

First Response is a voice incident commander that turns a failing checkout into an evidence-backed repair. The operator stays in conversation while an independent agent investigates, generates competing patches and tests them.

Our demo injects real faults into a Python shop: a payment timeout reduced from 3,000 milliseconds to three, and an optional coupon accessed without a guard. Pydantic AI validates Gemini's diagnosis against actual traces, source locations and quoted evidence. A second Gemini agent derives three edits from the broken source, without receiving a library of fixes.

Each candidate runs in its own network-disabled Modal Sandbox against a failing reproduction and 24 unchanged regression tests. In the measured timeout run, two generated repairs passed all 25 checks. A third passed the reproduction but failed timeout enforcement. The interface exposed that failure and withheld approval.

The operator reviewed and approved the 3,000-millisecond repair. Fresh Modal recovery passed 25 tests and twelve checkout probes. Generated code never executes on the host, and source fingerprints reject stale approvals.

Gemini Live supports streaming speech, interruption and typed conversation. Actual synthetic-audio checks verified transcription, spoken output, negation and reconnect.

The prototype covers controlled faults. Its contribution is a complete, inspectable loop: evidence, generation, isolated verification, human approval and measured recovery.

## Submission fields

- Project: First Response
- Track: Open Innovation
- Technologies: Google DeepMind, Modal, Pydantic
- Side challenges: Best use of Modal; Best use of Pydantic
- Repository: pending publication
- Video: pending export

The registered team in the organizer dashboard is currently Olympiad Commentator. This document does not rename that team or submit the project.
