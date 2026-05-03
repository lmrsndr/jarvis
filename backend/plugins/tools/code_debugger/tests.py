from pathlib import Path
import tempfile
import shutil

from tool import run


def main():
    root = Path("/home/s-ndrlm-r/Projects")
    root.mkdir(parents=True, exist_ok=True)
    test_project = root / "code_debugger_test_project"
    if test_project.exists():
        shutil.rmtree(test_project)
    test_project.mkdir(parents=True)
    (test_project / "frontend.jsx").write_text("""
      <button>Users</button>
      fetch('/api/users')
      <a href='/dashboard'>Dashboard</a>
    """, encoding="utf-8")
    (test_project / "server.js").write_text("""
      const express = require('express')
      const router = express.Router()
      router.get('/api/users', handler)
      router.post('/api/orders', handler)
    """, encoding="utf-8")

    result = run({"action": "audit", "project_path": str(test_project)})
    assert result["ok"] is True
    assert result["summary"]["backend_routes_count"] >= 2
    assert any(i["category"] == "unreached_backend_route" for i in result["issues"])

    read_result = run({"action": "read_file", "project_path": str(test_project), "target_file": "frontend.jsx"})
    assert read_result["ok"] is True

    delete_result = run({
        "action": "delete_file",
        "project_path": str(test_project),
        "target_file": "frontend.jsx",
        "approval_text": f"APPROVE ACTION: code_debugger delete_file {test_project} frontend.jsx",
    })
    assert delete_result["ok"] is True

    shutil.rmtree(test_project)
    print("code_debugger tests passed")


if __name__ == "__main__":
    main()
