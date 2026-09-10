#解析に必要なファイルのみ圧縮
#!/bin/bash
cd ~/initialTrial_92/initialTrial

#rm -rf export_analysis
mkdir -p export_analysis

for d in case_*; do
    [ -d "$d" ] || continue

    mkdir -p "export_analysis/$d"

    # パラメータ
    [ -f "$d/params.dat" ] && cp "$d/params.dat" "export_analysis/$d/"

    # CFD最終場 10000
    if [ -d "$d/10000" ]; then
        mkdir -p "export_analysis/$d/10000"
        for f in U p k omega nut phi; do
            [ -f "$d/10000/$f" ] && cp "$d/10000/$f" "export_analysis/$d/10000/"
        done
    fi

    # 粒子追跡の集約CSV
    if [ -f "$d/baseparticle/particle_fates_all.csv" ]; then
        mkdir -p "export_analysis/$d/baseparticle"
        cp "$d/baseparticle/particle_fates_all.csv" "export_analysis/$d/baseparticle/"
    fi

    # 基板沈着データ
    #if [ -f "$d/baseparticle/postProcessing/lagrangian/kinematicCloud/wallSubstrateParticles/1/wallSubstrate.dat" ]; then
    #    mkdir -p "export_analysis/$d/baseparticle/postProcessing/lagrangian/kinematicCloud/wallSubstrateParticles/1"
    #    cp "$d/baseparticle/postProcessing/lagrangian/kinematicCloud/wallSubstrateParticles/1/wallSubstrate.dat" \
    #       "export_analysis/$d/baseparticle/postProcessing/lagrangian/kinematicCloud/wallSubstrateParticles/1/"
    #fi

    # スコアファイルがあればコピー
    #[ -f "$d/wallSubstrate.csv" ] && cp "$d/wallSubstrate.csv" "export_analysis/$d/"
    #[ -f "$d/deposition_scores.csv" ] && cp "$d/deposition_scores.csv" "export_analysis/$d/"

    # 空なら削除
    if [ -z "$(find "export_analysis/$d" -type f)" ]; then
        rm -rf "export_analysis/$d"
        echo "skipped export: $d (no analysis files)"

    else
        echo "completed export: $d"
    fi
done

#exportファイル圧縮
tar -czf export_analysis_initialTrial_92.tar.gz export_analysis
echo "archive completed: export_analysis_initialTrial_92.tar.gz"
#サイズ確認
ls -lh export_analysis_initialTrial_92.tar.gz