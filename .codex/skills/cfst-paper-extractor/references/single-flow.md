# Single-Paper Worker Flow V2.1

Use this file as the worker execution contract for one paper.

Section map:

- `## 1-3`: enforce worker scope, required inputs, and execution order.
- `## 4-5`: apply validity and ordinary-CFST gates.
- `## 6-10`: resolve setup figures, reconcile mandatory table images with markdown tables, resolve concrete-strength basis, and preserve numeric and evidence traces.
- `## 11-12`: enforce validation expectations and final output goals.

## 1. Worker Contract

- process exactly one paper folder
- treat the parent-supplied worker brief plus this file and `references/extraction-rules.md` as the complete worker contract
- inspect the owned paper folder directly in the worktree for reading; run sandbox-only helpers only through the parent-provided `worker_sandbox.py` command
- `scripts/safe_calc.py` and `scripts/validate_single_output.py` require `CFST_SANDBOX=1`; do not call them directly from the parent shell
- read only the owned paper folder and the two worker references by default
- do not read `SKILL.md`, `runs/`, prior outputs, or `scripts/` to infer schema, validation, or path rules
- when the parent provides both `temp_json_host_path` and `temp_json_workspace_path`, write the JSON on disk to `temp_json_host_path`; the workspace path is the sandbox-visible alias of that same file
- never create or rely on a worktree-local relative `runs/...` JSON path
- if a concrete runtime blocker remains unresolved after following the documented command, you may inspect the one named helper script involved and report that you did so
- write only to the worker-local temp directory
- never write directly to final published output
- treat repository as non-exclusive runtime; other workers may change unrelated files concurrently
- do not edit, revert, or publish outside declared worker ownership

## 2. Required Input Layout

The worker input folder must contain:

- exactly one top-level `.md` file
- exactly one top-level parser `.json` file (exclude preprocessing metadata such as `paper_manifest.json` when counting)
- `images/`
- `tables/`
- `tables/manifest.json`

Long paper filenames are allowed and do not need to be renamed. Resolve the markdown and parser JSON filenames by listing the paper folder contents instead of synthesizing `<paper_token>` names.
The parser `.json` is not optional bookkeeping. Read it for page indices, block/page localization, and page fallback when markdown alone does not expose page numbers clearly. Do not use it as a third numeric/unit truth source for specimen extraction.

If any required path is missing, or if the top level contains zero or multiple `.md` / `.json` candidates, fail fast and report the missing or ambiguous path.

## 3. Mandatory Execution Order

1. Read `references/extraction-rules.md` and this file.
2. Verify required input files exist and identify the actual markdown/json filenames in the paper directory.
3. Read markdown first for global context.
4. Read the top-level parser `.json` only for page indices, page/block localization, and fallback page recovery when markdown omits page markers.
5. Read `tables/manifest.json` when available to map table captions or block ids to cropped table images.
6. Locate the relevant `tables/` images for every specimen-bearing table referenced by the markdown and inspect them with `view_image`. When the markdown contains injected `![caption](tables/filename)` image references before `<table>` tags, use those references directly to locate the corresponding table images. Fall back to `tables/manifest.json` caption matching when the markdown does not contain injected references.
7. Reconcile the markdown text tables against those same `tables/` images before extracting any specimen row values.
8. Resolve concrete-strength basis evidence from `Materials`, `Specimens`, `Concrete properties`, notation sections, and table footnotes before assigning `fc_basis`. First search for nearby concrete-strength-grade signals such as `C30`, `C40`, `C50`, `C60`, or `C60/75`, then interpret symbols such as `fck`, `fc`, `f'c`, or `Fc`.
9. Run the validity gate.
10. Run the ordinary-CFST Tier 1 paper-level preconditions.
11. Resolve the setup figure from markdown-linked image evidence.
12. Extract specimen rows using reconciled markdown-plus-image table evidence.
13. When a paper reports grouped average measured capacity for an explicit repeated-specimen group, assign that same average `n_exp` to each defensibly identified member row and mark `group_average_n_exp`.
14. Normalize units and derived values with `scripts/safe_calc.py`.
15. Run the ordinary-CFST Tier 2 per-specimen evaluation and tag each specimen with `is_ordinary` and `ordinary_exclusion_reasons`.
16. Derive paper-level `is_ordinary_cfst` and `ordinary_filter` summary from specimen flags.
17. Build schema v2.1 JSON.
18. Write that JSON on disk to `temp_json_host_path` from the worker brief. Do not create a worktree-local relative `runs/...` JSON path.
19. Validate that same file through `temp_json_workspace_path` with the parent-provided `worker_sandbox.py` command.
20. If validation fails for schema, data, or evidence reasons, repair once, overwrite the same host-backed JSON path, and validate once more.
21. If validation fails for path, mount, sandbox startup, or ownership reasons, stop and report the failure; do not relocate the JSON and do not create a second copy elsewhere.

## 4. Validity Gate

Stop as invalid when the paper is:

- FE-only
- theory-only or review-only
- non-column CFST study without recoverable specimen data
- no usable ultimate experimental load data

Grouped average measured capacities do not make a paper invalid by themselves. If the repeated-specimen group membership is explicit enough to map the same reported average to each member row defensibly, keep the paper valid and mark the affected rows with `group_average_n_exp`.

For invalid papers:

- `is_valid=false`
- `is_ordinary_cfst=false`
- empty specimen groups
- non-empty single-line `reason`

## 5. Ordinary-CFST Gate (Two-Tier, Specimen-Level)

Even when `is_valid=true`, evaluate each specimen individually for ordinary-CFST inclusion using the two-tier model defined in `references/extraction-rules.md` §2.

### Tier 1 — Paper-Level Preconditions

Check once for the whole paper. If any fails, set all specimens to `is_ordinary=false` with the paper-level reason in each specimen's `ordinary_exclusion_reasons`.

- `test_temperature = ambient`
- `loading_regime = static`
- no paper-wide durability conditioning (fire, corrosion, freeze-thaw)

### Tier 2 — Per-Specimen Evaluation

When Tier 1 passes, check each specimen individually:

- `section_shape in {circular, square, rectangular, round-ended}`
- `steel_type = carbon_steel`
- `concrete_type in {normal, high_strength, recycled}`
- `loading_pattern = monotonic`
- eccentric compression is single-direction when present
- no strengthening or special confinement
- recycled aggregate `R%` is explicitly extractable when `concrete_type = recycled`

Tag each specimen:

- `is_ordinary = true` with `ordinary_exclusion_reasons = []` when all conditions pass
- `is_ordinary = false` with non-empty `ordinary_exclusion_reasons` listing each failing condition

### Paper-Level Derivation

After all specimens are tagged, derive paper-level fields:

- `is_ordinary_cfst` = true when at least one specimen has `is_ordinary=true`
- `ordinary_filter.include_in_dataset` = `is_ordinary_cfst`
- `ordinary_filter.ordinary_count` = count of ordinary specimens
- `ordinary_filter.total_count` = total specimen count
- `ordinary_filter.special_factors`: paper-level special tags
- `ordinary_filter.exclusion_reasons`: paper-level exclusion summaries

## 6. Setup Figure Resolution

- prefer markdown mentions like `Fig.`, `Figure`, `加载装置`, `试验装置`
- locate the exact markdown image reference
- open that referenced image under `images/`
- determine loading mode from visual evidence when possible
- do not decide loading mode from text alone when setup image evidence exists

Store the resolved setup trace in:

- `paper_level.loading_mode`
- `paper_level.setup_figure`
- specimen `loading_mode`
- specimen `evidence.setup_image`

## 7. Mandatory Table Reconciliation Rules

Relevant `tables/` images are mandatory evidence for every specimen-bearing table used in extraction. Do not extract specimen rows from markdown tables alone, even when the markdown text looks clean.

For each specimen-bearing table:

- when the markdown includes an injected `![caption](tables/filename)` reference immediately before a `<table>` tag, that reference identifies the corresponding table image; open that image with `view_image` for reconciliation
- when no injected reference is present, read the markdown table and inspect the corresponding `tables/` image with `view_image`, using `tables/manifest.json` as a helper index when it improves table-image matching
- use markdown as a locator for table id, candidate row labels, and nearby notes
- use the `tables/` image as the authority for row boundaries, merged cells, scalar assignment, units, symbols, and signs
- confirm row/header alignment across both sources before writing any specimen field
- do not run local OCR or introduce any third recognition pipeline on the paper images
- use the top-level parser `.json` only for localization fallback such as recovering page numbers or block/page anchors

If markdown and image disagree:

- prefer the `tables/` image for numeric values, units, signs, and merged-cell interpretation
- use markdown and nearby prose only to help map row labels, table ids, and footnotes
- preserve a `quality_flags` marker such as `markdown_table_mismatch`

If a needed specimen-bearing table has no corresponding readable `tables/` image, stop with a clear failure reason instead of extracting from markdown alone.

## 8. Concrete-Strength Basis Rules

- `fc_type` must stay in validator-compatible measurement form only: `cube`, `cylinder`, `prism`, `unknown`, or sized forms such as `Cube 150`, `Cylinder 100x200`, or `Prism 150x150x300`
- never store shorthand notation or explanatory prose such as `fck`, `fcu`, `f'c`, `fc`, or `Prism-equivalent fck converted from Cube 150` inside `fc_type`

- treat explicit material/property evidence as first priority: `Materials`, `Specimens`, `Concrete properties`, notation sections, table headers, and table footnotes outrank shorthand labels such as `C60`
- before interpreting notation symbols, search nearby material/property text, the same sentence or paragraph, table headers, and footnotes for concrete-strength-grade signals such as `C30`, `C40`, `C50`, `C60`, or `C60/75`
- resolve `fc_basis` before doing any normalization or downstream interpretation of `fc_value`
- map explicit `150 mm cube` or equivalent standard-cube wording to `fc_basis = cube`
- map explicit cylinder wording, cylinder dimensions, `ASTM C39`, `JIS A 1108`, `JIS A 1132`, or equivalent cylinder-test descriptions to `fc_basis = cylinder`
- map explicit prism-strength / axial-compressive-strength wording to `fc_basis = prism`
- in Chinese GB/T 50010-type context, treat bare `C30`, `C40`, `C50`, `C60`, `C70`, and similar `C` grades as code-defined cube-strength grades unless the paper itself contradicts that reading
- in the same Chinese GB/T 50010-type context, a nearby single-grade `C30` / `C40` / `C50` / `C60`-style signal belongs to the code-context layer and must be checked before a nearby bare `fck` / `fc` symbol is allowed to lock `fc_basis = prism`
- in the same Chinese GB/T 50010-type context, when a reported measured strength value is numerically consistent with the nearby cube-grade system and clearly inconsistent with the prism/axial reading of a nearby `fck` / `fc` symbol, you may resolve `fc_basis = cube`; keep `fc_type` consistent with the stored measurement, typically `Cube 150` unless the paper explicitly gives another cube size or converted equivalent
- in the same Chinese GB/T 50010-type context, treat `fck` and `fc` as prism/axial-system values, not cylinder strengths
- in Eurocode / EN 206 context, read `Cx/y` as `x = cylinder`, `y = cube`; treat `Cx/y` as code-context evidence and do not collapse it to a single-basis guess
- in Eurocode / EN 206 context, treat `fck` as the characteristic cylinder compressive strength; when a European paper writes `fck` without a `Cx/y` grade, use `fc_basis = cylinder`
- in United States ACI / ASTM C39 context, treat `f'c` as cylinder-based specified compressive strength
- in Japanese `Fc` / JIS A 1108 / JIS A 1132 context, treat `Fc` as cylinder-based unless the paper explicitly defines another basis
- treat a bare single-value `C60` outside explicit Chinese cube context as ambiguous; inspect the cited code and the material/property section before choosing `cube` or `cylinder`
- the same symbol means different things across codes: China `fck` (axial/prism, e.g., C60 → 38.5 MPa) is NOT Eurocode `fck` (cylinder, e.g., C60/75 → 60 MPa); China `fc` (axial design value) is NOT US `f'c` (specified cylinder strength); Japan `Fc` (JIS cylinder-based design standard strength) is NOT interchangeable with Chinese `fc` or US `f'c`; always check which code governs the specimen before interpreting these symbols
- when both cube and cylinder values are reported, prefer the value the authors explicitly use in the specimen-property table, material parameters, constitutive model, or design/check calculations
- if a nearby `Cxx` grade signal and a nearby `fck` / `fc` symbol point to different bases, and no explicit cube / cylinder / prism test description resolves the conflict, use the Chinese GB/T cube-grade plus measured-value exception above when it applies; otherwise set `fc_basis = unknown`
- if the paper still does not identify the basis defensibly, set `fc_basis = unknown` and keep `fcy150 = null`
- when the basis is inferred from code/notation context rather than an explicit specimen description, mark `quality_flags` with `context_inferred_fc_basis`

## 9. Numeric Rules

- every conversion or derivation must use `scripts/safe_calc.py`
- store published JSON numbers in canonical `MPa / mm / kN / %` units
- round to `0.001`
- keep the `fcy150` key present; it may stay `null` when project-level strength normalization is deferred
- `boundary_condition` may be `unknown` or `null` when the paper does not define it defensibly
- `L` means project geometric specimen length, not effective length
- keep eccentricity signs as source evidence shows them
- do not use the sign pattern of `e1` and `e2` alone to exclude a specimen from the ordinary dataset
- recycled concrete rows must preserve `R%` in `r_ratio`
- when the paper does not define `L`, use steel-tube net height only when the figure evidence makes that geometry explicit, and record the derivation
- never infer `L` from boundary-condition assumptions or effective-length formulas

Use the parent-provided sandbox wrapper when calling `safe_calc.py`. Command pattern:

```bash
python .codex/skills/cfst-paper-extractor/scripts/worker_sandbox.py \
  --worktree-path <worktree_path> \
  --paper-dir-relpath <paper_dir_relpath> \
  --output-dir <output_dir> \
  --host-output-dir <output_host_path> \
  --cwd-mode workspace \
  -- \
  python3 .codex/skills/cfst-paper-extractor/scripts/safe_calc.py "D / 2" \
    --var D=164 \
    --round 3
```

Use the same wrapper shape for other derived values and unit conversions; do not infer `safe_calc.py` parameters from ad hoc script reading unless a concrete runtime blocker forces that inspection.

## 10. Evidence Rules

Every specimen row must preserve:

- concise `source_evidence`
- structured `evidence.page`
- `evidence.table_id`
- `evidence.figure_id`
- `evidence.table_image`
- `evidence.setup_image`
- `evidence.value_origin`

When page localization is defensibly recoverable, include it in both `evidence.page` and `source_evidence` using explicit wording such as `Page 4`.
Use the top-level parser `.json` as the normal fallback source for page recovery when markdown or image context does not surface page numbers clearly.
If page localization still cannot be recovered from the processed artifacts, set `evidence.page = null` and keep the best available table/figure/text locator in `source_evidence` rather than inventing a page number.

When a stored value is converted to canonical units, keep the original raw unit/value trace in `evidence.value_origin` and preserve `quality_flags` such as `unit_converted`.

When a value is derived, the field-level evidence must record:

- formula
- raw text
- raw unit if any
- source location

For `fc_basis` decisions:

- cite the exact `Materials` / `Specimens` / `Concrete properties` paragraph, table header, or table footnote when available
- if you rely on code/notation context such as GB/T 50010 `C60`, Eurocode `C60/75`, ACI `f'c`, or Japanese `Fc`, name that context explicitly in `source_evidence`
- do not leave a context-inferred `fc_basis` unexplained in `source_evidence`

## 11. Validation Expectations

Validation outcomes fall into two classes:

- schema/data/evidence failures: repair once, overwrite the same temp JSON, and rerun validation once
- path/mount/sandbox failures such as missing JSON at the declared path: report the failure to the parent and stop; do not move the JSON or invent a second output path

Warnings alone are not validator failure. If the validator exits zero with warnings only, the worker may return success unless a warning reflects a clearly recoverable omission that it is already correcting during an error-driven repair pass.

Validation must reject:

- missing or blank `specimen_label`
- invalid `fc_basis`
- impossible dimensions or strengths
- `is_valid=false` with non-empty specimen groups
- axial rows with nonzero eccentricity
- eccentric rows with both eccentricities zero
- non-null `fcy150` values that are non-numeric or non-positive
- `is_ordinary=true` with shapes outside circular / square / rectangular / round-ended
- `is_ordinary=true` with non-carbon steel
- `is_ordinary=true` with concrete types outside normal / high-strength / recycled
- `is_ordinary=true` with `loading_pattern != monotonic`
- `is_ordinary=false` with empty `ordinary_exclusion_reasons`
- `is_ordinary_cfst=true` but no specimen has `is_ordinary=true`
- `is_ordinary_cfst=false` but some specimen has `is_ordinary=true`
- `ordinary_filter.ordinary_count` mismatch with actual count of `is_ordinary=true` specimens
- per-specimen `loading_pattern` not in allowed specimen-level values
- duplicate specimen labels

## 12. Final Output Goal

The single-paper JSON should be:

- traceable
- physically plausible
- ordinary-filter aware
- canonical for downstream project-specific processing
