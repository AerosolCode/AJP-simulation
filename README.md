# AJP-simulation — 手動BO版

`main` は、候補生成・CFD投入・粒子計算投入・結果回収・次候補生成を、利用者が一段ずつ実行する版です。AJPノズルをstructuredメッシュ、OpenFOAMの定常流れ場、有限半径粒子の壁面さえぎりで評価します。

計算手法、これまでの変更、検証状況は [日本語ガイド（PDF）](reports/ajp_project_status_ja.pdf) にまとめています。編集用正本は [TeX](reports/ajp_project_status_ja.tex) です。

## 手動版と自動版を使い分ける

| ブランチ | 運用 |
| --- | --- |
| `main` | 手動で各段階を実行する。本READMEの対象 |
| `feature/structured-finite-radius-mobo-v2` | 常駐dispatcherによる複数ホストへの自動投入・回収・BO反復 |

両方を運用する場合は、別ディレクトリへcloneします。実行中のディレクトリでブランチを切り替えると、ジョブが読むスクリプトも切り替わるためです。

```bash
git clone --branch main \
  git@github.com:AerosolCode/AJP-simulation.git AJP-manual
git clone --branch feature/structured-finite-radius-mobo-v2 \
  git@github.com:AerosolCode/AJP-simulation.git AJP-auto
```

手動版の既定出力先は `campaigns/manual_structured_finite_radius/` です。自動版のcampaignと観測CSVを共有しないでください。自動版の設定・運用手順・旧資料は自動版ブランチに残しています。

## 学生・実行環境ごとの初回設定

学生本人のSSHユーザーで計算用クラスタへログインし、その環境のclone内で操作します。手動版にはホスト間SSHの自動制御はありません。利用者固有の設定は [site.env.example](site.env.example) をコピーして編集します。自動版とは設定項目が異なるため、手動版の雛形から作ってください。

```bash
cd AJP-manual
cp site.env.example site.env
${EDITOR:-vi} site.env
source ./site.env
"$AJP_PYTHON_BIN" tools/check_site_config.py
```

| 設定 | 指定するもの |
| --- | --- |
| `AJP_PYTHON_BIN` | NumPy・Gmshを使えるPython。計算ノードでも利用できる絶対パスを推奨 |
| `AJP_OPENFOAM_BASHRC` | 使用するOpenFOAMの `etc/bashrc` |
| `AJP_PARTICLE_SOLVER` | 粒子solverの実行ファイル。空ならOpenFOAM環境のPATHから探索 |
| `AJP_SLURM_NODELIST` | 投入先node。空ならSlurmに選択を任せる |
| `AJP_WORKER_ENV` | 通常は空。以前の `worker-env.sh` を読み込まない |

`site.env` はGit管理外です。`bo_loop.py` はこの設定を読み、ジョブへ引き継ぎます。形状範囲・目的関数など、共有する計算条件は [bo_config.json](bo_config.json) で管理します。Slurmで選ばれる全ノードから、clone・Python・OpenFOAM・solverを利用できる構成にしてください。

必要なPythonパッケージとsolverを準備します。OpenFOAMとSlurm自体はクラスタに導入済みであることが前提です。

```bash
"$AJP_PYTHON_BIN" -m pip install numpy gmsh
bash tools/build_solver.sh "$AJP_OPENFOAM_BASHRC" \
  "$PWD/vendor/aerosolDynamicsFoam"
"$AJP_PYTHON_BIN" tools/check_site_config.py --local-tools
```

このbuildは同梱の粒子solverと `finiteRadiusDeposition` ライブラリを作ります。実行時と同じOpenFOAM・利用者環境でbuildしてください。32件以上の有効観測からBOを提案する前に、追加の依存関係も導入します。

```bash
"$AJP_PYTHON_BIN" -m pip install -r requirements-mobo.txt
```

## 一段ずつ実行する

以下はclone直下で実行します。まず初期候補32件を生成し、試すケースを選びます。`init` と `suggest` は候補を作るだけです。

```bash
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json init --initial-batch 32
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json status

# 投入内容を確認してから、選択したケースのCFDを投入
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json \
  submit-cfd --cases case_0000 case_0001 --dry-run
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json \
  submit-cfd --cases case_0000 case_0001
```

Slurmの `squeue -u "$USER"`、`status`、各caseのログで終了を確認します。CFDが成功したケースを選んで、粒子計算へ進めます。残差停止した場合も、そのCFDの最新時刻の流れ場を使います。

```bash
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json \
  submit-particles --cases case_0000 case_0001 --dry-run
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json \
  submit-particles --cases case_0000 case_0001

# 粒子計算の終了後、結果を観測CSVへ反映
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json \
  collect --cases case_0000 case_0001
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json status
```

同じ手順で残りの初期候補を評価します。結果・計算費用を確認して、次の8件を生成します。

```bash
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json suggest --batch-size 8
```

有効観測が32件未満なら空間充填maximin、32件以上なら制約付き多目的BO（qLogNEHVI）を使います。次に投入するケース、再試行、次バッチへ進む時点、計算終了は利用者が判断します。

`status` が `cfd_failed` または `particle_failed` を示したらログを確認します。再試行する場合は、回収前に原因を修正して該当段階の `*_FAILED` 印だけを取り除いてから再投入します。失敗として評価に残す場合は `collect` します。強制終了では失敗印が残らない場合もあるため、Slurmの `sacct` でも確認してください。`squeue` を確認できないときは重複投入を避けるため投入を停止します。

## 残しているファイル

| 場所 | 用途 |
| --- | --- |
| `bo_loop.py`, `mobo.py`, `bo_config.json` | 手動操作、候補提案、評価、計算条件 |
| `base/` | structuredメッシュとCFDケースのテンプレート |
| `baseparticle/` | 粒子追跡・さえぎり・集計のテンプレート |
| `vendor/` | buildに必要な粒子solverのソースとライセンス |
| `tools/` | 利用者設定の確認、solver buildなどの補助 |
| `tests/` | ソースの回帰テスト。大容量の計算結果ではない |
| `reports/` | 本版のTeX/PDFガイド |
| `campaigns/` | 実行時に作るcase・ログ・観測。Git管理外 |

回帰テストは `python3 -m unittest discover -s tests -v` で実行できます。実際のCFD・粒子物理の検証は別途必要です。有限半径モデルは固定壁への直接さえぎりを扱い、堆積層の成長や粒子同士の衝突は扱いません。クラスタ上の並列実行、メッシュ・時間刻み・残差停止の感度を少数ケースで確認してから本計算へ進めてください。

## English

`main` is the manual Bayesian-optimization workflow: explicitly generate candidates, submit selected CFD cases, submit particle tracking after CFD succeeds, collect results, and request another batch. The automated multi-host workflow remains on `feature/structured-finite-radius-mobo-v2`. Use separate clones and campaign directories to operate both. Copy `site.env.example` to the Git-ignored `site.env` and configure your local Python, OpenFOAM, particle solver, and Slurm node selection. See the commands above and the Japanese PDF guide for the operating procedure and validation limits.

Licensed under [GNU GPL v3.0](LICENSE).
