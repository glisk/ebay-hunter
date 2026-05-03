# CLAUDE.md — Working conventions for this repo

## Branch strategy
- main is protected. Never commit directly to main.
- Feature branches: feature/description-of-work
- Bug branches: fix/description-of-bug
- All work happens in branches.

## Commit messages
- Imperative mood: "Add scoring model" not "Added scoring model"
- Describe what changed and why, not just what

## Pull requests
- Every branch merges via PR, even solo work
- PR description must include: what changed, why, and how to test
- Human approves all PRs before merge

## Testing
- Unit tests alongside each module, not after
- Tests live in /tests mirroring /src structure
- No merge to main without passing tests
