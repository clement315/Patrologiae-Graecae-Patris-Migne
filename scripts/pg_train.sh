#!/usr/bin/env bash
# =====================================================================
#  PG OCR - recognition training with kraken 7.x        (pg_train.sh v2)
#
#  Usage (inside Ubuntu / WSL):
#    bash /mnt/e/PG_OCR/scripts/pg_train.sh            prepare, train, test
#    bash /mnt/e/PG_OCR/scripts/pg_train.sh --status   progress of all runs
#    bash /mnt/e/PG_OCR/scripts/pg_train.sh --resume   continue after Ctrl+C / crash
#    bash /mnt/e/PG_OCR/scripts/pg_train.sh --new      start an additional run
#    bash /mnt/e/PG_OCR/scripts/pg_train.sh --test     evaluate the best model only
#
#  Optional overrides, e.g.:
#    BATCHES="4 2" PRECISION=32-true bash /mnt/e/PG_OCR/scripts/pg_train.sh
#
#  Improvements over train_rec.sh
#   - progress bar visible again (log is recorded through a pseudo-terminal)
#   - real CUDA out-of-memory -> automatic restart with a smaller batch
#   - refuses to start while another training already holds the GPU
#   - datasets cached on the Linux disk (random reads from /mnt/e are slow)
#   - each run in its own folder with its settings; --status overview
#   - rebuilds data only when the inputs changed
#   - the whole script is read before it runs, so editing it mid-run is safe
# =====================================================================
set -euo pipefail

main() {
    export PATH="$PATH:/usr/lib/wsl/lib"   # nvidia-smi location inside WSL
    ROOT="${PG_ROOT:-/mnt/e/PG_OCR}"
    GT="$ROOT/work/gt"
    RUNS="$ROOT/models/rec"
    CACHE="$HOME/pg_cache"
    BATCHES="${BATCHES:-8 4 2}"            # tried in this order on out-of-memory
    # bf16-mixed made the long-sequence LSTM stall at ~23% and diverge to NaN
    # (run_20261025_224654) -> full precision is the default now
    PRECISION="${PRECISION:-32-true}"
    WARMUP="${WARMUP:-1000}"               # steps of learning-rate warm-up
    CLIP="${CLIP:-1.0}"                    # gradient clipping (norm) against blow-ups
    LRATE="${LRATE:-}"                     # empty = kraken default (1e-3)
    PLATEAU_EPOCHS="${PLATEAU_EPOCHS:-6}"  # watchdog: by this epoch ...
    PLATEAU_MIN="${PLATEAU_MIN:-0.5}"      # ... best val accuracy must exceed this
    WORKERS="${WORKERS:-4}"
    MIN_EPOCHS="${MIN_EPOCHS:-20}"
    LAG="${LAG:-10}"                       # stop after LAG epochs without improvement
    START_TS=$(date +%s)
    MODE="${1:-}"
    # Windows notification when training/testing ends (NOTIFY=0 to switch off)
    [ "$MODE" = "--status" ] || trap 'notify_end $?' EXIT

    case "${1:-}" in
        --status) show_status; return ;;
        --test)   activate; run_test "$(latest_run)"; return ;;
        --resume) activate; preflight; prepare_data; resume_training; return ;;
        --new|"") activate; preflight; prepare_data; new_training "${1:-}"; return ;;
        *) die "unknown option '$1' (use --status, --resume, --new or --test)" ;;
    esac
}

# --------------------------------------------------------------------- notification
notify_end() {
    set +e                               # the notification itself must never fail
    local rc="$1" mins run acc msg
    [ "${NOTIFY:-1}" = "0" ] && return 0
    mins=$(( ( $(date +%s) - ${START_TS:-$(date +%s)} ) / 60 ))
    [ "$mins" -lt 1 ] && [ "$rc" -ne 0 ] && return 0      # instant usage errors: no popup
    run="$(latest_run)"
    acc=""
    if [ -n "$run" ] && [ -f "$run/test_report.txt" ]; then
        acc="$(grep -m1 'Character Accuracy' "$run/test_report.txt" | awk '{print $1}' || true)"
    fi
    if [ "$rc" -eq 0 ]; then
        msg="Finished after ${mins} min."
        [ -n "$acc" ] && msg="$msg Test character accuracy: $acc"
        bash "$ROOT/scripts/notify.sh" "PG training finished" "$msg"
    elif [ "$rc" -eq 130 ]; then
        bash "$ROOT/scripts/notify.sh" "PG training paused" "Stopped by Ctrl+C after ${mins} min. Continue with --resume."
    else
        bash "$ROOT/scripts/notify.sh" "PG training stopped" "Ended with an error (exit $rc) after ${mins} min - check --status and the log."
    fi
}

# --------------------------------------------------------------------- helpers
step() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$*"; }
note() { printf '\033[0;33m%s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

activate() {
    [ -f "$HOME/kraken-env/bin/activate" ] || die "kraken environment not found - run setup_kraken.sh first"
    # shellcheck disable=SC1091
    source "$HOME/kraken-env/bin/activate"
    export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
}

latest_run()  { ls -1d "$RUNS"/run_* 2>/dev/null | grep -vE '_oom_|_failed' | sort | tail -n1 || true; }
best_model()  { ls -1t "$1"/best_*.safetensors 2>/dev/null | head -n1 || true; }
newest_ckpt() { ls -1t "$1"/*.ckpt 2>/dev/null | head -n1 || true; }
running_jobs() { pgrep -af 'kraken-env/bin/ketos .*(train|test)( |$)' || true; }

gpu_line() {
    command -v nvidia-smi >/dev/null 2>&1 || { echo "nvidia-smi not found"; return; }
    nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu \
               --format=csv,noheader,nounits 2>/dev/null \
      | awk -F', *' '{printf "GPU memory %s / %s MiB, utilisation %s%%\n", $1, $2, $3}'
}

# run a command through a pseudo-terminal so the progress bar is shown,
# while everything is also written to a log file
run_logged() {
    local log="$1"; shift
    local cmd; cmd="$(printf '%q ' "$@")"
    script -q -e -f -c "$cmd" "$log"
}

# --------------------------------------------------------------------- checks
preflight() {
    step "Checks"
    local jobs; jobs="$(running_jobs)"
    if [ -n "$jobs" ]; then
        echo "$jobs" | head -n 3
        die "a kraken training/test is already running (see above). Let it finish, or stop it with Ctrl+C in its window first."
    fi
    gpu_line
    local used
    used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -n1 || echo 0)"
    if [ "${used:-0}" -gt 1200 ] 2>/dev/null; then
        note "Note: ${used} MiB of GPU memory are already in use by other programs."
        note "      Closing QQ, ChatGPT, browsers with video etc. leaves more memory for training."
    fi
    local free_gb; free_gb="$(df -BG --output=avail "$ROOT" | tail -n1 | tr -dc '0-9')"
    [ "${free_gb:-0}" -ge 5 ] || die "less than 5 GB free on the drive of $ROOT"
    echo "Free space on project drive: ${free_gb} GB"
}

# --------------------------------------------------------------------- data
prepare_data() {
    step "Ground truth (cleaning, split, binary datasets)"
    local prep="$ROOT/scripts/prepare_gt.py"
    if [ ! -f "$GT/summary.json" ] || [ "$prep" -nt "$GT/summary.json" ]; then
        python "$prep" --root "$ROOT"
    else
        echo "cleaned ground truth up to date"
    fi
    for split in train val test; do
        if [ ! -f "$GT/$split.arrow" ] || [ "$GT/$split.lst" -nt "$GT/$split.arrow" ]; then
            ketos --workers "$WORKERS" compile -f page -o "$GT/$split.arrow" -F "$GT/$split.lst"
        else
            echo "dataset up to date: $split.arrow"
        fi
    done
    mkdir -p "$CACHE"
    cp -u "$GT"/train.arrow "$GT"/val.arrow "$GT"/test.arrow "$CACHE"/
    echo "$CACHE/val.arrow" > "$CACHE/val.lst"
    echo "datasets cached in $CACHE"
}

# --------------------------------------------------------------------- training
new_training() {
    local mode="$1" last best
    last="$(latest_run)"
    if [ "$mode" != "--new" ] && [ -n "$last" ]; then
        best="$(best_model "$last")"
        if [ -n "$best" ]; then
            note "Latest run is already finished: $best"
            note "Use --new for another run or --test to evaluate it again."
            run_test "$last"; return
        fi
        if [ -n "$(newest_ckpt "$last")" ]; then
            note "Latest run $(basename "$last") is unfinished - continuing it (use --new to start over)."
            resume_training; return
        fi
    fi

    local batch rundir log rc why lr="$LRATE" retried_lr=0 lr_args
    for batch in $BATCHES; do
        while :; do
            rundir="$RUNS/run_$(date +%Y%m%d_%H%M%S)"
            mkdir -p "$rundir"
            log="$rundir/train.log"
            cat > "$rundir/run.conf" <<EOF
started=$(date '+%F %T')
batch=$batch
precision=$PRECISION
lrate=${lr:-default (1e-3)}
warmup=$WARMUP
clip=$CLIP
workers=$WORKERS
min_epochs=$MIN_EPOCHS
lag=$LAG
train_lines=$(python -c "import json;print(json.load(open('$GT/summary.json'))['split_lines']['train'])")
EOF
            lr_args=(); [ -n "$lr" ] && lr_args=(-r "$lr")
            step "Training  (run $(basename "$rundir"), batch $batch, precision $PRECISION, lr ${lr:-1e-3})"
            note "A single line 'memory allocation failed with OOM' at the start is harmless (PyTorch retries)."
            note "Watchdog on: a run that turns NaN or does not learn is stopped automatically."
            note "Stop any time with Ctrl+C; continue later with:  bash $0 --resume"
            rc=0
            watchdog "$log" "$rundir" & local wd=$!
            run_logged "$log" ketos -d cuda:0 --precision "$PRECISION" --workers "$WORKERS" -s 42 train \
                -f binary -B "$batch" --augment "${lr_args[@]}" \
                --warmup "$WARMUP" --gradient-clip-val "$CLIP" \
                --min-epochs "$MIN_EPOCHS" --lag "$LAG" \
                -o "$rundir" -e "$CACHE/val.lst" "$CACHE/train.arrow" || rc=$?
            kill "$wd" 2>/dev/null || true; wait "$wd" 2>/dev/null || true

            if [ -n "$(best_model "$rundir")" ]; then
                echo "finished=$(date '+%F %T')" >> "$rundir/run.conf"
                run_test "$rundir"; return
            fi
            if [ -f "$rundir/STOPPED_BY_WATCHDOG" ]; then
                why="$(cat "$rundir/STOPPED_BY_WATCHDOG")"
                mv "$rundir" "${rundir}_failed"
                if [ "$retried_lr" -eq 0 ]; then
                    retried_lr=1; lr="${RETRY_LRATE:-0.0003}"
                    note "Watchdog stopped the run ($why). Retrying once with a lower learning rate ($lr)."
                    continue
                fi
                die "run failed again ($why) even with learning rate $lr - send me the log: ${rundir}_failed/train.log"
            fi
            if grep -qE 'OutOfMemoryError|CUDA out of memory' "$log"; then
                note "Real out-of-memory with batch $batch - retrying with the next smaller batch."
                mv "$rundir" "${rundir}_oom_b${batch}"
                continue 2
            fi
            if grep -q 'KeyboardInterrupt' "$log"; then
                note "Stopped by you. Continue later with:  bash $0 --resume"
                exit 130
            fi
            tail -n 25 "$log" | sed 's/\x1b\[[0-9;?]*[A-Za-z]//g'
            die "training ended without a model (exit code $rc). Log: $log"
        done
    done
    die "out of memory even with the smallest batch ($BATCHES). Close other GPU programs."
}

# Background guard for a running training:
#  - loss NaN (run has diverged, never recovers)        -> stop at once
#  - after PLATEAU_EPOCHS epochs best val accuracy < PLATEAU_MIN -> stop
# It writes the reason to STOPPED_BY_WATCHDOG and sends Ctrl+C (SIGINT) to kraken,
# which then saves checkpoint_abort.ckpt and exits cleanly.
watchdog() {
    set +e
    local log="$1" rundir="$2" n pid ep best reason
    sleep "${WD_START:-90}"
    while pgrep -f 'kraken-env/bin/ketos .* train' >/dev/null 2>&1; do
        reason=""
        n="$(tail -c 400000 "$log" 2>/dev/null | grep -o 'train_loss_step: nan' | wc -l || true)"
        [ "${n:-0}" -ge 50 ] && reason="loss became NaN"
        if [ -z "$reason" ]; then
            read -r ep best < <(ls -1 "$rundir"/checkpoint_[0-9]*.ckpt 2>/dev/null \
                | sed 's#.*/checkpoint_##; s#\.ckpt$##' \
                | awk -F- '{e=$1+0; if(e>me)me=e; if($2>mb)mb=$2} END{print me+0, mb+0}')
            if [ "${ep:-0}" -ge "$PLATEAU_EPOCHS" ] && \
               awk -v b="${best:-0}" -v m="$PLATEAU_MIN" 'BEGIN{exit !(b<m)}'; then
                reason="best val accuracy only ${best} after ${ep} epochs (no learning)"
            fi
        fi
        if [ -n "$reason" ]; then
            echo "$reason" > "$rundir/STOPPED_BY_WATCHDOG"
            pid="$(pgrep -of 'kraken-env/bin/ketos .* train' || true)"
            [ -n "$pid" ] && kill -INT "$pid" 2>/dev/null
            return
        fi
        sleep "${WD_INTERVAL:-60}"
    done
}

resume_training() {
    local rundir ckpt log rc=0
    rundir="$(latest_run)"
    [ -n "$rundir" ] || die "no run to resume - start one without --resume"
    [ -z "$(best_model "$rundir")" ] || { note "run already finished"; run_test "$rundir"; return; }
    ckpt="$(newest_ckpt "$rundir")"
    [ -n "$ckpt" ] || die "no checkpoint in $rundir yet - start a new run with --new"
    log="$rundir/train_resume_$(date +%H%M%S).log"
    step "Resuming $(basename "$rundir") from $(basename "$ckpt")"
    note "(batch size and data settings are taken from the checkpoint)"
    watchdog "$log" "$rundir" & local wd=$!
    run_logged "$log" ketos -d cuda:0 --precision "$PRECISION" --workers "$WORKERS" train \
        --resume "$ckpt" || rc=$?
    kill "$wd" 2>/dev/null || true; wait "$wd" 2>/dev/null || true
    if [ -f "$rundir/STOPPED_BY_WATCHDOG" ]; then
        die "watchdog stopped the resumed run ($(cat "$rundir/STOPPED_BY_WATCHDOG")). Start fresh with --new."
    fi
    if [ -n "$(best_model "$rundir")" ]; then
        echo "finished=$(date '+%F %T')" >> "$rundir/run.conf"
        run_test "$rundir"
    else
        die "resume ended without a model (exit code $rc). Log: $log"
    fi
}

# --------------------------------------------------------------------- evaluation
run_test() {
    local rundir="$1" best
    [ -n "$rundir" ] || die "no training run found"
    best="$(best_model "$rundir")"
    [ -n "$best" ] || die "no finished model in $rundir"
    step "Evaluation on the 30 held-out test pages"
    echo "model: $best"
    [ -f "$CACHE/test.arrow" ] || cp "$GT/test.arrow" "$CACHE/"
    ketos -d cuda:0 test -B 8 -f binary -m "$best" "$CACHE/test.arrow" 2>&1 \
        | tee "$rundir/test_report.txt"
    printf '\n\033[1;32mDONE.\033[0m  Report: %s\n' "$rundir/test_report.txt"
    printf '\a'
}

# --------------------------------------------------------------------- status
show_status() {
    step "Status"
    local jobs; jobs="$(running_jobs)"
    if [ -n "$jobs" ]; then echo "training/test process running: yes"; else echo "training/test process running: no"; fi
    gpu_line
    local d any=0
    for d in "$RUNS"/run_* "$ROOT"/models/rec_v1; do
        [ -d "$d" ] || continue
        any=1
        printf '\n\033[1m%s\033[0m\n' "$(basename "$d")"
        if [ -f "$d/run.conf" ]; then
            grep -E '^(started|batch|precision|lrate|warmup|clip|finished)=' "$d/run.conf" | sed 's/^/  /' || true
        fi
        local c
        for c in "$d"/checkpoint_[0-9]*.ckpt; do
            [ -f "$c" ] || continue
            basename "$c" .ckpt | awk -F'[_-]' '{acc=$3; printf "  epoch %2d  val accuracy %.2f%%  (CER %.2f%%)\n", $2, acc*100, (1-acc)*100}'
        done | sort -k2,2n | tail -n 12
        [ -n "$(best_model "$d")" ] && echo "  best model: $(basename "$(best_model "$d")")"
        local lg; lg="$(ls -1t "$d"/train*.log 2>/dev/null | head -n1 || true)"
        if [ -n "$lg" ] && tail -c 200000 "$lg" | grep -q 'train_loss_step: nan'; then
            printf '  \033[1;31mWARNING: loss is NaN - this run has diverged, stop it (Ctrl+C) and start --new\033[0m\n'
        fi
        [ -f "$d/STOPPED_BY_WATCHDOG" ] && echo "  stopped by watchdog: $(cat "$d/STOPPED_BY_WATCHDOG")"
        if [ -f "$d/test_report.txt" ]; then
            echo "  test report:"; grep -iE 'accuracy|error' "$d/test_report.txt" | head -n 4 | sed 's/^/    /'
        fi
    done
    [ "$any" -eq 1 ] || echo "no runs yet"
}

main "$@"; exit $?
