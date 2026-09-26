#ifndef CPPJIT_INTEROP_STDERRCAPTURE_H
#define CPPJIT_INTEROP_STDERRCAPTURE_H

// Standard
#include <cstdio>
#include <iostream>
#include <string>

#ifdef _WIN32
#include <io.h>
#define CPPJIT_DUP _dup
#define CPPJIT_DUP2 _dup2
#define CPPJIT_FILENO _fileno
#define CPPJIT_CLOSE _close
#else
#include <unistd.h>
#define CPPJIT_DUP dup
#define CPPJIT_DUP2 dup2
#define CPPJIT_FILENO fileno
#define CPPJIT_CLOSE close
#endif

namespace cppjit::interop {

// Redirects file descriptor 2 into an anonymous temporary file for the
// object's lifetime. clang's diagnostics and ORC's "JIT session error"
// reports go through llvm::errs(), which writes to the descriptor and
// bypasses std::cerr, so a stream-buffer swap never sees them. The
// descriptor is process-global: output from other threads lands in the
// capture too, and nested captures must stop in reverse order. A file
// rather than a pipe holds any amount of output without a reader.
class StderrCapture {
public:
  StderrCapture() {
    std::cout.flush();
    std::cerr.flush();
    fflush(stderr);
    fFile = tmpfile();
    if (!fFile)
      return; // output stays on the descriptor
    fSavedFd = CPPJIT_DUP(2);
    if (fSavedFd == -1 || CPPJIT_DUP2(CPPJIT_FILENO(fFile), 2) == -1) {
      if (fSavedFd != -1)
        CPPJIT_CLOSE(fSavedFd);
      fSavedFd = -1;
      fclose(fFile);
      fFile = nullptr;
    }
  }
  ~StderrCapture() { Stop(); }
  StderrCapture(const StderrCapture&) = delete;
  StderrCapture& operator=(const StderrCapture&) = delete;

  // whether the descriptor is redirected
  bool IsActive() const { return fSavedFd != -1; }

  // Restores the descriptor and returns what was written meanwhile.
  std::string Stop() {
    std::string text;
    if (!IsActive())
      return text;
    std::cerr.flush();
    fflush(stderr);
    CPPJIT_DUP2(fSavedFd, 2);
    CPPJIT_CLOSE(fSavedFd);
    fSavedFd = -1;
    rewind(fFile);
    char buf[4096];
    for (size_t n; (n = fread(buf, 1, sizeof(buf), fFile)) > 0;)
      text.append(buf, n);
    fclose(fFile);
    fFile = nullptr;
    return text;
  }

private:
  int fSavedFd = -1;
  FILE* fFile = nullptr;
};

} // namespace cppjit::interop

#undef CPPJIT_DUP
#undef CPPJIT_DUP2
#undef CPPJIT_FILENO
#undef CPPJIT_CLOSE

#endif // !CPPJIT_INTEROP_STDERRCAPTURE_H
