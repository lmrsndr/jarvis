# filesystem_manager plugin

Safe local filesystem manager for Jarvis.

## Allowed root

The plugin only works inside:

```text
~/Projects
```

Relative paths are treated as relative to `~/Projects`.

## Actions

Safe actions:

- `list`
- `tree`
- `read`
- `info`
- `search_names`
- `search_text`

Medium actions:

- `create_file`
- `create_folder`
- `append_file`

Dangerous actions:

- `overwrite_file`
- `rename`
- `delete`

Dangerous actions require the host app to pass `admin_confirmed: true` after admin password verification and the exact approval phrase.

## Approval phrase examples

```text
APPROVE OVERWRITE: /home/s-ndrlm-r/Projects/Jarvis/test.txt
APPROVE DELETE: /home/s-ndrlm-r/Projects/Jarvis/test.txt
APPROVE RENAME: /home/s-ndrlm-r/Projects/Jarvis/old.txt -> /home/s-ndrlm-r/Projects/Jarvis/new.txt
```

Backups are created under:

```text
~/Projects/.jarvis_backups/
```

## Example calls

```json
{"action":"tree","path":"~/Projects/Jarvis","max_depth":4}
```

```json
{"action":"read","path":"~/Projects/Jarvis/README.md"}
```

```json
{"action":"create_file","path":"Jarvis/notes/example.md","content":"Hello"}
```
