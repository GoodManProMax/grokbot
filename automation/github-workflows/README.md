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

Cron (both): `0 2 * * 6` (Saturday 02:00 UTC = Saturday 10:00 Asia/Shanghai)
