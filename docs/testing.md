# Running the repository tests

Use Python 3.10 or newer and install the test-only dependency:

```sh
python3 -m pip install -r requirements-test.txt
```

On Linux, immutable verification requires `bubblewrap` (`bwrap`) and permission
to create its sandbox namespaces. Ubuntu CI installs the distribution package:

```sh
sudo apt-get update
sudo apt-get install --yes bubblewrap
bwrap --die-with-parent --ro-bind / / --proc /proc --dev /dev /bin/true
```

The last command is a fail-fast environment check. Do not disable AppArmor,
run the tests as root, or bypass the verification boundary to make it pass.
Ubuntu 24.04 also restricts user namespaces. CI loads the upstream AppArmor
`bwrap-userns-restrict` policy (ABI 4.0, commit and SHA-256 pinned in the workflow).
It permits sandbox setup but strips capabilities from the child commands; no
global namespace restriction is disabled. This setup is for the disposable
GitHub-hosted runner, not an instruction to overwrite a workstation's policy.
See [Ubuntu's explanation](https://discourse.ubuntu.com/t/understanding-apparmor-user-namespace-restriction/58007)
and the [pinned upstream policy](https://gitlab.com/apparmor/apparmor/-/blob/53074bb9063797743ba8298388dd590b8265ccf7/profiles/apparmor/profiles/extras/bwrap-userns-restrict).
The full suite checks same-UID write denial and allowed output directories.
On macOS, verification uses the system `sandbox-exec` instead.

```sh
python3 -m unittest discover -s tests -v
```

The archive test uses `tools/validate_skill.py` from this repository and a
nonexistent `CODEX_HOME`. A Codex installation is not a test prerequisite.
It validates every archived Skill's metadata, rejects unfinished instruction
placeholders, and checks the archived workflow entrypoint and runtime identity.
These are package checks, not evidence of a Skill's professional judgment.

Freeze the plugin source while a full suite is running: the workflow tests bind
their temporary runtime to the exact plugin payload, so concurrent edits can
correctly invalidate that identity.
