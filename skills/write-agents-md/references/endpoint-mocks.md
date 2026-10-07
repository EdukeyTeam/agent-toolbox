# Endpoint mocks and real application checks

Preserve this contract when authoring test guidance; detailed endpoint-specific procedures belong in testing skills.

## E2E and Manual QA: zero mocks

Run the fully working application against real backing services. This includes actual LLM provider calls, the real database and endpoint results. No stub providers, fake success, network interception, substituted completions or hidden test-only paths. Real services with isolated synthetic test data are appropriate; services merely simulating the verified endpoint are mocks.

LLM unpredictability makes fabricated completions poor proof that the application works. Verify observable outcomes robustly rather than expecting a particular generated phrase. A passing mock-based integration test is not an E2E or Manual QA result.

## Unit/integration: evidence before mocking an endpoint

Decide whether isolation is useful and state what that layer proves. Integration tests may mock services, including an LLM provider, when meaningful. Every time an endpoint mock/fixture is created or refreshed:

1. Make a fresh real query to the actual endpoint or database in the authorized test environment. Do this for backend, provider and database responses alike.
2. Retrieve the complete response, including its actual envelope, nested objects, types, nulls and optional fields. For streaming endpoints, capture the real complete stream rather than inventing a final object.
3. Save that full raw body verbatim to a file **before** creating the mock. Do not reconstruct from documentation, retype, trim fields, prettify, normalize values or invent an example.
4. Load the mock from that exact captured file; record capture provenance separately (request shape, endpoint/version where relevant, test environment and capture time, without authentication secrets).
5. Check the mocked response matches the captured payload and describe the remaining real-service coverage gap.

An existing fixture is historical evidence; it does not replace the fresh query required to create/refresh a mock, nor prove the current provider still responds that way. An ordinary rerun of a fixture-based test is not a new live capture.

Use synthetic, authorized test data. Do not commit private responses, credentials or customer data. If a response cannot safely become a fixture, use a safe real test scenario or protected untracked storage as authorized; do not silently edit it and call the result a verbatim capture. If the real query is unavailable or its cost/access is not authorized, report the blocker instead of making up the response.
