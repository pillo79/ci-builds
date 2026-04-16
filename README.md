# ci-builds

Central store for CI build-metadata JSON snippets, with automated package index generation and publishing via GitHub Pages.

## How it works

1. Satellite repos call the reusable `store-snippets.yml` workflow at the end of their CI run
2. JSON snippets are committed to `snippets/{repo}/{branch}/{run-id}/`
3. The `generate-index.yml` workflow triggers automatically, builds and publishes to GitHub Pages

## Repository layout

```
snippets/
  {repo}/
    {branch}/
      <core-snippet-vxx-main>.json
      <core-snippet-vxx-contrib>.json
        ...           ← all snippets from the same repo branch
.github/workflows/
  store-snippets.yml  ← reusable workflow called by satellites
  generate-index.yml ← report generation + Pages deploy
```

## Setup

### 1. Enable GitHub Pages

In **ci-builds → Settings → Pages**, set source to **GitHub Actions**.

### 2. Create a PAT

Create a fine-grained PAT (or classic PAT) with **`contents: write`** on this repo.

### 3. Add the secret to each satellite repo

In each satellite repo → **Settings → Secrets → Actions**, add:

| Name | Value |
|---|---|
| `CI_CORES_TOKEN` | the PAT from step 2 |

### 4. Call the reusable workflow from satellite CIs

Add this step **after** your JSON-generating steps:

```yaml
- uses: arduino/ci-builds/.github/workflows/store-snippets.yml@main
  with:
    snippets: |
      {
        "build-info.json": ${{ toJSON(steps.build.outputs.metadata) }},
        "test-results.json": ${{ toJSON(steps.test.outputs.results) }}
      }
  secrets:
    ci_cores_token: ${{ secrets.CI_CORES_TOKEN }}
```

`snippets` is a JSON object: **keys** are the filenames to store, **values** are the JSON objects to write.  
The satellite's repo name, branch, and run ID are read from the calling context automatically.

## Customising the output

Edit the `generate-index.yml`.
