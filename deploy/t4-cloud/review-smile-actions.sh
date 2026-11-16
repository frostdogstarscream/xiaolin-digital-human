set -eu
root=/formal/smile-other-actions-20261111
mkdir -p "$root"
for action in goodbye-wave explain-open-palms acknowledge-nod
do
    mkdir -p "$root/$action"
    python /formal/smile-review-20261111/review_smile_speech.py --action "$action" --output "$root/$action" --two-way > "$root/$action/render.log" 2>&1
    python /formal/smile-review-20261111/verify-smile-review.py --output "$root/$action" > "$root/$action/verification.log" 2>&1
done
touch "$root/complete"
