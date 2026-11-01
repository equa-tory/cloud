# cloud

A keyboard-driven selective sync manager for folders on already-mounted shares.
It never edits fstab, stores share passwords, or mounts/unmounts `/mnt` shares.
Requires Python 3 and curses (normally included on Linux/macOS). No server software.
Linux background sync uses the existing user systemd; macOS uses launchd.

## Install again

Download `cloud` from [GitHub](https://github.com/equa-tory/cloud), or clone this repository.
Copy the single script into your PATH:

```sh
mkdir -p ~/.local/bin
install -m 755 cloud ~/.local/bin/cloud
cloud
```

Or run `sh install.sh` after cloning the repository.

```sh
git clone https://github.com/equa-tory/cloud.git
cd cloud
sh install.sh
cloud
```

## Example

Run `cloud`. Use Up/Down and Enter, Esc to go back, or q to leave a screen.

1. Choose **Connect a folder**.
2. Choose an existing source such as `/mnt/nas` (read from fstab), or type a path.
3. Browse **Media → Stems → Use this folder**.
4. Accept `~/Documents/Stems`, or enter another empty/new local folder.
5. Browse the source, select a song folder, open **Actions for this folder**,
   and choose **Pin**. Files show actions directly.
6. Enable **Auto sync** to sync every two minutes, or use **Sync now** manually.

A connection is created without walking the whole tree. The browser lists only
the directory you open. Pinning downloads and scans that selection; large pinned
folders still require time to enumerate and copy. Pinning the entire source
naturally scans/downloads the whole source.

If `~/Documents/Stems` is already connected, select **Stems** from the home screen
instead of creating it again. Choose **Enable lazy browsing** once for an old
profile. Pins and downloaded files stay; existing stubs stay without an expensive
cleanup. Legacy profiles retain full indexing until this option is chosen.

## What syncs

Pinned paths are downloaded and kept available offline. Local edits, new files,
renames, and deletions in those paths sync both ways. Already tracked downloaded
files continue syncing until explicitly unpinned, including after switching an
old profile to lazy mode. New files outside selected paths do not sync in lazy mode.
New remote folders/files outside those paths are visible in the cloud browser;
they are not automatically materialized in the local sync folder.

Unpin first syncs changes, then removes local copies confirmed identical to the
server. Small `.cloud` stubs may remain; these are instructions, not files that
transparently download when opened. The remote files stay. To unpin a child of
a pinned folder, unpin the parent and select the children you want.

Auto sync OFF stops scheduled sync; pin/unpin and manual sync still work.
Disconnect stops scheduled sync and removes cloud settings and stubs while keeping
downloaded files. It does not disconnect, modify, or unmount the underlying share.

Existing conflict and deletion behavior remains: newer edits win, older conflicting
versions are kept beside the file (except `.meta` conflicts), deletions go to trash
for 30 days by default, and more than 100 file deletions require `sync --force`.
Sync compares size and modification time. Backups are still advisable for important data.

## Commands

```sh
cloud                                      # keyboard manager
cloud list                                 # saved/discovered connections
cloud -C ~/Documents/Stems                  # open this connection in the manager
cloud init /mnt/nas/Media/Stems ~/Documents/MyStems
cloud -C ~/Documents/MyStems status
cloud -C ~/Documents/MyStems pin ~/Documents/MyStems/SomeSong
cloud -C ~/Documents/MyStems unpin ~/Documents/MyStems/SomeSong
cloud -C ~/Documents/MyStems sync
cloud -C ~/Documents/MyStems auto on 120
cloud -C ~/Documents/MyStems auto off
cloud -C ~/Documents/MyStems uninit          # prompts; keeps downloads
```

`init --full-index REMOTE LOCAL` retains the older recursive placeholder behavior.
Saved folder paths live in `~/.config/cloud/folders.json` (or XDG_CONFIG_HOME).
Each local folder retains its own `.cloudsync.json` and sync state. Discovery checks
only home and Documents one level deep; other locations become registered when
created or accessed using `-C`.

Run tests with `python3 test_cloud`. Tests use temporary local folders, never NAS data.
