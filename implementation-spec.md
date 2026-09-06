# Implementation Specification: Candy-Man

## Overview
Candy-Man is a static analysis engine designed to detect wrapper functions around third-party libraries.

## Pipeline Architecture
- **Step 0: Repo Loading** (`engine/repo_loader.py`) - Clone repository / scan local directory, parse ASTs safely.
- **Step 1: Candidacy Filtering** (`engine/candidacy.py` & `engine/classifier.py`) - Filter functions with $\ge 1$ statically-attributable third-party calls.
- **Step 2: Structural Complexity Scoring** (`engine/structural.py`) - Calculate $R_{\text{structural}}$ using internal vs external weights and housekeeping discounts.
- **Step 3 & 3.5: Transformation Scoring** (`engine/transformation.py`) - Evaluate AST data flow transformations and trace returned variables.
- **Step 4 & 5: Scoring & Ranking** (`engine/scorer.py`) - Apply AND-gate thresholds and rank flagged functions by suspicion.

## Stated Limitations
- Dynamic imports or aliased runtime dispatch cannot be statically resolved.
- Tracing bailed out functions (`transformation_computed: false`) are intentionally unflagged to avoid false positives.
