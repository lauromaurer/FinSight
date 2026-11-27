# User data lives in the per-user app-data folder

Rules, categories, imported CSVs and exported charts are stored in the OS per-user data folder (`~/Library/Application Support/FinSight` on macOS, `%APPDATA%\FinSight` on Windows), not next to the executable or in the working directory. The old locations broke in packaged builds (inside a `.app` bundle, or a read-only install folder on Windows) and an app update could wipe user data. On first run, any files found in the old `config/` location are copied over once.

## Considered Options

- **Next to the executable / working directory** (previous behaviour): simple and portable, but not writable in packaged installs and tied to how the app was launched.
- **User-chosen folder**: flexible, but adds a setup step to a tool meant to be zero-config.
