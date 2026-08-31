#!/usr/bin/env bash
#
# Reproduces the sherpa-speaker-embedding WASM build from scratch.
#
# This directory (frontend/native/sherpa-speaker-embedding/) holds only the
# NEW files we add on top of an upstream sherpa-onnx checkout (a CMakeLists
# for a new "wasm/speaker-embedding" target + its .cc wrapper) — it is not
# a standalone CMake project. This script clones the pinned sherpa-onnx
# commit into a scratch dir, drops these files into its wasm/ tree, patches
# the two lines needed to wire in the new target, fetches the model, and
# builds, mirroring exactly how sherpa-onnx's own wasm/speaker-diarization
# example is built (same build-wasm.sh pattern, same onnxruntime-wasm
# linkage), just with a smaller exported function surface.
#
# Usage:
#   ./build-wasm.sh [scratch-dir]
#
# Output (on success):
#   <scratch-dir>/sherpa-onnx/build-wasm-simd-speaker-embedding/install/bin/wasm/speaker-embedding/
#     sherpa-onnx-wasm-main-speaker-embedding.js
#     sherpa-onnx-wasm-main-speaker-embedding.wasm
#     sherpa-onnx-wasm-main-speaker-embedding.data   (bundled embedding.onnx)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRATCH="${1:-$HERE/.build-scratch}"
SHERPA_ONNX_COMMIT="91e090ff86f0773556059cb55183837d5687450b"  # tag v1.10.30
EMSCRIPTEN_VERSION="3.1.53"
MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx"

mkdir -p "$SCRATCH"

# --- 1. emsdk -----------------------------------------------------------
if [ ! -d "$SCRATCH/emsdk" ]; then
  git clone https://github.com/emscripten-core/emsdk.git "$SCRATCH/emsdk"
fi
pushd "$SCRATCH/emsdk" >/dev/null
./emsdk install "$EMSCRIPTEN_VERSION"
./emsdk activate "$EMSCRIPTEN_VERSION"
popd >/dev/null

export EMSDK="$SCRATCH/emsdk"
export EM_CONFIG="$SCRATCH/emsdk/.emscripten"
export PATH="$SCRATCH/emsdk:$SCRATCH/emsdk/upstream/emscripten:$PATH"

if ! command -v cmake &>/dev/null; then
  echo "cmake not found. Install it first (e.g. 'brew install cmake')." >&2
  exit 1
fi

# --- 2. sherpa-onnx source, pinned commit --------------------------------
if [ ! -d "$SCRATCH/sherpa-onnx" ]; then
  git clone https://github.com/k2-fsa/sherpa-onnx.git "$SCRATCH/sherpa-onnx"
fi
pushd "$SCRATCH/sherpa-onnx" >/dev/null
git fetch --depth 1 origin "$SHERPA_ONNX_COMMIT" || true
git checkout "$SHERPA_ONNX_COMMIT"
popd >/dev/null

# --- 3. drop in our new wasm target + wire it into the build -----------
TARGET_DIR="$SCRATCH/sherpa-onnx/wasm/speaker-embedding"
mkdir -p "$TARGET_DIR/assets"
cp "$HERE/CMakeLists.txt" "$TARGET_DIR/CMakeLists.txt"
cp "$HERE/sherpa-onnx-wasm-main-speaker-embedding.cc" "$TARGET_DIR/sherpa-onnx-wasm-main-speaker-embedding.cc"

WASM_CMAKE="$SCRATCH/sherpa-onnx/wasm/CMakeLists.txt"
if ! grep -q SHERPA_ONNX_ENABLE_WASM_SPEAKER_EMBEDDING "$WASM_CMAKE"; then
  cat >> "$WASM_CMAKE" <<'EOF'

if(SHERPA_ONNX_ENABLE_WASM_SPEAKER_EMBEDDING)
  add_subdirectory(speaker-embedding)
endif()
EOF
fi

ROOT_CMAKE="$SCRATCH/sherpa-onnx/CMakeLists.txt"
if ! grep -q SHERPA_ONNX_ENABLE_WASM_SPEAKER_EMBEDDING "$ROOT_CMAKE"; then
  python3 - "$ROOT_CMAKE" <<'PYEOF'
import sys
path = sys.argv[1]
text = open(path).read()
anchor = 'option(SHERPA_ONNX_ENABLE_WASM_SPEAKER_DIARIZATION "Whether to enable WASM for speaker diarization" OFF)'
addition = anchor + '\noption(SHERPA_ONNX_ENABLE_WASM_SPEAKER_EMBEDDING "Whether to enable WASM for speaker embedding extraction" OFF)'
assert anchor in text, "anchor 1 not found -- sherpa-onnx CMakeLists.txt layout changed"
text = text.replace(anchor, addition, 1)

anchor2 = "if(SHERPA_ONNX_ENABLE_WASM_TTS)\n  if(NOT SHERPA_ONNX_ENABLE_TTS)"
addition2 = (
    "if(SHERPA_ONNX_ENABLE_WASM_SPEAKER_EMBEDDING)\n"
    "  if(NOT SHERPA_ONNX_ENABLE_WASM)\n"
    '    message(FATAL_ERROR "Please set SHERPA_ONNX_ENABLE_WASM to ON if you enable WASM for speaker embedding")\n'
    "  endif()\n"
    "endif()\n\n"
    + anchor2
)
assert anchor2 in text, "anchor 2 not found -- sherpa-onnx CMakeLists.txt layout changed"
text = text.replace(anchor2, addition2, 1)
open(path, "w").write(text)
PYEOF
fi

# --- 4. model -------------------------------------------------------------
if [ ! -f "$TARGET_DIR/assets/embedding.onnx" ]; then
  curl -SL -o "$TARGET_DIR/assets/embedding.onnx" "$MODEL_URL"
fi

# --- 5. build ---------------------------------------------------------
BUILD_DIR="$SCRATCH/sherpa-onnx/build-wasm-simd-speaker-embedding"
mkdir -p "$BUILD_DIR"
pushd "$BUILD_DIR" >/dev/null

export SHERPA_ONNX_IS_USING_BUILD_WASM_SH=ON

cmake \
  -DCMAKE_INSTALL_PREFIX=./install \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="$EMSDK/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DSHERPA_ONNX_ENABLE_PYTHON=OFF \
  -DSHERPA_ONNX_ENABLE_TESTS=OFF \
  -DSHERPA_ONNX_ENABLE_CHECK=OFF \
  -DBUILD_SHARED_LIBS=OFF \
  -DSHERPA_ONNX_ENABLE_PORTAUDIO=OFF \
  -DSHERPA_ONNX_ENABLE_JNI=OFF \
  -DSHERPA_ONNX_ENABLE_C_API=ON \
  -DSHERPA_ONNX_ENABLE_WEBSOCKET=OFF \
  -DSHERPA_ONNX_ENABLE_GPU=OFF \
  -DSHERPA_ONNX_ENABLE_WASM=ON \
  -DSHERPA_ONNX_ENABLE_WASM_SPEAKER_EMBEDDING=ON \
  -DSHERPA_ONNX_ENABLE_BINARY=OFF \
  -DSHERPA_ONNX_LINK_LIBSTDCPP_STATICALLY=OFF \
  ..

make -j4
make install

popd >/dev/null

echo ""
echo "Build artifacts:"
ls -lh "$BUILD_DIR/install/bin/wasm/speaker-embedding/"
echo ""
echo "Verify with:"
echo "  node $HERE/test-embedding.js $BUILD_DIR/install/bin/wasm/speaker-embedding/sherpa-onnx-wasm-main-speaker-embedding.js embedding.onnx $HERE/test-audio"
