# cloud

An iCloud-style folder for a network share that is already mounted (Linux + macOS). One Python 3 file, no dependencies,
nothing installed on the server.

```bash
sudo install -m 755 cloud /usr/local/bin/cloud
cloud init /mnt/share/Projects ~/Cloud     # create the local folder
cd ~/Cloud
cloud pin Game                             # download + keep in sync both ways
cloud unpin Game                           # upload changes, free the disk space
cloud sync                                 # sync now (cloud auto on 120 = every 2 min)
cloud status                               # pinned items, auto sync, last sync
```

- Files you haven't pinned show up as small `name.ext.cloud` stubs.
- Pinned files sync both ways; the newest edit wins. If both sides changed a file, the older version is kept next to it as
  `name (conflict HOST DATE).ext`.
- Deleted files go to `.cloud-trash/` (local and on the share) for 30 days. A sync that would delete more than 100 files is
  refused unless you run `cloud sync --force`.
- If the share isn't mounted, nothing happens: `cloud` refuses to sync against a missing or empty folder.
- Settings live in `.cloudsync.json` (remote, pinned, exclude list, max_deletes, trash_days, auto). Unity's `Library/`, `Temp/`,
  `obj/`, `Logs/`, `UserSettings/` are excluded by default.
