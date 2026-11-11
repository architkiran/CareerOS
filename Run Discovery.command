#!/bin/zsh
# Career OS 2.0: fetch sources, apply the hard eligibility rules, write today's digest.
# Usage: double-click, or `./Run\ Discovery.command [fast|all]` (default: fast).
set -euo pipefail
career_repo="${0:A:h}"
cd "$career_repo"
export PYTHONPATH="$career_repo/src${PYTHONPATH:+:$PYTHONPATH}"
py="$career_repo/.venv/bin/python"
mode="${1:-fast}"

# LCA .xlsx import needs openpyxl; install it once if missing (free, from PyPI).
"$py" -c "import openpyxl" 2>/dev/null || "$py" -m pip install -q "openpyxl>=3.1" 2>/dev/null \
  || uv pip install -q --python "$py" "openpyxl>=3.1" 2>/dev/null \
  || print "Note: could not install openpyxl. LCA .xlsx import will be unavailable (CSV still works)."

"$py" -m careeros migrate
if [[ "$mode" == "all" ]]; then
  print "Running every source, including ~120 Workday career sites. The first run can take over an hour."
  "$py" -m careeros discover --file config/sources.discovered.toml
else
  print "Fast pass: community list, Greenhouse, Lever, Ashby (a few minutes)."
  print "Run './Run Discovery.command all' later to include Workday career sites."
  "$py" -m careeros discover --file config/sources.discovered.toml \
    --types community,greenhouse,lever,ashby
fi
print ""
print "Done. Start CareerOS and open the Today page, or read the digest in exports/."
