// wasm/speaker-embedding/sherpa-onnx-wasm-main-speaker-embedding.cc
//
// Minimal WASM wrapper exposing only the speaker-embedding-extractor slice
// of sherpa-onnx's C API, modeled on
// wasm/speaker-diarization/sherpa-onnx-wasm-main-speaker-diarization.cc.
//
// Feasibility spike for Framewrite's real-time diarization feature.
#include <stdio.h>

#include <algorithm>

#include "sherpa-onnx/c-api/c-api.h"

// see also
// https://emscripten.org/docs/porting/connecting_cpp_and_javascript/Interacting-with-code.html

extern "C" {

static_assert(sizeof(SherpaOnnxSpeakerEmbeddingExtractorConfig) == 4 * 4, "");

void MyPrint(const SherpaOnnxSpeakerEmbeddingExtractorConfig *config) {
  fprintf(stdout, "----------speaker embedding extractor config----------\n");
  fprintf(stdout, "model: %s\n", config->model);
  fprintf(stdout, "num threads: %d\n", config->num_threads);
  fprintf(stdout, "debug: %d\n", config->debug);
  fprintf(stdout, "provider: %s\n", config->provider);
}

// Helper used by the JS glue to copy bytes out of the WASM heap (same
// pattern as the official speaker-diarization wasm example).
void CopyHeap(const char *src, int32_t num_bytes, char *dst) {
  std::copy(src, src + num_bytes, dst);
}
}
