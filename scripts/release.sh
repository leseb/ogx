#!/usr/bin/env bash
# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

# =============================================================================
# OGX Release Script
# =============================================================================
#
# Automates the full release process for OGX patch and minor releases.
#
# Prerequisites:
#   - gh CLI authenticated with write access to ogx-ai/ogx
#   - git CLI with access to the remote
#
# Usage:
#   ./scripts/release.sh <version>                    # patch release
#   ./scripts/release.sh <version> --minor             # minor release (creates release branches)
#   ./scripts/release.sh <version> --dry-run           # preview without executing
#   ./scripts/release.sh <version> --rc <N>            # release candidate
#
# Examples:
#   ./scripts/release.sh 0.4.5                         # patch on release-0.4.x
#   ./scripts/release.sh 0.5.0 --minor                 # creates release-0.5.x in ogx + client repos
#   ./scripts/release.sh 0.5.0 --rc 1                  # publishes v0.5.0rc1
#   ./scripts/release.sh 0.4.5 --dry-run               # shows what would happen
#
# =============================================================================

set -euo pipefail

REPO="ogx-ai/ogx"
CLIENT_REPOS=(
    "ogx-ai/ogx-client-python"
    "ogx-ai/ogx-client-typescript"
)
POLL_INTERVAL=15
WORKFLOW_TIMEOUT=600
PUBLISH_TIMEOUT=900

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { echo -e "${CYAN}==>${RESET} ${BOLD}$*${RESET}"; }
ok()    { echo -e "${GREEN}  ✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}  !${RESET} $*"; }
err()   { echo -e "${RED}  ✗${RESET} $*" >&2; }
fatal() { err "$@"; exit 1; }

confirm() {
    local prompt="$1"
    echo -en "${YELLOW}  ? ${prompt} [y/N]${RESET} "
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]]
}

branch_exists() {
    local repo="$1"
    local branch="$2"
    gh api "repos/${repo}/branches/${branch}" >/dev/null 2>&1
}

create_branch_from_main() {
    local repo="$1"
    local branch="$2"
    local main_sha=""

    main_sha=$(gh api "repos/${repo}/git/ref/heads/main" --jq '.object.sha') \
        || fatal "Failed to get main branch SHA for ${repo}"
    gh api "repos/${repo}/git/refs" \
        -f "ref=refs/heads/${branch}" \
        -f "sha=${main_sha}" >/dev/null \
        || fatal "Failed to create branch ${repo}:${branch}"
    ok "Created ${repo}:${branch} from main (${main_sha:0:8})"
}

find_recent_workflow_run_id() {
    local workflow="$1"
    local event="$2"
    local not_before="$3"
    local branch_filter="${4:-}"

    local run_id=""
    local created_at=""
    local head_branch=""

    while IFS=$'\t' read -r run_id created_at head_branch; do
        if [[ -n "$branch_filter" && "$head_branch" != "$branch_filter" ]]; then
            continue
        fi
        if [[ "$created_at" == "$not_before" || "$created_at" > "$not_before" ]]; then
            echo "$run_id"
            return 0
        fi
    done < <(
        gh run list \
            --repo "$REPO" \
            --workflow "$workflow" \
            --event "$event" \
            --limit 20 \
            --json databaseId,createdAt,headBranch \
            --jq '.[] | [.databaseId, .createdAt, (.headBranch // "")] | @tsv'
    )
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

VERSION=""
MINOR=false
DRY_RUN=false
RC=""
REPOS_TO_CREATE=()

usage() {
    sed -n '/^# Usage:/,/^# ====/{/^# ====/d; s/^# \{0,3\}//; p}' "$0"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --minor)   MINOR=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --rc)
            [[ $# -ge 2 ]] || fatal "Option --rc requires a value (e.g., --rc 1)"
            RC="$2"
            shift 2
            ;;
        --help|-h) usage ;;
        -*)        fatal "Unknown option: $1" ;;
        *)
            if [[ -z "$VERSION" ]]; then
                VERSION="$1"; shift
            else
                fatal "Unexpected argument: $1"
            fi
            ;;
    esac
done

[[ -n "$VERSION" ]] || { err "Missing required argument: version"; usage; }

# Validate version format
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    fatal "Invalid version format: ${VERSION}. Expected X.Y.Z (e.g., 0.5.1)"
fi
if [[ -n "$RC" ]] && ! [[ "$RC" =~ ^[1-9][0-9]*$ ]]; then
    fatal "Invalid RC number: ${RC}. Expected a positive integer (e.g., 1)"
fi

# Parse version components
MAJOR=$(echo "$VERSION" | cut -d. -f1)
MINOR_V=$(echo "$VERSION" | cut -d. -f2)
PATCH=$(echo "$VERSION" | cut -d. -f3)
RELEASE_BRANCH="release-${MAJOR}.${MINOR_V}.x"

# Build the tag — RC or final
if [[ -n "$RC" ]]; then
    TAG="v${VERSION}rc${RC}"
    PREPARE_VERSION="${VERSION}rc${RC}"
else
    TAG="v${VERSION}"
    PREPARE_VERSION="${VERSION}"
fi

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

info "Preflight checks"

command -v gh >/dev/null 2>&1 || fatal "gh CLI is not installed"
command -v git >/dev/null 2>&1 || fatal "git CLI is not installed"

# Verify gh is authenticated and has correct repo access
gh auth status >/dev/null 2>&1 || fatal "gh CLI is not authenticated. Run: gh auth login"
gh repo view "$REPO" --json name >/dev/null 2>&1 || fatal "Cannot access ${REPO}. Check your permissions."
ok "gh CLI authenticated with access to ${REPO}"

# Check if tag already exists
if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
    fatal "Release ${TAG} already exists"
fi
ok "Tag ${TAG} is available"

# ---------------------------------------------------------------------------
# Branch setup
# ---------------------------------------------------------------------------

if [[ "$MINOR" == true ]]; then
    info "Minor release: validating ${RELEASE_BRANCH} branch plan"

    # Check if branch already exists
    if branch_exists "$REPO" "$RELEASE_BRANCH"; then
        fatal "Branch ${RELEASE_BRANCH} already exists. Use --minor only for new minor releases."
    fi

    REPOS_TO_CREATE+=("$REPO")

    for client_repo in "${CLIENT_REPOS[@]}"; do
        if branch_exists "$client_repo" "$RELEASE_BRANCH"; then
            ok "Client branch ${client_repo}:${RELEASE_BRANCH} already exists"
            continue
        fi

        REPOS_TO_CREATE+=("$client_repo")
    done
else
    # Verify release branch exists for patch releases
    if ! branch_exists "$REPO" "$RELEASE_BRANCH"; then
        fatal "Branch ${RELEASE_BRANCH} does not exist. Use --minor to create it."
    fi
    ok "Release branch ${RELEASE_BRANCH} exists in ${REPO}"

    for client_repo in "${CLIENT_REPOS[@]}"; do
        if ! branch_exists "$client_repo" "$RELEASE_BRANCH"; then
            fatal "Client branch ${client_repo}:${RELEASE_BRANCH} does not exist. Create it before releasing."
        fi
        ok "Client branch ${client_repo}:${RELEASE_BRANCH} exists"
    done
fi

# ---------------------------------------------------------------------------
# Summary and confirmation
# ---------------------------------------------------------------------------

echo ""
info "Release plan"
echo "  Version:        ${VERSION}"
echo "  Tag:            ${TAG}"
echo "  Release branch: ${RELEASE_BRANCH}"
echo "  Type:           $(if [[ "$MINOR" == true ]]; then echo "minor"; else echo "patch"; fi)$(if [[ -n "$RC" ]]; then echo " (release candidate ${RC})"; fi)"
if [[ "$MINOR" == true ]]; then
    echo "  Branches to create from main:"
    for target_repo in "${REPOS_TO_CREATE[@]}"; do
        echo "    - ${target_repo}:${RELEASE_BRANCH}"
    done
fi
echo ""
echo "  Steps:"
echo "    1. Run 'Prepare release' workflow (updates versions on ${RELEASE_BRANCH})"
echo "    2. Create GitHub release ${TAG} targeting ${RELEASE_BRANCH}"
echo "    3. Wait for packages to build and publish (pypi.yml)"
echo "    4. Verify packages on PyPI and npm"
if [[ -n "$RC" ]]; then
    echo "    5. Post-release automation is skipped for prereleases"
else
    echo "    5. Post-release automation runs automatically"
fi
echo ""

if [[ "$DRY_RUN" == true ]]; then
    warn "[dry-run] Would execute the above steps. Exiting."
    exit 0
fi

confirm "Proceed with release ${TAG}?" || { info "Aborted."; exit 0; }

if [[ "$MINOR" == true ]]; then
    echo ""
    info "Creating release branches"
    for target_repo in "${REPOS_TO_CREATE[@]}"; do
        create_branch_from_main "$target_repo" "$RELEASE_BRANCH"
    done
fi

# ---------------------------------------------------------------------------
# Step 1: Trigger prepare-release workflow
# ---------------------------------------------------------------------------

echo ""
info "Step 1/4: Running 'Prepare release' workflow"

PREPARE_DISPATCHED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
gh workflow run prepare-release.yml \
    --repo "$REPO" \
    --ref "$RELEASE_BRANCH" \
    -f "version=${PREPARE_VERSION}" \
    -f "release_branch=${RELEASE_BRANCH}"

# Find the run ID for the workflow we just dispatched
RUN_ID=""
ATTEMPTS=0
MAX_ATTEMPTS=24
while [[ $ATTEMPTS -lt $MAX_ATTEMPTS ]]; do
    RUN_ID="$(find_recent_workflow_run_id "prepare-release.yml" "workflow_dispatch" "$PREPARE_DISPATCHED_AT" "$RELEASE_BRANCH" || true)"
    if [[ -n "$RUN_ID" ]]; then
        break
    fi
    sleep 5
    ATTEMPTS=$((ATTEMPTS + 1))
done

if [[ -z "$RUN_ID" ]]; then
    fatal "Could not find the newly triggered prepare-release workflow run"
fi

ok "Workflow triggered (run ${RUN_ID})"
echo "  https://github.com/${REPO}/actions/runs/${RUN_ID}"

# Poll for completion
ELAPSED=0
while [[ $ELAPSED -lt $WORKFLOW_TIMEOUT ]]; do
    STATUS=$(gh run view "$RUN_ID" --repo "$REPO" --json status,conclusion --jq '.status')
    if [[ "$STATUS" == "completed" ]]; then
        CONCLUSION=$(gh run view "$RUN_ID" --repo "$REPO" --json conclusion --jq '.conclusion')
        if [[ "$CONCLUSION" == "success" ]]; then
            ok "Prepare release completed successfully"
            break
        else
            fatal "Prepare release failed with conclusion: ${CONCLUSION}. Check: https://github.com/${REPO}/actions/runs/${RUN_ID}"
        fi
    fi
    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

if [[ $ELAPSED -ge $WORKFLOW_TIMEOUT ]]; then
    fatal "Prepare release timed out after ${WORKFLOW_TIMEOUT}s. Check: https://github.com/${REPO}/actions/runs/${RUN_ID}"
fi

# ---------------------------------------------------------------------------
# Step 2: Create GitHub release
# ---------------------------------------------------------------------------

echo ""
info "Step 2/4: Creating GitHub release ${TAG}"

RELEASE_ARGS=(
    --repo "$REPO"
    --target "$RELEASE_BRANCH"
    --generate-notes
)

if [[ -n "$RC" ]]; then
    RELEASE_ARGS+=(--prerelease)
    RELEASE_ARGS+=(--title "${TAG}")
else
    RELEASE_ARGS+=(--title "OGX ${TAG}")
fi

PUBLISH_TRIGGERED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
RELEASE_URL=$(gh release create "$TAG" "${RELEASE_ARGS[@]}" 2>&1 | tail -1)
ok "Release created: ${RELEASE_URL}"

# ---------------------------------------------------------------------------
# Step 3: Wait for build and publish workflow
# ---------------------------------------------------------------------------

echo ""
info "Step 3/4: Waiting for build and publish workflow"

# The pypi.yml workflow triggers on release:published — give it a moment to start
sleep 10

# Find the pypi.yml run triggered by this release
PYPI_RUN_ID=""
ATTEMPTS=0
MAX_ATTEMPTS=12
while [[ $ATTEMPTS -lt $MAX_ATTEMPTS ]]; do
    PYPI_RUN_ID="$(find_recent_workflow_run_id "pypi.yml" "release" "$PUBLISH_TRIGGERED_AT" || true)"
    if [[ -n "$PYPI_RUN_ID" ]]; then
        break
    fi
    sleep 5
    ATTEMPTS=$((ATTEMPTS + 1))
done

if [[ -z "$PYPI_RUN_ID" ]]; then
    warn "Could not find the pypi.yml workflow run automatically."
    warn "Check https://github.com/${REPO}/actions/workflows/pypi.yml"
    warn "The release ${TAG} was created — packages should publish when the workflow completes."
else
    ok "Build workflow triggered (run ${PYPI_RUN_ID})"
    echo "  https://github.com/${REPO}/actions/runs/${PYPI_RUN_ID}"

    ELAPSED=0
    while [[ $ELAPSED -lt $PUBLISH_TIMEOUT ]]; do
        STATUS=$(gh run view "$PYPI_RUN_ID" --repo "$REPO" --json status,conclusion --jq '.status')
        if [[ "$STATUS" == "completed" ]]; then
            CONCLUSION=$(gh run view "$PYPI_RUN_ID" --repo "$REPO" --json conclusion --jq '.conclusion')
            if [[ "$CONCLUSION" == "success" ]]; then
                ok "Build and publish completed successfully"
                break
            else
                fatal "Build/publish workflow finished with: ${CONCLUSION}. Check: https://github.com/${REPO}/actions/runs/${PYPI_RUN_ID}"
            fi
        fi
        # Show progress
        ELAPSED=$((ELAPSED + POLL_INTERVAL))
        printf "\r  … waiting (%ds / %ds)" "$ELAPSED" "$PUBLISH_TIMEOUT"
        sleep "$POLL_INTERVAL"
    done
    echo ""

    if [[ $ELAPSED -ge $PUBLISH_TIMEOUT ]]; then
        warn "Build workflow still running after ${PUBLISH_TIMEOUT}s."
        warn "Check: https://github.com/${REPO}/actions/runs/${PYPI_RUN_ID}"
    fi
fi

# ---------------------------------------------------------------------------
# Step 4: Verify packages
# ---------------------------------------------------------------------------

echo ""
info "Step 4/4: Verifying published packages"

if [[ -n "$RC" ]]; then
    PYPI_API_BASE="https://test.pypi.org/pypi"
    PYPI_PROJECT_BASE="https://test.pypi.org/project"
    PYPI_LABEL="TestPyPI"
else
    PYPI_API_BASE="https://pypi.org/pypi"
    PYPI_PROJECT_BASE="https://pypi.org/project"
    PYPI_LABEL="PyPI"
fi

check_pypi() {
    local pkg="$1"
    local ver="$2"
    local url="${PYPI_API_BASE}/${pkg}/${ver}/json"
    if curl -sf "$url" >/dev/null 2>&1; then
        ok "${pkg}==${ver} on ${PYPI_LABEL}"
        return 0
    else
        warn "${pkg}==${ver} not yet on ${PYPI_LABEL}"
        return 1
    fi
}

check_npm() {
    local pkg="$1"
    local ver="$2"
    local url="https://registry.npmjs.org/${pkg}/${ver}"
    if curl -sf "$url" >/dev/null 2>&1; then
        ok "${pkg}@${ver} on npm"
        return 0
    else
        warn "${pkg}@${ver} not yet on npm"
        return 1
    fi
}

# For RCs the PyPI version format uses rcN suffix
if [[ -n "$RC" ]]; then
    PYPI_VERSION="${VERSION}rc${RC}"
    NPM_VERSION="${VERSION}-rc${RC}"
else
    PYPI_VERSION="${VERSION}"
    NPM_VERSION="${VERSION}"
fi

ALL_PUBLISHED=true
check_pypi "ogx" "$PYPI_VERSION" || ALL_PUBLISHED=false
check_pypi "ogx-api" "$PYPI_VERSION" || ALL_PUBLISHED=false
check_pypi "ogx-client" "$PYPI_VERSION" || ALL_PUBLISHED=false
check_npm "ogx-client" "$NPM_VERSION" || ALL_PUBLISHED=false

if [[ "$ALL_PUBLISHED" == true ]]; then
    ok "All packages published"
else
    echo ""
    warn "Some packages are not yet available. They may still be propagating."
    warn "Check manually:"
    echo "    ${PYPI_PROJECT_BASE}/ogx/${PYPI_VERSION}/"
    echo "    ${PYPI_PROJECT_BASE}/ogx-api/${PYPI_VERSION}/"
    echo "    ${PYPI_PROJECT_BASE}/ogx-client/${PYPI_VERSION}/"
    echo "    https://www.npmjs.com/package/ogx-client/v/${NPM_VERSION}"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "Release ${TAG} complete"
echo ""
echo "  Release:     ${RELEASE_URL:-https://github.com/${REPO}/releases/tag/${TAG}}"
echo "  ${PYPI_LABEL}:     ${PYPI_PROJECT_BASE}/ogx/${PYPI_VERSION}/"
echo "  npm:         https://www.npmjs.com/package/ogx-client/v/${NPM_VERSION}"
echo "  Docker:      https://hub.docker.com/r/ogx-ai/ogx/tags"
echo ""
if [[ -z "$RC" ]]; then
    echo "  Post-release automation will:"
    echo "    • Tag main with v${MAJOR}.${MINOR_V}.$((PATCH + 1))-dev"
    echo "    • Open PR to bump fallback_version on main"
    echo "    • Open PR to update npm lockfile on ${RELEASE_BRANCH}"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
