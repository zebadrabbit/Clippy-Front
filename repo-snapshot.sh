#!/usr/bin/env bash
set -euo pipefail

OUT=".repo_snapshot"
rm -rf "$OUT" && mkdir -p "$OUT"

# 0) Basic git metadata
{
  echo "# Repo Metadata"
  echo "Repo: $(basename "$(git rev-parse --show-toplevel)")"
  echo "Default branch: $(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@' || true)"
  echo "HEAD: $(git rev-parse --short HEAD)"
  echo "HEAD date: $(git show -s --format=%ci HEAD)"
  echo
  echo "## Recent commits (last 30)"
  git log --oneline -n 30
  echo
  echo "## Top contributors"
  git shortlog -sn --all
} > "$OUT/00_git_overview.md"

# 1) Top-level manifest & config
mkdir -p "$OUT/manifest"
for f in package.json pnpm-lock.yaml yarn.lock package-lock.json turbo.json nx.json tsconfig.json jsconfig.json\
         .eslintrc* .prettierrc* .nvmrc .node-version .browserslistrc .editorconfig .npmrc; do
  [ -f "$f" ] && cp "$f" "$OUT/manifest/" || true
done

# 2) App structure (limit depth; ignore huge dirs)
mkdir -p "$OUT/structure"
if command -v tree >/dev/null; then
  tree -I 'node_modules|.git|.next|dist|build|coverage|.turbo|.nx|out|.cache' -L 3 > "$OUT/structure/dir_tree.txt"
else
  find . -maxdepth 3 \( -path './node_modules' -o -path './.git' -o -path './.next' -o -path './dist' -o -path './build' -o -path './coverage' -o -path './.turbo' -o -path './out' -o -path './.cache' \) -prune -o -type d -print > "$OUT/structure/dirs.txt"
fi

# 3) Size & hotspots
mkdir -p "$OUT/hotspots"
# Biggest tracked files (exclude node_modules etc.)
git ls-files -z | xargs -0 -I{} bash -lc 'printf "%s\t%s\n" "$(wc -c < "{}")" "{}"' \
  | sort -nr | head -n 100 > "$OUT/hotspots/largest_tracked_files.tsv"

# 4) Code stats (cloc if available)
if command -v cloc >/dev/null; then
  cloc --exclude-dir=node_modules,.git,.next,dist,build,coverage,.turbo,.nx,out,.cache \
       --by-file --json . > "$OUT/hotspots/cloc_by_file.json" || true
  cloc --exclude-dir=node_modules,.git,.next,dist,build,coverage,.turbo,.nx,out,.cache \
       . > "$OUT/hotspots/cloc_summary.txt" || true
fi

# 5) Deps & scripts (Node)
if [ -f package.json ]; then
  node -e 'const fs=require("fs");const j=JSON.parse(fs.readFileSync("package.json","utf8"));
    console.log("# npm scripts"); for (const [k,v] of Object.entries(j.scripts||{})) console.log(k, "=>", v);
    console.log("\n# dependencies"); console.log(JSON.stringify(j.dependencies||{},null,2));
    console.log("\n# devDependencies"); console.log(JSON.stringify(j.devDependencies||{},null,2));' \
    > "$OUT/manifest/npm_overview.txt" || true
  # Full tree (safe-ish)
  npm ls --all --json > "$OUT/manifest/npm_tree.json" 2>/dev/null || true
fi

# 6) Framework-specific: Next.js/React routes, API
mkdir -p "$OUT/framework"
# Next.js (pages/ or app/ routing)
rg --no-color --line-number --glob '!node_modules' --glob '!dist' --glob '!build' \
  -e 'export default function.*' -e 'export const GET|POST|PUT|DELETE' \
  > "$OUT/framework/exports_scan.txt" 2>/dev/null || true

# Pages/app directories & API endpoints
{
  echo "## Route-ish files"
  rg --no-color --files -g 'pages/**' -g 'app/**' -g 'src/pages/**' -g 'src/app/**' -g 'pages/api/**' -g 'app/**/route.*' \
     -g '!node_modules' | sort
} > "$OUT/framework/routes_files.txt" 2>/dev/null || true

# 7) Linting & formatting warnings (optional quick sample)
rg --no-color --line-number --glob '!node_modules' -e 'TODO|FIXME|HACK|@ts-expect-error|@ts-ignore' \
  > "$OUT/hotspots/annotations.txt" 2>/dev/null || true

# 8) Tests presence
{
  echo "## Detected test files"
  rg --files -g '*.{test,spec}.{ts,tsx,js,jsx}' -g '!node_modules' | sort
} > "$OUT/tests/tests_inventory.txt" 2>/dev/null || true
[ -f jest.config.* ] && cp jest.config.* "$OUT/tests/" || true
[ -f vitest.config.* ] && cp vitest.config.* "$OUT/tests/" || true
[ -f playwright.config.* ] && cp playwright.config.* "$OUT/tests/" || true

# 9) CI
mkdir -p "$OUT/ci"
[ -d .github/workflows ] && cp -r .github/workflows "$OUT/ci/" || true

# 10) Env template (keys only; no secrets)
for f in .env.example .env.sample .env.template; do
  [ -f "$f" ] && cp "$f" "$OUT/env_keys.txt"
done

# 11) Import graph (if madge is installed)
if command -v npx >/dev/null; then
  npx --yes madge --ts-config ./tsconfig.json --extensions ts,tsx,js,jsx --warning \
      --json . > "$OUT/framework/import_graph.json" 2>/dev/null || true
fi

# 12) Zip it
ZIP="clippy_front_snapshot.zip"
rm -f "$ZIP"
zip -qr "$ZIP" "$OUT"
echo "Wrote $ZIP"
