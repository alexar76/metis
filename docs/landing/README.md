# Metis Landing Page — GitHub Pages Deployment

Static landing page at `docs/landing/index.html`. All CSS and SVG are inlined — no CDN dependencies.

## Option A: Deploy from `/docs` folder (recommended)

1. Push this repo to GitHub.
2. Go to **Settings → Pages**.
3. Under **Build and deployment → Source**, select **Deploy from a branch**.
4. Branch: `main` (or your default branch).
5. Folder: **`/docs`**.
6. Save. GitHub Pages will serve `docs/landing/index.html` at:

   ```
   https://<username>.github.io/metis/landing/
   ```

   To make the landing page the site root, either:
   - Move `index.html` to `docs/index.html`, or
   - Add a redirect from `docs/index.html` to `landing/index.html`.

## Option B: Deploy only the landing page (gh-pages branch)

```bash
git checkout --orphan gh-pages
git rm -rf .
cp docs/landing/index.html index.html
git add index.html
git commit -m "Deploy landing page"
git push -u origin gh-pages
```

Then in **Settings → Pages**, set source to branch `gh-pages` / root (`/`).

Site URL: `https://<username>.github.io/metis/`

## Option C: Custom domain

1. Add a `CNAME` file to the published folder (e.g. `docs/CNAME` containing `metis.example.com`).
2. Configure DNS: `CNAME metis.example.com → <username>.github.io`.
3. Enable **Enforce HTTPS** in Pages settings.

## Local preview

```bash
cd docs/landing
python3 -m http.server 8000
# Open http://localhost:8000
```

## Updating

Edit `docs/landing/index.html` and push to the branch configured in Pages settings. Deployment typically completes within 1–2 minutes.
