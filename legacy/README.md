# legacy/ — archived, superseded material

These files are retained for history/reference but **not part of the active
engine**. The live code is `src/jb_ape/`; the live docs are `AGENTS.md` + `README.md`.

| File | What it was | Superseded by |
|------|-------------|---------------|
| `ape.py` | Original single-file LangGraph jailbreak framework | `src/jb_ape/` (full rewrite) |
| `mcp_ape.py` | MCP server exposing the old planner | `src/jb_ape/facade.py` |
| `test_ape.py` | Tests for the old `ape.py` (mostly failing/stale) | `tests/` (233 tests) |
| `tech.txt` | Flat 20-entry technique list | `src/jb_ape/techniques.py` |
| `README_cn.md` | Old Chinese README (describes ape.py) | `README.md` |
| `CLAUDE.md` | Old Claude Code guidance (describes ape.py) | `AGENTS.md` |
| `req.txt` | Old dependency list (`pytest-asyncio`) | `pyproject.toml` |

## legacy/ctf/ (gitignored — contains flags, local only)

Past CTF writeups and payload samples. Kept for reference; **not tracked in git**
because they contain HTB flags and exploit material.
