# Deploying to GitHub Pages

The `research/site/` directory is a complete static site. A GitHub Actions
workflow at `.github/workflows/pages.yml` publishes it automatically.

## One-time setup

1. **Create a GitHub repo** (if you don't have one for this project yet):

   ```bash
   gh repo create wc2026-tracking-transformer --public --source=. --remote=origin
   # or, if the repo already exists on GitHub:
   git remote add origin git@github.com:<your-user>/wc2026-tracking-transformer.git
   ```

2. **Push the project**:

   ```bash
   git push -u origin main
   ```

3. **Enable Pages** in the repo:
   - Go to `Settings → Pages`.
   - Under "Build and deployment", set **Source = GitHub Actions**.
   - The workflow at `.github/workflows/pages.yml` will run on the next push
     to `main` that touches anything under `research/site/`.

4. **First run** — either push a change, or trigger manually from the Actions
   tab: pick "Deploy chemistry site to GitHub Pages" → "Run workflow".

The deployed URL will be one of:

- Project page: `https://<your-user>.github.io/wc2026-tracking-transformer/`
- Custom domain: configure in the Pages settings.

## Updating the site

Re-run the export pipeline whenever the data changes:

```bash
PYTHONPATH=research/src uv run python research/scripts/export_site_data.py
PYTHONPATH=research/src uv run python research/scripts/render_chemistry_figures.py
git add research/site/data research/site/assets/figures
git commit -m "Refresh chemistry site data"
git push
```

The workflow re-deploys on push.

## Size budget

The site is ~48 MB (24 MB CSV, 18 MB PNG figures, 6 MB JSON + joblibs).
GitHub Pages allows up to 1 GB and 100 MB per file. Comfortable headroom.
