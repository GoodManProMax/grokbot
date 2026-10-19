# Pending GitHub Actions workflows

These files belong in `.github/workflows/` on `main`.

Pushing workflow files requires a credential with the `workflow` scope
(OAuth) or fine-grained “Workflows: Read and write”.

Install (once scope is available):

```bash
mkdir -p .github/workflows
cp automation/github-workflows/update-*.yml .github/workflows/
git add .github/workflows
git commit -m "启用中国节假日与美股日历周末自动更新 Actions"
git push origin main
```

Crons are staggered on Saturday so the three calendars do not start in the same minute. All of them use concurrency group `ics-calendar-update` with `cancel-in-progress: false` (overlap queues, it does not cancel).

- China statutory holiday: `0 2 * * 6` (02:00 UTC / 10:00 Asia/Shanghai)
- China festivals and solar terms: `20 2 * * 6` (02:20 UTC / 10:20 Asia/Shanghai), workflow only under `.github/workflows/`
- US market: `40 2 * * 6` (02:40 UTC / 10:40 Asia/Shanghai)
