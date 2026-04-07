# Release Packaging

Do not create the final delivery zip by compressing the whole working folder directly.

Use the PowerShell packaging script instead:

```powershell
.\create_release_zip.ps1
```

The generated release zip excludes:

- `.git/`
- `__pycache__/`, `*.pyc`, `*.pyo`
- `uploads/`, `repo/`, `repo_v1/`
- `test_uploads/`, `test_repo/`, `tests/_tmp/`
- `frontend/node_modules/` and other `node_modules/`
- `*.db`, `*.sqlite`, `*.log`, previous `release/*.zip`
- local regression folders such as `smart_org_regression_*/`

If a frontend exists, the delivery package should keep dependency manifests such as `package.json` and `package-lock.json`, but should not include `node_modules/`.

After unpacking, install and verify dependencies again:

```bash
npm install
npm run build
npm test
```
