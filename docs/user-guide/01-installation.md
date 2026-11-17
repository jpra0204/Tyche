# Installation and your workspace

This page gets Tyche onto your Mac and creates your private workspace. It takes about ten minutes. Nothing here connects to a broker or spends money.

## What you need

- macOS with [Homebrew](https://brew.sh).
- [uv](https://docs.astral.sh/uv/), which installs the right Python version for you. Install it with:

  ```bash
  brew install uv
  ```

- git, which comes with the Xcode command-line tools.

## 1. Get the code

```bash
git clone https://github.com/jpra0204/Tyche.git
cd Tyche
make install
```

`make install` creates a virtual environment with the pinned Python version (3.14) and the exact library versions from `uv.lock`.

Check it worked:

```bash
uv run tyche --version
```

You should see `tyche` and a version number.

## 2. Create your workspace

Your workspace is a separate, private folder for everything that is yours: configuration now, and later your data, reports, proposals and trading state. The code repository is public, so none of this goes in it.

```bash
uv run tyche init
```

This creates `~/tyche-workspace` with:

| File | What it is |
|---|---|
| `config/tyche.toml` | Workspace settings, including the active market profile |
| `config/markets/US.toml` | The `US` market profile |
| `.env` | Where secrets will go in Phase 2. Empty for now, and readable only by you |
| `.gitignore` | Keeps `.env`, market data, state and logs out of git |
| `README.md` | A short description of the folder |

`tyche init` refuses to:

- overwrite a folder that already has something in it;
- create the workspace inside `~/Public`, `~/Desktop` or `~/Documents`, or inside any git repository, including the Tyche code itself.

### Using a different folder

```bash
uv run tyche init --home /path/to/folder
```

Then tell Tyche where it is, in your shell profile (for example `~/.zshrc`):

```bash
export TYCHE_HOME=/path/to/folder
```

Tyche looks for the workspace in this order: the `--home` option, then `TYCHE_HOME`, then `~/tyche-workspace`.

## 3. Make the workspace a private git repository

Your configuration should be versioned, so you can see what changed and when.

```bash
cd ~/tyche-workspace
git init
git add .
git commit -m "Create Tyche workspace"
```

Check that `.env` was not committed:

```bash
git ls-files
```

The list should not contain `.env`.

If you also keep it on GitHub, create the repository as **private**. Never make it public.

## 4. Check the configuration

From the Tyche code folder:

```bash
uv run tyche config check
```

You should see:

```text
Configuration is valid: /Users/<you>/tyche-workspace
  Market profile: US
  Config hash:    sha256:…
```

The config hash is a fingerprint of every setting. Tyche will print it in every backtest report and run log, so you can always tell which configuration produced a result. Editing a comment or reordering keys does not change it; changing any value does.

If something is wrong, the message names the file and the setting:

```text
Error: config/tyche.toml: 1 invalid setting(s)
  risk_profle: Extra inputs are not permitted
```

Unknown settings are always an error, so a misspelled key cannot be silently ignored.

## Troubleshooting

| Message | What to do |
|---|---|
| `config/tyche.toml is missing; is … a Tyche workspace?` | Tyche is looking in the wrong folder. Check `TYCHE_HOME`, or run `tyche init` if you have no workspace yet. |
| `TYCHE_HOME is set but empty` | Unset it (`unset TYCHE_HOME`) or give it a path. |
| `… is not empty; tyche init only creates a new workspace` | You already have a workspace there. Use `tyche config check` instead. |
| `… is inside ~/Documents, which macOS can sync to iCloud` | Choose a folder outside `~/Public`, `~/Desktop` and `~/Documents`. |
| `… selects market profile 'CA', but config/markets/CA.toml does not exist` | Only `US` exists for now. `CA` and `CA+US` arrive in Phase 4. |
