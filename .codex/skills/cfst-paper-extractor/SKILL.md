---
name: cfst-paper-extractor
description: Extract specimen-level data from processed CFST paper folders into schema-v2 JSON, validate ordinary-CFST inclusion, provenance, and physical plausibility, orchestrate isolated one-paper workers, and publish canonical JSON outputs. Use when Codex needs to work from `processed/` paper directories that already contain markdown, parser JSON, `images/`, and `tables/`, repair or review CFST JSON outputs, or normalize raw MinerU parses into that processed layout before extraction.
---

# CFST Paper Extractor

Use only bundled files in this skill. Do not depend on external metadata manifests.
Prefer existing `processed/` paper folders directly. If a paper folder already contains one top-level `.md`, one top-level parser `.json`, `images/`, `tables/`, and `tables/manifest.json`, skip preprocessing; the long paper filenames do not need to be normalized before extraction.

## Use This Workflow

0. If starting from a raw MinerU batch directory (not yet in processed layout), normalize it first:

```bash
python .codex/skills/cfst-paper-extractor/scripts/normalize_batch.py \
  --batch-dir batch1 \
  --output-dir processed
```

This creates `processed/[A1-1]/`, `processed/[A1-2]/`, etc. with one markdown (enhanced with table image references), one parser JSON, `images/`, `tables/`, and `tables/manifest.json`. Use `--no-inject-table-images` to skip injecting `![caption](tables/filename)` references into the markdown.

1. Prepare a batch workspace from processed paper folders.

```bash
python .codex/skills/cfst-paper-extractor/scripts/prepare_batch.py \
  --processed-root processed \
  --output-root <output_root>
```

This creates `manifests/`, `tmp/`, `output/`, and `logs/`. It does not copy or rename the paper folders under `processed/`.

If you only have raw MinerU output and not the processed layout yet, run `scripts/reorganize_parsed_with_tables.py` first to create a compatible paper-folder structure. Do that only when `processed/` is missing or incomplete.

2. Follow the **Parent Playbook** below for worker orchestration (worktree creation, worker briefs, validation, retries), publication, and optional checkpoints.

## Parent Playbook

Use this sequence as the canonical parent-agent orchestration path. If you follow these steps, the parent agent does not need to inspect bundled script internals.

### Parent-Owned Artifacts

- `<output_root>/manifests/batch_manifest.json`: batch summary, paper titles, and processed-layout inspection results.
- `<output_root>/manifests/worker_jobs.json`: source of truth for `paper_id`, `paper_dir_relpath`, worker temp JSON path, and final output path.
- `<output_root>/manifests/batch_state.json`: parent-owned per-paper state tracker.
- `<output_root>/tmp/<paper_id>/<paper_id>.json`: sandbox-visible temp JSON path.
- `worker_jobs.json[*].worker_output_json_path`: on-disk host-backed temp JSON path; workers must write here so the sandbox bind mount can see the same file at `<output_root>/tmp/<paper_id>/<paper_id>.json`.
- `<output_root>/output/<paper_id>.json`: canonical published artifact; parent writes here only through `publish_validated_output.py`.

### Direct-Use Sequence

1. Ensure the repository has a git `HEAD`. If it does not, initialize it once:

```bash
python .codex/skills/cfst-paper-extractor/scripts/bootstrap_git_repo.py \
  --repo-root . \
  --initial-empty-commit
```

2. Prepare the batch workspace:

```bash
python .codex/skills/cfst-paper-extractor/scripts/prepare_batch.py \
  --processed-root processed \
  --output-root <output_root>
```

3. Read `<output_root>/manifests/worker_jobs.json`. Process only items whose `status` is `prepared`. Do not reconstruct paper paths from `paper_id`; use `paper_dir_relpath` from this file exactly as written.
Use `worker_output_json_path` from this file as the on-disk host write target for the worker's temp JSON.

4. For each prepared job, create one isolated worker worktree:

```bash
python .codex/skills/cfst-paper-extractor/scripts/git_worktree_isolation.py create \
  --paper-dir '<paper_dir_relpath>' \
  --output-dir <output_root>/tmp/<paper_id>
```

This returns a JSON object. Record at least:

- `worktree_path`
- `branch`
- `paper_rel`
- `output_dir`
- `output_host_path`

5. Spawn exactly one worker sub-agent for that paper. Pass only one paper per worker and include this ownership tuple:

- `paper_id=<paper_id>`
- `worktree_path=<worktree_path>`
- `paper_dir_relpath=<paper_dir_relpath>`
- `output_dir=<output_root>/tmp/<paper_id>`
- `output_host_path=<output_host_path>`
- `temp_json_workspace_path=<output_root>/tmp/<paper_id>/<paper_id>.json`
- `temp_json_host_path=<worker_output_json_path_from_worker_jobs.json>`

6. Use this worker brief template verbatim except for placeholder substitution:

```text
Own exactly one CFST paper.

Inputs:
- paper_id: <paper_id>
- worktree_path: <worktree_path>
- paper_dir_relpath: <paper_dir_relpath>
- output_dir: <output_root>/tmp/<paper_id>
- output_host_path: <output_host_path>
- temp_json_workspace_path: <output_root>/tmp/<paper_id>/<paper_id>.json
- temp_json_host_path: <worker_output_json_path_from_worker_jobs.json>

Required reading inside the worktree:
- .codex/skills/cfst-paper-extractor/references/extraction-rules.md
- .codex/skills/cfst-paper-extractor/references/single-flow.md

Authoritative sources for this task, in order:
- the owned paper folder at <paper_dir_relpath>
- .codex/skills/cfst-paper-extractor/references/extraction-rules.md
- .codex/skills/cfst-paper-extractor/references/single-flow.md
- the exact commands and paths in this brief

Do not use other files to infer schema, validation, or path behavior:
- do not read .codex/skills/cfst-paper-extractor/SKILL.md
- do not read .codex/skills/cfst-paper-extractor/scripts/*.py to infer rules or parameters
- do not inspect runs/, tmp/, output/, or other papers for schema examples
- only inspect a named helper script if the parent-provided command itself fails with a concrete runtime blocker that the sources above do not explain

Execution rules:
- Work only on this one paper.
- Do not revert unrelated changes.
- Write exactly one JSON file on disk, at `temp_json_host_path`.
- Do not create or modify a worktree-local relative `runs/...` JSON path.
- `temp_json_workspace_path` is the sandbox-visible path of that same file after `output_host_path` is bound into `output_dir`.
- For every specimen-bearing table, locate the table image from the `![caption](tables/filename)` reference in the markdown (injected before each `<table>` tag), then reconcile the markdown text table against that image using `view_image`. If no injected reference is present, use `tables/manifest.json` to find the corresponding image.
- Use the top-level parser `.json` only for page/block localization fallback. Do not use it as a third numeric or unit source.
- Do not run local OCR or any other third recognition pipeline on the paper images.
- When listing the paper directory to identify the parser `.json`, exclude `paper_manifest.json` if present — it is preprocessing metadata, not the parser output.
- Run the validation command exactly as written below; do not rewrite paths or create a second output location.
- After writing JSON, validate inside the sandbox with:
  python .codex/skills/cfst-paper-extractor/scripts/worker_sandbox.py \
    --worktree-path <worktree_path> \
    --paper-dir-relpath <paper_dir_relpath> \
    --output-dir <output_root>/tmp/<paper_id> \
    --host-output-dir <output_host_path> \
    --cwd-mode workspace \
    -- \
    python3 .codex/skills/cfst-paper-extractor/scripts/validate_single_output.py \
      --json-path <output_root>/tmp/<paper_id>/<paper_id>.json \
      --strict-rounding
- If validation fails, repair once before returning.
- If the validator or sandbox reports a path, mount, or sandbox startup failure, stop and return that failure to the parent; do not move the JSON to a different path and do not write a second copy elsewhere.

Return exactly:
- paper_id
- temp_json path (`temp_json_workspace_path`)
- validation pass/fail
- failure reason if any
```

7. When a worker finishes:

- If the worker reports success and the temp JSON exists, mark the paper ready for publication.
- If the worker fails with a schema, evidence, or extraction decision problem, create a fresh worktree and retry once with a focused correction prompt that includes the exact failure.
- If the worker fails with a path, mount, or sandbox startup problem, treat that as a parent-side orchestration issue. Fix the command or worktree/output binding first, then rerun on a fresh worktree; do not ask the worker to relocate outputs on its own.
- If the retry also fails, mark the paper failed and continue the batch. Do not block unrelated papers.

While a worker remains in normal `running` state and has not reported a concrete failure, interrupt, or terminal result, do not interrupt, replace, or redirect it. One-paper extraction can legitimately exceed a short wait timeout. Use generous waits and only intervene on terminal status or concrete blockers.

8. After the worker exits, confirm the temp JSON exists at `worker_output_json_path` in the parent workspace. This same file must also be visible inside the sandbox at `<output_root>/tmp/<paper_id>/<paper_id>.json` because `--host-output-dir` binds the parent directory into `output_dir`.

9. Always clean up each finished worker worktree, whether the paper succeeded or failed:

```bash
python .codex/skills/cfst-paper-extractor/scripts/git_worktree_isolation.py remove \
  --worktree-path '<worktree_path>' \
  --delete-branch
```

10. After all prepared papers finish, publish all validated temp outputs:

```bash
python .codex/skills/cfst-paper-extractor/scripts/publish_validated_output.py \
  --batch-manifest <output_root>/manifests/batch_manifest.json \
  --tmp-root <output_root>/tmp \
  --output-dir <output_root>/output \
  --publish-log <output_root>/logs/publish_log.jsonl \
  --strict-rounding
```

11. If repository policy requires checkpoints, run them only after publication:

```bash
python .codex/skills/cfst-paper-extractor/scripts/checkpoint_output_commits.py \
  --processed-count <published_plus_failed_count> \
  --output-dir <output_root>/output
```

12. The parent agent's final report should distinguish:

- papers skipped before spawn because `worker_jobs.json.status != prepared`
- papers that failed after retry
- papers successfully published to `output/`

## Respect These Contracts

### Batch orchestration

- Use a parent-child model for every multi-paper extraction.
- Regardless of paper count, extraction work must always be executed by a spawned worker sub-agent; even a single-paper extraction must not be performed directly by the parent agent.
- Spawn one worker sub-agent per prepared paper folder from `processed/`.
- Cap concurrency at 5 active paper workers.
- Declare worker ownership at launch: one paper folder, one worker-local temp JSON path, and one worker worktree path.
- Read `worker_jobs.json` after batch preparation and treat it as the only source of truth for `paper_dir_relpath`, temp JSON path, and per-paper readiness.
- Treat the repository as concurrently modified; workers must ignore unrelated changes and must not revert anything outside their ownership.
- Keep the parent focused on orchestration, validation review, retries, and publication after workers launch.
- If a worker is still running normally, do not interrupt it just because a local wait call timed out. Extraction may take longer than the nominal wait window.
- Retry a failed paper once with a focused correction prompt. If it still fails, return the failure reason and temp JSON path.

### Worker execution

- Process exactly one prepared paper folder.
- Worker-authoritative sources are the owned paper folder, `references/extraction-rules.md`, `references/single-flow.md`, and the parent-supplied worker brief.
- Do not inspect `SKILL.md`, `scripts/`, `runs/`, prior outputs, or other papers to infer schema, validation, or path behavior. Only inspect a named helper script when a concrete runtime blocker remains unresolved after following the documented command.
- When both `temp_json_workspace_path` and `temp_json_host_path` are provided, write the JSON on disk to `temp_json_host_path` and validate that same file through `temp_json_workspace_path` inside the sandbox bind mount.
- Require these inputs: exactly one top-level `.md`, exactly one top-level parser `.json`, `images/`, `tables/`, and `tables/manifest.json`.
- Resolve the actual markdown and parser JSON filenames by listing the paper directory contents; do not assume short `<paper_token>` filenames.
- Read the markdown first for context, then read the top-level parser `.json` only for page/block localization and page fallback, then inspect the relevant `tables/` images and setup images with `view_image`.
- Use `tables/manifest.json` as a fast index when matching captions or block ids to cropped table images, but treat the image itself as the authority.
- Extract table data by reconciling the markdown text table against the corresponding `tables/` image opened with `view_image`; do not extract specimen rows from markdown tables alone.
- Do not run local OCR or introduce any third recognition pipeline. The extraction truth sources are the markdown text plus the human-inspected table/setup images; the parser `.json` is localization support only.
- Resolve `fc_basis` by following `references/extraction-rules.md` `## 8. Concrete-Strength Basis Rules`. Before interpreting symbols such as `fck`, `fc`, `f'c`, or `Fc`, first search nearby material/property text, table headers, and footnotes for code-defined grade notation such as Chinese `C30`, `C40`, `C50`, `C60` or Eurocode `C60/75`. In Chinese GB/T context, those `Cxx` grades sit above nearby bare `fck` / `fc` symbols in the priority order; when the reported measured value clearly matches the cube-strength system, keep `fc_type` consistent with that stored value instead of mirroring sloppy symbol usage. Do not assign `fc_basis` without consulting those rules.
- Keep `fc_type` in validator-compatible form only: `cube`, `cylinder`, `prism`, `unknown`, or sized forms such as `Cube 150` or `Cylinder 100x200`. Never store symbolic notation like `fck/fcu/f'c/fc` or explanatory phrases in `fc_type`.
- Inside the worker sandbox, use `scripts/safe_calc.py` for conversions, rounding, and derived values; do not do ad hoc arithmetic.
- Preserve eccentricity signs exactly as source evidence shows them.
- Do not exclude ordinary CFST specimens from the dataset based on the sign pattern of `e1` and `e2` alone.
- Preserve recycled aggregate replacement ratio `R%` in `r_ratio`.

### Output shape

- Produce the schema-v2.1 top-level keys `schema_version`, `paper_id`, `is_valid`, `is_ordinary_cfst`, `reason`, `ordinary_filter`, `ref_info`, `paper_level`, `Group_A`, `Group_B`, and `Group_C`.
- Treat `is_valid=false` as an unusable paper with empty specimen groups.
- Treat `is_valid=true` as usable; extract all specimens regardless of ordinary status.
- Tag each specimen with `is_ordinary` and `ordinary_exclusion_reasons` using the two-tier evaluation in `references/extraction-rules.md` §2.
- Derive `is_ordinary_cfst` from specimen flags: `true` when at least one specimen has `is_ordinary=true`.
- Keep worker output in `tmp/<paper_id>/<paper_id>.json` only.
- Let the parent publish the final JSON into `output/<paper_id>.json`; workers must never write final outputs directly.
- Treat published JSON as canonical. Any project-specific tabular conversion should happen outside this skill.

### Git and sandbox isolation

- Require a git repository with `HEAD` before creating worktrees.
- Initialize one when needed:

```bash
python .codex/skills/cfst-paper-extractor/scripts/bootstrap_git_repo.py \
  --repo-root . \
  --initial-empty-commit
```

- Create every worker environment with `scripts/git_worktree_isolation.py create`.
- Launch every worker only through `scripts/worker_sandbox.py`.
- The paper folder is mounted read-only inside the sandbox; only the declared worker-local temp output directory is writable. For parent-managed batches, bind that writable directory from the parent workspace with `--host-output-dir` so temp JSON survives worktree deletion.
- `scripts/safe_calc.py` and `scripts/validate_single_output.py` are sandbox-only helpers in this variant; they fail fast if `CFST_SANDBOX=1` is missing.
- Require `bubblewrap` or `bwrap`.
- Treat sandbox startup failure as fatal; do not fall back to unsandboxed execution.
- Remove finished worktrees with `scripts/git_worktree_isolation.py remove`.

## Use These Bundled Scripts

- `scripts/prepare_batch.py`: preferred entry point; discover processed paper folders, verify they have markdown/json/images/tables, and write manifests/state for worker orchestration without copying paper contents.
- `scripts/normalize_batch.py`: preferred entry point for converting raw MinerU batch directories into the processed layout; wraps `reorganize_parsed_with_tables.py` with bracket-prefixed folder names and table image injection into markdown by default.
- `scripts/reorganize_parsed_with_tables.py`: lower-level normalization helper; use `--inject-table-images` to insert table image references into the output markdown before each `<table>` tag. Called internally by `normalize_batch.py`.
- `scripts/validate_single_output.py`: sandbox-only validator for one worker-local schema-v2 JSON; checks shape, provenance, plausibility, ordinary-filter consistency, and rounding.
- `scripts/publish_validated_output.py`: revalidate worker outputs, publish final JSON, and append a publish log.
- `scripts/git_worktree_isolation.py`: create and remove per-paper git worktrees. In the parent flow, `create` also returns `output_host_path`, the persistent host directory that should be bound into `worker_sandbox.py`.
- `scripts/worker_sandbox.py`: mandatory worker launcher; it mounts paper inputs read-only and the worker-local output directory read-write. Use `--host-output-dir` in parent-managed batches so worker temp outputs persist outside the worktree; never bypass it.
- `scripts/bootstrap_git_repo.py`: initialize a repo and optional empty commit so worktree execution can start.
- `scripts/checkpoint_output_commits.py`: commit or push published outputs at fixed intervals when the repository policy calls for output-only checkpoints.
- `scripts/safe_calc.py`: sandbox-only arithmetic helper for deterministic conversions and derived geometry values instead of handwritten calculations.

## Read These References

- `references/extraction-rules.md`: use for schema details, group mapping, required fields, evidence format, loading-mode decisions, numeric rules, mandatory table-image reconciliation, and invalid-output handling.
- `references/single-flow.md`: use for one-paper worker sequencing, required input layout, mandatory table-image reconciliation, setup-figure rules, and validation expectations.
