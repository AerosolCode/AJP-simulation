#不要な中間時間フォルダを消去

#cd ~/initialTrial_92/initialTrial

for d in case_*; do
    [ -d "$d/10000" ] || continue

    for t in $(find "$d" -maxdepth 1 -type d \
        | sed 's#.*/##' \
        | grep -E '^[0-9]+(\.[0-9]+)?$'); do

        if [ "$t" != "0" ] && [ "$t" != "10000" ]; then
            rm -rf "$d/$t"
        fi
    done

    echo "cleaned $d"
done