# SDK version rule

Follow `AGENTS.md` in this repository.

Every commit must increase the SDK version unless the person making the change explicitly says not to bump it. Show the old version and the new version and wait for agreement before committing.

Compatible changes increase the last number (`1.3.1` -> `1.3.2`). Breaking changes increase the middle number and reset the last number to 0 (`1.3.2` -> `1.4.0`).

The version file is `liveavatar-channel-sdk/pom.xml` in the Java SDK, and `pyproject.toml` in the Python SDKs.

Do not skip unless explicitly told. A skip is one line in the commit message: `SDK-Version-Bump: skip`.

When the version increases, add the same caller-visible changes to `CHANGELOG.md` in English and `CHANGELOG.zh-CN.md` in Chinese. Heading: `## [x.y.z] - YYYY-MM-DD`. Categories: `Added`, `Fixed`, `Changed`. Summarize every change since the previous version bump. One or two changes may use category bullets. More than two changes must be numbered `1.` `2.` `3.` For a new or changed parameter, name the method first, then the parameter, then every allowed value and its effect. Do not start with the event name or JSON field. The commit is rejected if either file lacks that heading. Put README usage in the existing API section, not at the top. Every public method needs a commented call example in the SDK example file, and that example must not run in the normal demo flow.

Install the local check once per clone:

```bash
git config core.hooksPath .githooks
```
