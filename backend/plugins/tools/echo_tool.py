from __future__ import annotations


class Tool:
    name = "echo"
    description = "Return the input text unchanged."

    def run(self, text: str = "") -> dict[str, str]:
        return {"text": text}
