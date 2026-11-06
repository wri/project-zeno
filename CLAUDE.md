# Working in this repository

## PR titles and commit messages

A PR title and a commit message do different jobs. Don't copy one into the other.

**PR title: links the work to Jira.** Start it with the ticket key:
`PZB-1234: <summary>`. For several tickets use `PZB-1234, PZB-1240: <summary>`;
for work with no ticket use `NO-TICKET: <summary>`. A CI check fails the PR otherwise.

**Commit messages: the history.** Use Conventional Commits: `type(scope): summary`
- Common types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`
- Summary is imperative, lowercase after the colon, no trailing period

**Squash merges.** `main` is squash-only. GitHub pre-fills the squash commit
with the PR title when a PR has several commits. Replace it with a
Conventional Commits message before merging.

Examples:
- PR title: `PZB-1234: Handle empty AOI results in the geocoder`
- Squash commit: `fix(geocoder): handle empty AOI results`
