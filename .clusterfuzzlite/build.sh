#!/bin/bash -eu

python3 -m pip install \
  --no-cache-dir \
  --require-hashes \
  --requirement "$SRC/preflightops/.clusterfuzzlite/requirements.lock"

# Import the checked-out project directly. The only packages downloaded during
# the build are the hash-pinned runtime dependencies above.
export PYTHONPATH="$SRC/preflightops${PYTHONPATH:+:$PYTHONPATH}"

for fuzzer in "$SRC"/preflightops/fuzz/*_fuzzer.py; do
  fuzzer_basename=$(basename -s .py "$fuzzer")
  fuzzer_package="${fuzzer_basename}.pkg"

  pyinstaller --distpath "$OUT" --onefile --name "$fuzzer_package" "$fuzzer"

  cat > "$OUT/$fuzzer_basename" <<EOF
#!/bin/sh
# LLVMFuzzerTestOneInput marker used by ClusterFuzzLite target discovery.
this_dir=\$(dirname "\$0")
exec "\$this_dir/$fuzzer_package" "\$@"
EOF
  chmod +x "$OUT/$fuzzer_basename"
done
