# SDK version rule

Every commit in this repository must increase the SDK version, unless the person making the change explicitly says not to.

Version file:

- Java Channel: `liveavatar-channel-sdk/pom.xml` (`<version>` of `liveavatar-channel-sdk`)
- Python Channel and Python RTC: `pyproject.toml` (`version = "..."`)

How to increase it:

- Compatible addition or fix: add 1 to the last number. Example: `1.3.1` becomes `1.3.2`.
- Breaking change: add 1 to the middle number and set the last number to 0. Example: `1.3.2` becomes `1.4.0`.

Before committing, tell the person the old version and the new version, and wait for them to agree. Do not choose the skip path yourself.

When the version increases, add one section to both update records:

- `CHANGELOG.md` in English
- `CHANGELOG.zh-CN.md` in Chinese

Use the heading `## [x.y.z] - YYYY-MM-DD`. The date is the release day. Under it, use only `Added`, `Fixed`, or `Changed`. The two languages must describe the same changes.

A version section summarizes every caller-visible change since the previous version bump, including every commit in between. Do not describe only the last commit. If a version has one or two changes, category bullets are enough. If it has more than two, number them `1.` `2.` `3.` across that version so the list is easy to scan.

When a method or configuration gains a parameter, write it in this order: the method or type name, that this is a new or changed parameter, the parameter name, then every allowed value and what that value does. Java enum parameters name the enum type. Python string parameters say they are strings, not enums. Put the protocol event and JSON field after the values. Put cautions in a separate sentence. Do not start with the event name or the JSON field.

Do not list file names, internal refactors, or version-number-only commits. Do not mention earlier numbering mistakes.

`README.md` and `README.zh.md` are the guide, not the changelog. Do not put new release text at the top. Put usage in the existing section for that API, or add a section there when none fits. Do not add a README entry for every field change. Update the README when an example uses the field, when the caller needs the parameter, or when the parameter is important. Keep the English and Chinese guides equivalent.

Every public method and parameter must have a commented call example in the SDK's own example file. The example shows a caller how to use it. Do not run those examples in the normal demo flow. Java uses `liveavatar-channel-server-example` `DemoAgentService`. Python Channel uses `liveavatar_channel_sdk/example/live_avatar_service_simulator.py`. Python RTC uses `examples/basic_agent.py`. A new or changed public method is not done until that commented call is in the same change. If the call is not part of the running demo, the comment is still required.

Skip only after that person explicitly says not to bump the version. Put this exact line in the commit message:

```
SDK-Version-Bump: skip
```

Local Git uses `.githooks/commit-msg`. Each clone must run this once:

```bash
git config core.hooksPath .githooks
```

GitHub Actions runs the same check on pull requests and on pushes to `main`. A commit that does not increase the version fails. Claude Code reads `CLAUDE.md`. Codex, Cursor, and other agents read this file. GitHub Copilot reads `.github/copilot-instructions.md`. All three point at this same rule.
