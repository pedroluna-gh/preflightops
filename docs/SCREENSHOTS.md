# Screenshots

The images under `docs/screenshots/` are referenced from the README. They are
real captures of the running PreflightOps app (`app-overview.png`, `risk-results.png`)
the bundled placeholder example data. The real public pull-request evidence is
captured in `preflightops-demo-pr.png`. The steps below explain how to regenerate
them.

| File | Where it's used | What to capture |
|---|---|---|
| `app-overview.png` | README hero | The Streamlit app with the Service Catalog and Change Request editors and the **Run Risk Assessment** button. |
| `risk-results.png` | README "Quick demo" | A completed assessment showing the risk score, risk level, and the per-category score breakdown. |
| `github-pr-comment.png` | README GitHub Action section | The PreflightOps report posted as a pull-request comment with a failed check. |
| `preflightops-demo-pr.png` | README GitHub Action section | Full-page capture of the public v0.3.0 demo PR, bot comment, and passing check. |

## How to capture

1. Launch the web app:

   ```bash
   pip install -e ".[app]"
   streamlit run app.py
   ```

2. Click a **Low / High / Critical Risk Example**, then **Run Risk Assessment**.

3. Take a screenshot of:
   - the input editors (for `app-overview.png`), and
   - the results / score breakdown (for `risk-results.png`).

4. For `github-pr-comment.png`, open a pull request in a repo that uses the
   PreflightOps Action and screenshot the posted report comment.

5. Refresh `preflightops-demo-pr.png` only from the completed public
   [`preflightops-demo` PR #1](https://github.com/pedroluna-gh/preflightops-demo/pull/1),
   keeping the title, generated comment, and passing check visible together.

## Guidelines

- Use a clean browser window (no personal bookmarks/extensions visible).
- Use a high-contrast light or dark GitHub theme and a width around **1280px**.
- Keep file sizes reasonable (PNG, ideally < 300 KB each).
- Use only placeholder / non-sensitive data in the inputs.
- Keep the same file names so the README links keep working.
