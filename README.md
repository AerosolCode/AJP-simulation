# AJP-simulation — BOの実行手順

初期候補の生成 → CFD → 粒子計算 → 結果回収 → 次候補の生成、の順に実行します。以下のコマンドはすべてclone直下で実行してください。

## 1. 初回の環境設定

自分のSSHユーザーで計算用クラスタへログインし、作業用ディレクトリにcloneします。OpenFOAMとSlurmはクラスタに導入済みであることが前提です。

```bash
git clone --branch main \
  git@github.com:AerosolCode/AJP-simulation.git AJP-manual
cd AJP-manual

# site.envの作成は初回だけ。各パスを自分の環境に合わせて編集
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
| `AJP_WORKER_ENV` | 通常は空のまま |

`site.env` はGit管理外です。ユーザーや環境が変わったら、このファイルをその人の設定で作成してください。Slurmで選ばれる全ノードから、clone・Python・OpenFOAM・solverを利用できる構成にします。

必要なPythonパッケージ、粒子solver、壁面さえぎりライブラリを準備します。buildは計算時と同じOpenFOAM・利用者環境で実行してください。

```bash
"$AJP_PYTHON_BIN" -m pip install numpy gmsh
"$AJP_PYTHON_BIN" -m pip install -r requirements-mobo.txt
bash tools/build_solver.sh "$AJP_OPENFOAM_BASHRC" \
  "$PWD/vendor/aerosolDynamicsFoam"
"$AJP_PYTHON_BIN" tools/check_site_config.py --local-tools
```

新しいターミナルや再ログイン後は、clone直下で設定を読み直します。

```bash
source ./site.env
```

## 2. 初期候補を生成する

形状範囲・目的関数などの計算条件は [bo_config.json](bo_config.json) で確認・編集します。まず初期候補32件を生成します。`init` は新しい計算を始めるときに一度だけ実行します。

```bash
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json init --initial-batch 32
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json status
```

既定の出力先は `campaigns/manual_structured_finite_radius/` です。この中の `bo_candidates.csv` で候補を確認できます。`init` と `suggest` は候補を生成するだけで、計算ジョブは投入しません。

## 3. 選んだケースのCFDを投入する

以下は `case_0000` と `case_0001` を計算する例です。`--cases` の後を実際に計算したいケース名に置き換えてください。まず `--dry-run` で投入内容を確認し、問題なければ投入します。

```bash
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json \
  submit-cfd --cases case_0000 case_0001 --dry-run
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json \
  submit-cfd --cases case_0000 case_0001
```

ジョブの終了を待ち、進捗と各ケースのログでCFDの成功を確認します。

```bash
squeue -u "$USER"
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json status
```

## 4. CFDが成功したケースの粒子計算を投入する

CFDの成功を確認したケースを指定します。残差停止した場合も、CFDの最新時刻の流れ場を使います。

```bash
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json \
  submit-particles --cases case_0000 case_0001 --dry-run
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json \
  submit-particles --cases case_0000 case_0001

squeue -u "$USER"
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json status
```

## 5. 結果を回収する

粒子計算の終了後、結果を観測CSVへ反映します。

```bash
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json \
  collect --cases case_0000 case_0001
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json status
```

結果は出力先の `bo_observations.csv` に保存されます。手順3〜5を繰り返し、残りの初期候補も評価します。

## 6. 次の候補を生成して繰り返す

回収した結果を確認し、次の8件を生成します。

```bash
"$AJP_PYTHON_BIN" bo_loop.py --config bo_config.json suggest --batch-size 8
```

有効観測が32件未満なら空間充填maximin、32件以上なら制約付き多目的BO（qLogNEHVI）で候補を提案します。`bo_candidates.csv` で新しいケース名を確認し、そのケースについて手順3〜5を実行します。以後は手順6→3→4→5を必要な回数だけ繰り返します。`init` をやり直す必要はありません。

## 計算に失敗したとき

`status` が `cfd_failed` または `particle_failed` を示したらログを確認します。再試行する場合は、回収前に原因を修正して該当段階の `*_FAILED` 印だけを取り除いてから再投入します。失敗として評価に残す場合は `collect` します。強制終了では失敗印が残らない場合もあるため、Slurmの `sacct` でも確認してください。`squeue` を確認できないときは重複投入を避けるため投入を停止します。

Licensed under [GNU GPL v3.0](LICENSE).
