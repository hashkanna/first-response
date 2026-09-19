# Investigator modes

`INVESTIGATOR_BACKEND=local` is the default and needs no credentials. It matches
two authored fault scenarios against actual exceptions and changed runtime
source. Reproductions, candidate tests, and post-approval tests still execute.

`INVESTIGATOR_BACKEND=gemini` uses Pydantic AI to send the actual exception, the
actual source diff, and numbered runtime Python files to Gemini. It produces a
typed `GroundedRootCause`. The model must select the causal changed file, line,
service, and fault mechanism; it must cite both the exception and deploy diff
using exact evidence IDs and exact supporting quotations. Validation retries are
bounded to three model requests and the entire analysis to 45 seconds. Invalid
analysis or provider failures stop the incident with `no_fix_found`; the hub
never silently substitutes the local explanation.

The default analysis model is `gemini-3.8-flash`; override it with
`GEMINI_INVESTIGATOR_MODEL`. Google documents this identifier as stable with
structured-output support. This analysis is separate from `gemini-3.8-live`,
which handles the optional real-time voice conversation.

Repair selection is configured separately. `REPAIR_BACKEND=authored` uses the
reviewed strategies. `REPAIR_BACKEND=gemini` asks a second Pydantic AI agent to
derive three bounded source edits from the actual evidence and broken code; it
requires `VERIFICATION_BACKEND=modal`. The generator is not shown the authored
candidate library. All generated execution, including recovery probes, occurs
inside Modal. See [Generated repairs](GENERATED_REPAIRS.md) for the edit boundary,
source fingerprinting, receipts, and approval behavior.

The model's diagnosis or proposed edit does not establish that a fix works. Each
candidate must independently pass its reproduction and 24 regression tests.
Every application still requires explicit operator approval and a second
verification after application. Any number of generated candidates may pass,
including all three; failures are never engineered for presentation.

## Configuration

The hub loads the repository `.env` with `python-dotenv`, without overriding
existing process variables. It never prints its contents. Configure one of:

```dotenv
INVESTIGATOR_BACKEND=gemini
GEMINI_INVESTIGATOR_MODEL=gemini-3.8-flash
GEMINI_API_KEY=your-secret-key
VERIFICATION_BACKEND=modal
REPAIR_BACKEND=gemini
```

Or use Google Cloud credentials:

```dotenv
INVESTIGATOR_BACKEND=gemini
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
VERIFICATION_BACKEND=modal
REPAIR_BACKEND=gemini
```

The latter needs working Application Default Credentials and access to the
configured model in that project. `/health` reports selected backends and
configuration availability; configuration is not proof of a successful cloud
request. Successful Gemini analyses write a non-secret receipt with model name,
actual usage counts, typed output, and incident ID to `.runtime/investigator.json`.

Only the toy shop's Python source and local fault evidence go to Gemini. API
keys remain on the server and are excluded from verification subprocesses and
Modal snapshots. The local verifier is suitable only for these trusted authored
fixtures; it is not a security sandbox for generated or untrusted code.

Official references checked during implementation:

- [Google: Gemini 3.8 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Pydantic AI: Google models and providers](https://pydantic.dev/docs/ai/models/google/)
