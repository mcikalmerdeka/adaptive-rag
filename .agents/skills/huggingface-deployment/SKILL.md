---
name: huggingface-deployment
description: Deploy and auto-deploy apps to Hugging Face Spaces from a GitHub repository. Use when setting up HF Space deployment pipelines, fixing Space build/CONFIG errors, debugging failed deploys, checking Space state, or diagnosing HF rate-limit failures. Triggers - "deploy to huggingface", "hf space", "huggingface sync", "CONFIG_ERROR", "space rebuild", "429 hub", "git push space".
---

# Hugging Face Space Deployment via GitHub

## Overview

How to deploy a project to a Hugging Face Space automatically whenever a GitHub repository is updated, hard lessons learned from a real production failure (rate-limited mid-deploy, broken/emptied Space), and the APIs used to debug Space state.

Core deployment strategies (in order of preference):

| Strategy                                   | How                                                      | Pros                                                               | Cons                                                                                  |
| ------------------------------------------ | -------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| **`git push space`** (recommended)         | CI pushes git history directly to the Space's git remote | 1 commit per push; incremental; native deletions; no SDK           | Pushes all git-tracked files; needs LFS tracked properly                              |
| **Official `huggingface/hub-sync` action** | GitHub Action that mirrors files via the `hf` CLI        | Zero-config; auto-excludes `.github/` + `.git/`; handles deletions | Mirror-based (not git-to-git); still commit-per-hook under the hood for large folders |
| **`hf upload` / `upload_folder` script**   | Python API bulk upload with `ignore_patterns`            | Full control over ignore list                                      | Easy to trip commit rate limits if implemented as delete-per-file + upload            |
| ~~Wipe-everything-then-upload~~            | `delete_file()` loop + `upload_folder`                   | (none — anti-pattern)                                              | Burns ~1 commit **per deleted file**; a mid-run failure leaves the Space half-emptied |

---

## When to Use This Skill

- Setting up auto-deployment: GitHub repo → Hugging Face Space (same as Vercel/GH Pages flow)
- Space shows `CONFIG_ERROR` / "Missing configuration in README"
- Deploy job fails with `429 Too Many Requests ... commit rate limit`
- Space state looks wrong after a failed deploy (files missing, only partial tree)
- Choosing between `git push`, `hub-sync`, and `upload_folder` for a Space

---

## Prerequisites (What a Working Space Needs)

1. **`README.md` with YAML front matter at the very top** — this _is_ the Space's build config. Without it HF shows:

   ```
   configuration error
   Missing configuration in README
   Base README.md template:
   ---
   title: {{title}}
   emoji: {{emoji}}
   colorFrom: {{colorFrom}}
   colorTo: {{colorTo}}
   sdk: {{sdk}}
   sdk_version: "{{sdkVersion}}"
   {{#pythonVersion}}
   python_version: "{{pythonVersion}}"
   {{/pythonVersion}}
   app_file: app.py
   pinned: false
   ---
   ```

   - `sdk`: `gradio` | `streamlit` | `static` | `docker` | `panel` | etc.
   - The error above is ALSO shown when `README.md` is missing entirely (e.g. failed deploy) — don't assume the front matter is malformed; check whether the file exists on the Space first (see Debugging).

2. **`requirements.txt` at repo root** — HF Spaces installs from this (it does NOT read `pyproject.toml`/`uv.lock` unless visible; keep `requirements.txt` authoritative).

3. **App file in repo root** matching `app_file` (usually `app.py`).

4. **GitHub secret `HF_TOKEN`** — a HF access token with write access to the Space, added in GitHub repo Settings → Secrets and variables → Actions.

---

## Recommended Setup: GitHub Workflow

```yaml
# .github/workflows/deploy.yml
name: Deploy to Hugging Face Space

on:
  push:
    branches: [main]
  workflow_dispatch: # manual re-run after rate-limit recovery

jobs:
  deploy-to-hf:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0 # full history — HF's pre-receive hook scans every pushed commit
          lfs: true # required whenever any tracked file matches .gitattributes LFS patterns

      - name: Push to HF Space
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
          SPACE_REPO: <HF_USERNAME>/<SPACE_NAME>
        run: |
          git lfs install
          git remote add space "https://user:${HF_TOKEN}@huggingface.co/spaces/${SPACE_REPO}"
          git push space main --force
```

Key mechanics:

- `git push --force` to the Space is **reconciling**: adds, updates, AND deletes files to match the repo — no wipe step needed, and a failed run can't half-emptied the Space (unlike a delete-all-then-upload script).
- **1 git push = 1 commit on HF** — the entire commit-rate-limit problem disappears. There is no need to delete per file. Delete files in git; push; they're deleted on the Space.
- LFS objects (assets, PDFs, models under `.gitattributes` tracking) upload automatically with the push because the Space remote supports Git LFS natively. `checkout` with `lfs: true` ensures the runner has the objects.
- `fetch-depth: 0`: HF scans history on push; shallow pushes with binary blobs in parents can be rejected — full history + LFS avoids surprises.

### Deployment scope is defined by git tracking, not an ignore list

The workflow deploys exactly what `git ls-files` outputs. Before wiring it up, run:

```bash
git ls-files    # everything that will land on the Space
```

- Sensitive files (`.env`) must be `gitignored` — never rely on a deploy ignore list to catch them.
- Data/runtime dirs (`data/output/*`, uploaded user files, model outputs) belong in `.gitignore`.
- Non-needed extras (agent docs, local tool configs) may ride along harmlessly if you prefer parity-by-tracking over extra ignores — decide consciously.

---

## Alternative: Official Action

```yaml
steps:
  - uses: actions/checkout@v6
  - uses: huggingface/hub-sync@v0.1.0
    with:
      github_repo_id: ${{ github.repository }}
      huggingface_repo_id: username/my-space
      hf_token: ${{ secrets.HF_TOKEN }}
```

Mirrors file contents (not git history), excludes `.github/` and `.git/` automatically, and removes Hub files that were removed from GitHub. Files >10MB must be tracked with Git LFS. Use this when you don't want the Space to share your git history at all.

---

## Rate Limits (Failure Mode That Took Down a Real Space)

Hub commit quota is a **user-action rate limit** (not part of the published 5-minute-window API/resolver tiers). Empirically observed on a free account:

```
429 Too Many Requests — You have exceeded the rate limit for repository commits
(128 per hour). You can retry this action in about 1 hour.
```

Key facts:

- The limit counts **commits regardless of success/failure**, including retried failed ones — a failed upload mid-run still spent budget.
- `delete_file()` is **one commit per file**. Wiping a 70-file Space ≈ 70 commits.
- `upload_folder` splits into multiple commits (auto-splits at ~50–100 files per commit for large folders).
- Three deploys in one hour ≈ far over budget → mid-upload 429 → Space left empty → rebuild error.

Recovery from a 429:

1. Wait for the window to reset (the error message states the cooldown, usually ~1 hour).
2. Re-run the workflow via `workflow_dispatch` (Actions tab → Run workflow) — no new commit needed if `main` is already correct.
3. Local runs (running the same script locally with the HF token) hit the **same account-level** quota.

If you must clean a repo where per-file deletes are otherwise unavoidable, batch them into a single commit:

```python
from huggingface_hub import HfApi
from huggingface_hub.hf_api import CommitOperationDelete

api.create_commit(
    repo_id="user/space", repo_type="space", token=token,
    operations=[CommitOperationDelete(path=f) for f in existing_files],
    commit_message="Clear existing files",
)
```

---

## Debugging a Space

### State inspection (works even when the UI is confusing)

```python
import os, requests
from dotenv import load_dotenv
load_dotenv()
h = {"Authorization": f"Bearer {os.environ['HF_TOKEN']}"}

# Files currently on the Space
r = requests.get("https://huggingface.co/api/spaces/<USER>/<SPACE>/tree/main", headers=h)
print(r.status_code, [f["path"] for f in r.json()])

# Space runtime/config status (runtime stage: RUNNING | BUILDING | CONFIG_ERROR | ...)
s = requests.get("https://huggingface.co/api/spaces/<USER>/<SPACE>", headers=h)
print(s.json().get("runtime", {}).get("stage"))
```

- `CONFIG_ERROR` + tree missing `README.md`/`app.py` → deploy died mid-run; find the failing workflow run's log (`gh run view <run-id> --log-failed`) — usually a 429 or upload exception — then fix root cause and re-run.
- `CONFIG_ERROR` + `README.md` present → front matter is actually malformed; the template block above tells you exactly what HF expects.

### Workflow failures

```bash
gh run list -R <OWNER>/<REPO> --limit 3          # history
gh run view <id> --log-failed -R <OWNER>/<REPO>  # the exception
gh workflow run deploy.yml -R <OWNER>/<REPO>     # manual rerun (workflow_dispatch)
```

### Space runtime issues

- **Logs tab** on the Space page is the only source of runtime (build/runtime) errors — config errors surface in the Space UI, not the GitHub Action log.
- Wrong `app_file` / missing root entry file → build succeeds, app fails. `app_file` must match exactly.

### After any Space-altering change

Check: file tree is complete (`tree/main` shows expected set), README front matter intact, and the Space's runtime stage becomes `RUNNING` after build.

---

## Gotchas

- **Rate limit is per account/token across everything**, so a local test run and a CI run share the same budget.
- The Hub's pre-receive hook scans **every commit in the push**, not just the tip — and since the move to Xet storage it **rejects raw binary files** not stored via Xet/LFS anywhere in that history, even if the current tree is clean (symptom: `remote: Your push was rejected because it contains binary files` + `Offending files:` list). If that bites, push a single **orphan commit** of the current tree minus raw binaries instead of raw history. Historic binaries committed before an LFS rule was added to `.gitattributes` stay raw in ancestors — adding the LFS rule only changes future commits.
- **LFS pointer vs file content**: if the runner checks out with `lfs: true`, files in the working copy are real content; pushing to the Space via `git push` uploads the real LFS objects over the remote's LFS endpoint. Without LFS checkout, the Space receives pointer files → 404 on the asset.
- `upload_folder` failures mid-run are **not transactional** — partial state persists (this is what emptied a real Space down to one directory).
- Deleting LFS files only frees guardrail-level storage after history is rewritten (`super_squash_history`), but for Spaces the OPPOSITE pattern is fine: force-push resets history, so old Storage-deleted files aren't a top concern.
- Secrets on the Space come from Space Settings → Variables and secrets (HF side), NOT from GitHub secrets; a `.env` excluded from the repo is still not present at runtime unless you set it in HF Space settings too.

---

## Checklist (Per Deployment Change)

- `README.md` front matter exists and matcher (`sdk`, `app_file`) targets the actual entrypoint and SDK version
- `requirements.txt` authoritatively lists runtime deps (Free HF Spaces reads only it)
- GitHub secret `HF_TOKEN` present and has write scope to the Space
- All Space-relevant files tracked in git; private/user-data files gitignored
- Workflow file under `.github/workflows/` with `push: branches: [main]` and `workflow_dispatch`
- Trigger one deploy and watch it complete; verify Space tree completeness and rerun if throttled
