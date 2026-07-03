# AJP-simulation

An OpenFOAM-based CFD and particle-tracking simulation pipeline for evaluating AJP (Aerosol Jet Printing) nozzles. It runs many nozzle geometries/conditions (cases) in parallel on a SLURM cluster to obtain evaluation metrics such as deposition efficiency and overspray.

Currently this pipeline is operated as the **low-fidelity** leg of a multi-fidelity Bayesian optimization framework (a separate high-fidelity pipeline is run in parallel).

## Pipeline overview

1. **Case setup & CFD submission** — [paramSet.py](paramSet.py) / [paramRun.py](paramRun.py)
   For each parameter set in `baseparams.csv`, a `case_XXX` directory is created from [base/](base/) and submitted via `sbatch run.sh`.

2. **CFD** — [base/run.sh](base/run.sh)
   Mesh generation (`meshGen2.py`) → `gmshToFoam` → boundary condition generation (`BC_omega.py`, `BC_U.py`) → `potentialFoam` → `simpleFoam` (steady-state solver).

3. **Monitoring & resubmission of unfinished cases** — [selectrun.sh](selectrun.sh)
   Skips finished/queued cases; resumes interrupted cases from `latestTime` via [base/restartrun.sh](base/restartrun.sh), or resubmits `run.sh` from scratch for cases that haven't started.

4. **Particle-tracking submission** — [particlerunall.sh](particlerunall.sh)
   For cases with completed CFD but no completed particle tracking, copies the latest [baseparticle/](baseparticle/) template and submits [baseparticle/loopparticle.sh](baseparticle/loopparticle.sh).

5. **Particle tracking (chunked execution)** — [baseparticle/loopparticle.sh](baseparticle/loopparticle.sh)
   Runs `icoUncoupledKinematicParcelFoam` in time chunks, tallying particles reaching the outlet/substrate/walls after each chunk, and stops once the target resolved ratio is reached.

6. **Post-processing**
   - [delete.sh](delete.sh): removes unneeded intermediate time directories from finished cases
   - [export.sh](export.sh): extracts and archives only the files needed for analysis (parameters, final CFD field, aggregated particle-tracking CSV)

## Directory structure

- `base/` — CFD case template (mesh generation, boundary conditions, solver settings)
- `baseparticle/` — particle-tracking case template
- `paramSet.py` — script that prepares cases from a parameter set

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

---

# AJP-simulation（日本語版）

AJP（Aerosol Jet Printing）ノズルの評価を目的とした、OpenFOAMベースのCFD・粒子追跡シミュレーションパイプラインです。SLURMクラスタ上で多数のノズル形状・条件（ケース）を並列に実行し、堆積効率やオーバースプレーなどの評価指標を得ることを目指しています。

現状はマルチフィデリティ・ベイズ最適化フレームワークの**低フィデリティ**計算として運用しています（高フィデリティ計算は別途並行して実行）。

## パイプライン概要

1. **ケース準備・CFD投入** — [paramSet.py](paramSet.py) / [paramRun.py](paramRun.py)
   `baseparams.csv` の各パラメータセットごとに `case_XXX` ディレクトリを作成し、[base/](base/) の内容をコピーして `sbatch run.sh` で投入します。

2. **CFD本体** — [base/run.sh](base/run.sh)
   メッシュ生成（`meshGen2.py`）→ `gmshToFoam` → 境界条件生成（`BC_omega.py`, `BC_U.py`）→ `potentialFoam` → `simpleFoam`（定常流計算）を実行します。

3. **未完了ケースの監視・再投入** — [selectrun.sh](selectrun.sh)
   完了・投入済みのケースをスキップしつつ、途中終了したケースは [base/restartrun.sh](base/restartrun.sh) で `latestTime` から再開、未着手のケースは `run.sh` を再投入します。

4. **粒子追跡投入** — [particlerunall.sh](particlerunall.sh)
   CFD完了済み・粒子追跡未完了のケースに対して、最新の [baseparticle/](baseparticle/) をコピーし [baseparticle/loopparticle.sh](baseparticle/loopparticle.sh) を投入します。

5. **粒子追跡本体（チャンク実行）** — [baseparticle/loopparticle.sh](baseparticle/loopparticle.sh)
   `icoUncoupledKinematicParcelFoam` を一定時間刻みで繰り返し実行し、outlet／基板／壁面への粒子到達数から解決率を算出、目標解決率に達した時点で打ち切ります。

6. **後処理**
   - [delete.sh](delete.sh): 完了ケースの不要な中間時刻フォルダを削除
   - [export.sh](export.sh): 解析に必要なファイル（パラメータ、CFD最終場、粒子追跡集約CSV）のみを抽出・圧縮

## ディレクトリ構成

- `base/` — CFDケースのテンプレート（メッシュ生成・境界条件・ソルバー設定）
- `baseparticle/` — 粒子追跡ケースのテンプレート
- `paramSet.py` — パラメータセットからケースを準備するスクリプト

## ライセンス

このプロジェクトは [GNU General Public License v3.0](LICENSE) の下で公開されています。
