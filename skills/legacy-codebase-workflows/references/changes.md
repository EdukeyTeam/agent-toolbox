# Optional startup, tests, features and modernization

Choose the route requested by the user. Investigation does not authorize repairing the app or upgrading its dependencies. A feature request does not require modernizing the entire repository.

## Startup diagnosis

Read the original build descriptors and runtime assumptions before running commands. Establish the required Java/runtime version, dependency sources, native/system components, network needs and environment variable names without exposing values. Use an isolated environment when the old runtime differs from the developer's normal toolchain.

Run the existing startup/build path when within the requested task and environment permissions. Record the exact failure and the smallest hypothesis it tests. Fix the minimum startup blocker before unrelated upgrades; preserve the failure and working command as evidence. Build tools can execute project code, so do not run them merely to generate a map.

## Characterization tests

Choose observable behavior affected by the proposed change: outputs, protocol interactions, persistence, error cases and meaningful invariants. If the original cannot build, either use its compatible runtime or first make the minimum startup repair; do not claim tests passed on an unbuildable baseline.

Verify tests against the baseline. Keep them independent of incidental implementation details. After a change, resolve failures by inspecting intended behavior before changing assertions. Do not weaken a behavior test merely to make the new implementation pass.

## Feature or modernization

Trace the behavior and framework conventions using source evidence. For a substantial new feature, capture requirements and out-of-scope boundaries; write a feature PRD or ADR when those decisions help. A legacy repository does not need a new whole-application PRD as a prerequisite.

Make small reviewable changes and run checks appropriate to the affected behavior. Modernization, runtime/dependency upgrades, architectural replacement and UI redesign require their own requested scope. Use incremental compatibility changes and preserve a verified baseline; apply patterns such as strangler migration only when the application needs them.

Keep documentation/evidence current for changed APIs. Report what changed, verification performed and remaining blockers, with commands that someone else can reproduce.
