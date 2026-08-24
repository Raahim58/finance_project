# Issue tracker: GitHub

Issues and specifications for this repository live in GitHub Issues at
`Raahim58/finance_project`. Use the `gh` CLI from inside this repository.

## Operations

- Create: `gh issue create --title "..." --body-file <file>`
- Read: `gh issue view <number> --comments`
- List: `gh issue list`
- Comment: `gh issue comment <number> --body "..."`
- Label: `gh issue edit <number> --add-label "..."`
- Close: `gh issue close <number> --comment "..."`

Infer the repository from its Git remote.

## Pull requests as a request surface

PRs as a request surface: no.

## Skill conventions

- “Publish to the issue tracker” means create a GitHub issue.
- “Fetch the relevant ticket” means read the GitHub issue and its comments.
