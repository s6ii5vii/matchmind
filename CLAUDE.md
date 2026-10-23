# CLAUDE.md

## Git commits (required)

- Commit as the repository owner, never as Claude. Before the first commit in a session run:
  `git config user.name "s6ii5vii"` and
  `git config user.email "259956125+s6ii5vii@users.noreply.github.com"`
- Do NOT add `Co-Authored-By`, `Claude-Session`, "Generated with Claude Code" or any other
  attribution lines to commit messages or PR descriptions. Claude must not appear as a contributor.
- Branch names must not contain "claude". Use plain names like `feature/<topic>` or `fix/<topic>`,
  even if the session suggests a `claude/...` branch.

## Project

MatchMind: synthetic football match intelligence for the Microsoft Premier League Hackathon 2026.

- `backend/` FastAPI (Python 3.10+). Tests: `python -m unittest discover -s tests -v` from `backend/`.
- `backend/app/agents/` multi-agent pipeline built on Microsoft Agent Framework workflows.
- `frontend/` Next.js dashboard. `npm run build` to type-check.
- All teams, players and events are fictional. Never introduce real club names or real match data.
