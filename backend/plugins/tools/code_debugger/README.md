# code_debugger Jarvis Plugin

`code_debugger` gives Jarvis safe project inspection and controlled code-change capability for projects under:

```text
/home/s-ndrlm-r/Projects
```

## Safety model

- Read access is allowed inside `/home/s-ndrlm-r/Projects`.
- Write/delete actions are blocked unless `confirmation` is exactly `OK`.
- Delete does not permanently delete. It moves files into `.jarvis_trash/` inside the project.
- The plugin refuses paths outside `/home/s-ndrlm-r/Projects`.
- Large files, binary files, `node_modules`, `.git`, builds and caches are ignored.

## Actions

### audit

```json
{
  "action": "audit",
  "project_path": "/home/s-ndrlm-r/Projects/affiliate-marketing-app"
}
```

Finds frontend routes, backend routes, API calls, buttons, forms, imports and likely connection issues.

### preview_fix

```json
{
  "action": "preview_fix",
  "project_path": "/home/s-ndrlm-r/Projects/affiliate-marketing-app",
  "issue_id": "ISSUE-001"
}
```

Returns the proposed fix guidance for a specific issue.

### apply_fix

```json
{
  "action": "apply_fix",
  "project_path": "/home/s-ndrlm-r/Projects/affiliate-marketing-app",
  "issue_id": "ISSUE-001",
  "confirmation": "OK"
}
```

V1 intentionally does not perform broad automatic rewrites. It is wired safely for future project-specific fix templates.

### read_file

```json
{
  "action": "read_file",
  "project_path": "/home/s-ndrlm-r/Projects/affiliate-marketing-app",
  "target_file": "frontend/src/App.jsx"
}
```

Reads a text file inside the project.

### delete_file

```json
{
  "action": "delete_file",
  "project_path": "/home/s-ndrlm-r/Projects/affiliate-marketing-app",
  "target_file": "old-file.js",
  "confirmation": "OK"
}
```

Moves the file to `.jarvis_trash/`.

### list_tree

```json
{
  "action": "list_tree",
  "project_path": "/home/s-ndrlm-r/Projects/affiliate-marketing-app",
  "max_files": 300
}
```

Lists text-like project files.

## Suggested Jarvis prompt

```text
Use code_debugger to audit /home/s-ndrlm-r/Projects/affiliate-marketing-app.
Check frontend routes, backend routes, buttons, forms, API calls and imports.
Return a table of likely missing GUI access, broken API links and broken imports.
Do not apply fixes until I say OK.
```
