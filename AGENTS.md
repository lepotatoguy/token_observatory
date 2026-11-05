# Repository instructions

## Cross-platform verification is required

Token Observatory supports macOS, Windows, and Linux. This requirement applies
to every addition, update, and bug fix in this repository.

- Before editing, assess the effect on all three operating systems, including
  affected callers, dependencies, installation, packaging, and updates.
- Run the applicable automated checks on macOS, Windows, and Linux before
  merging or pushing behavior changes to main. Use native runners or machines
  for each operating system.
- For desktop, process, filesystem, launcher, installer, or updater changes,
  exercise the affected behavior on each applicable operating system. For a
  widget change, check both on and off states, visibility, background process
  behavior, and unwanted Dock, taskbar, app switcher, or console entries.
- Mocked platforms, parameterized tests on one host, and cross-compilation do
  not substitute for native operating system verification.
- Record the checks, results, and evidence locations for each operating system.
  If a required environment is unavailable or a check fails, report that gap
  and leave cross-platform verification incomplete. Do not describe the change
  as fully verified or push it to main until the required checks pass.
- Documentation-only changes need review for accuracy across all three
  operating systems; they do not require unrelated runtime tests. Explain any
  other platform exclusion using evidence rather than assuming it is unaffected.
