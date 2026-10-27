# Manual GitHub Actions build trigger

This PR is a **control surface**, not a code change to merge. Keep it open.

The repository has no `push` event for the Dizi standalone UEFI build.
After `main` changes are completed, the repository owner can post exactly:

```text
/run-dizi-uefi
```

The `issue_comment` event activates the **Dizi standalone UEFI + UniXNU (public only)** workflow only when the comment:
- is posted on this PR,
- comes from GitHub user `vildangil`, and
- exactly matches the command above.

The workflow then checks out the **latest `main`**, not this PR branch. Normal pushes do not trigger it.
`workflow_dispatch` remains available from the GitHub Actions web UI.

Do not merge this PR. Do not flash generated experimental boot images.
