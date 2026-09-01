# Working in this repository

## PR titles and commit history

`main` is protected by a squash-only ruleset with required linear history: every PR collapses into a single commit on merge, and that commit's message is the PR title. Write PR titles accordingly.

- Use Conventional Commits format: `type(scope): summary`
- Common types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`
- Summary is imperative, lowercase after the colon, no trailing period
- Put ticket references (e.g. `PZB-1234`) in the PR description, not the title

Examples:
- `fix(geocoder): handle empty AOI results`
- `feat(dashboards): add section grouping for widgets`
