# Edukey Agent Toolbox

This public repository contains skills created by [Edukey](https://edukey.ai) for its course participants, clients, and anyone else using AI agents. The first collection serves developers; business skills will follow. We plan to package useful collections as agent plugins so people can install several skills together. Keep every contribution generic enough to share publicly and useful across supported agents and operating systems.

The [README](README.md) is for people discovering and installing the toolbox. Keep its skill list and install examples accurate when adding or renaming skills. This file guides agents contributing to the repository.

## Skills

- Put each skill in `skills/<name>/SKILL.md`. The folder name and the YAML frontmatter `name` must match. Include a `description` that makes clear when an agent should use the skill.
- Keep scripts and occasional reference material beside the skill in `scripts/` and `references/`. Instructions needed on every run belong in `SKILL.md`; one-time setup belongs in a referenced file.
- Add only skills we authored. Install third-party skills from their original source instead of copying them here. An authored skill may bundle an adapted upstream code library when its license permits this; pin its provenance, document changes and preserve all required licenses and notices. This does not permit copying a third-party skill.
- Do not include secrets, client-specific information, private repository paths, or machine-specific assumptions in public skills.
- Edit the source in this repository, then reinstall or update the skill. Do not patch an installed `.agents/skills/` or `.claude/skills/` copy.
- `skills/` is also the source for the Claude and Copilot plugin bundles. Do not copy skill folders into plugin-specific directories. Keep the root `plugin.json`, Claude `.claude-plugin/plugin.json`, and marketplace entry consistent when changing the plugin name or description.

## Changes and checks

- Work on a branch and open a pull request. Do not push skill changes directly to `main`. Get human and AI review before merging a skill change.
- Every new skill is checked by the repository-wide structure test. Add focused automated tests for its scripts and other testable behavior, including regression cases for bugs. For a skill with no executable behavior, describe a realistic manual trial in the pull request.
- Put Node tests in `tests/` with a `.test.cjs` or `.test.js` suffix. Run `npm ci` and `npm test` locally. The [Node test workflow](.github/workflows/test-skills.yml) discovers these tests automatically. Separate validation workflows use built-in `paths` filters on pull requests and pushes to `main`; update their input patterns when adding runtime/test dependencies. See [CI scope](docs/ci.md).
- If a new skill needs tests in another language or an extra setup step, update the workflow in the same pull request so CI actually runs them. Check the workflow result before merging.
- The Claude ZIP builder discovers all `skills/*/SKILL.md` folders. The [plugin workflow](.github/workflows/test-plugin.yml) builds and checks that ZIP when skill or plugin payload dependencies change; update the builder and its checks if the skill layout changes.
