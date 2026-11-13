# Msty Studio 3.0 storage layout

This note records how Msty Studio 3.0.0 stores workspace data, as msty-admin-mcp v6.3.0 relies on it. Every fact is marked as checked on Linux or assumed for macOS and Windows.

## How it was checked

- Studio 3.0.0 and 2.9.12 Linux AppImages from Msty's update feed (`next-assets.msty.studio`, the `v3` Linux track for 3.0.0). Download checksums matched the feed.
- Each install ran in a throwaway home folder under a virtual display. No real Msty data and no Mac were used.
- Four set-ups were checked: a fresh 3.0.0 install, a 2.9.12 install, a 2.9.12 install upgraded in place to 3.0.0, and that upgrade after turning on file-based storage and moving a workspace to a custom folder.
- Rows were created through the Studio interface (persona, prompt, workspace, three Toolbox tools) and read back from the SQLite files.
- A persona and a prompt written by this MCP were opened, edited and saved in Studio 3.0.0.

## Facts checked on Linux

### Data folder

- The data folder is `~/.config/MstyStudio`.
- The Linux process and executable name is `mstystudio`. The case-insensitive process check for `MstyStudio` matches it.
- The installed version is not readable from a fixed path on Linux (the AppImage carries it in its desktop entry only), so this MCP reports the version as unknown there.

### Workspace storage

- File-based storage puts each workspace in `<data>/data/workspaces/<slug>/msty.cloud.db`, in WAL mode. Home has the slug `default`.
- A custom folder is recorded in `<data>/data/workspace-locations.json` as `{"<slug>": {"parentPath": "/absolute/path"}}`. The database is then `<parentPath>/<slug>/msty.cloud.db`.
- A workspace folder other than Home holds a `.msty.workspace` JSON file with its name, slug and icon.
- The workspace list lives in the `workspaces` table of the Home database (id, name, slug, colorIcon, extras, isActive, createdAt). Home has the id `__MSTY__DEFAULT__WORKSPACE__`. `isActive = 1` marks the active workspace.
- Each other workspace database has its own `workspaces` table holding only a default row. It is ignored.
- A fresh 3.0.0 install uses file-based storage from the start. No browser-storage database exists.

### Upgrade from 2.9.12

- After the upgrade Studio keeps the workspace in Chromium browser storage (`<data>/File System/000/t/00/00000000`) and migrates it in place to the 3.0 schema (63 tables, 30 migrations). Its schema then matches a fresh 3.0.0 install exactly.
- Turning on file-based storage (Settings, Data, Workspace storage) copies the database to `data/workspaces/default/msty.cloud.db` and leaves the browser-storage file in place. Studio no longer updates that file. A persona created after the switch exists only in the new file.
- Moving a workspace to another folder copies it, checks the copy, then deletes the source, so no stale copy is left.
- Studio decides the storage of a workspace this way: file-based if a custom location is set or the file exists, else browser storage if the browser file exists, else file-based. This MCP follows the same order.
- Browser storage maps only Home to a known file. Other browser-storage workspaces would need Chromium's leveldb index, so this MCP lists them as `browser_unmapped` and does not read them.

### Schema

- 3.0.0 adds the `crewFolders` table, `crews.folderId` and `personaFolders.folderParentId` to the 2.9.12 schema. The 2.9.12 migration list is the start of the 3.0.0 list.
- The persona, persona version and prompt tables are the same in 2.9.12 and 3.0.0. Personas created in Studio look the same in both releases.
- A prompt created in Studio has `source = 'custom'` (the column default `'ootb'` is for prompts Studio ships), no `activeVersionId`, and a version row with its own id and the changelog `Initial version`.
- Schema fingerprints (sha256 over table names and `PRAGMA table_info` rows):
  - full schema 2.9.12: `014febe701c3a311cf3f915bbce882ca15f60377eec16a508c4499191598a6f8`
  - full schema 3.0.0: `8006b6fe2940f2d5b6b5d9d4992b704aa3b3b1b2230278b34310b129f319a18e`
  - persona and prompt write tables 3.0.0: `6349bbbc21b2c9ff2fcf933fd7896c0586037b1ca6a1c305f1c9fbaffc112237`
  - latest migration 3.0.0: `dfd015ce2d3143d02275131190db973f05a5f7af4cf9f08995bc7f3d38576ad0`

### Toolbox tools

- An HTTP tool stores `{"transport": "http", "url": ..., "headers": {name: value}, "auth": ...}`. No auth means no `auth` key. Bearer auth is `{"type": "bearer", "token": ...}`. OAuth is `{"type": "oauth", "mode": "oauth" or "oauth-dynamic", "clientId", "clientSecret", "scope", ...}`.
- A STDIO tool stores `{"command", "args", "env"}` with no transport key.
- OAuth tokens are kept in `<data>/secrets.json`, encrypted by Electron safeStorage. This MCP does not read that file.

### Other

- A read-only SQLite open of a live WAL database works while Studio runs and shows current data.
- Agent Mode sessions are files under `<data>/agents/sessions`. Only `agentModePlans` is in the database.
- Studio 3.0.0 opened, listed, edited and saved a persona and a prompt written by this MCP. Studio kept the persona's version link and the prompt's version row.
- The same was checked with Home still in browser storage: a 2.9.12 install upgraded in place to 3.0.0, file-based storage not turned on. A persona and a prompt written by this MCP into the browser-storage database with Studio closed were listed, opened, edited and saved after a relaunch, and `PRAGMA quick_check` stayed `ok`. Both writes reused free pages, so the file size did not change. A write that grows the file, and a crash in the middle of a write (which would leave a `-journal` file Studio does not look for), were not tested. The backup taken before every write covers both cases.

## Assumed for macOS and Windows

- The data folder is Electron's `userData` folder: `~/Library/Application Support/MstyStudio` on macOS and `%APPDATA%\MstyStudio` on Windows. Studio sets no other location outside development builds. This was read from the app code, not seen on a Mac or a Windows PC.
- The folder layout under the data folder, the workspace registry and the schema are the same on every platform, because they come from the same app code. Not seen on a Mac.
- The macOS app version is read from `MstyStudio.app/Contents/Info.plist` as before. A 3.0 bundle was not inspected.
- The macOS process name is `MstyStudio`, as seen on 2.x.

## What this MCP does with it

- Reads use the active workspace unless a `workspace` is given, and never read a stale copy.
- Writes on Studio 3.0 go only to the active workspace's current database, need the write-table fingerprint and latest migration above, need Studio closed, and are read back before COMMIT. The schema, migration and Studio-running checks run again after the write lock is taken, and Studio-running is checked once more just before COMMIT.
- If more than one workspace is marked active, the earliest created is used and results carry a `storage_warnings` entry.
- A Studio 3.0.x patch that changes the persona or prompt tables refuses writes until its fingerprint is added after the same check. Studio 3.1 and later are refused for reads and writes.
