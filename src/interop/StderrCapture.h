#ifndef CPPJIT_INTEROP_STDERRCAPTURE_H
#define CPPJIT_INTEROP_STDERRCAPTURE_H

#include <cstdio>
#include <string>
#include <unistd.h>
#ifdef __linux__
#include <sys/mman.h>
#endif

namespace cppjit::interop {

// Redirects descriptor 2 into an anonymous file between Begin and Stop. clang
// and the JIT report on the descriptor, which a std::cerr buffer swap misses.
class StderrCapture {
public:
  ~StderrCapture() { Stop(); }

  void Begin() {
    if (fFd != -1)
      return;
    fflush(stderr);
#ifdef __linux__
    fFd = memfd_create("cppjit-stderr", MFD_CLOEXEC);
#else
    if (FILE* f = tmpfile()) {
      fFd = dup(fileno(f));
      fclose(f);
    }
#endif
    if (fFd == -1 || (fSaved = dup(2)) == -1 || dup2(fFd, 2) == -1)
      Stop(); // the output stays on the descriptor
  }

  // restores the descriptor and returns the text written meanwhile
  std::string Stop() {
    std::string text;
    if (fFd == -1)
      return text;
    fflush(stderr);
    if (fSaved != -1) {
      dup2(fSaved, 2);
      close(fSaved);
    }
    lseek(fFd, 0, SEEK_SET);
    char buf[4096];
    for (ssize_t n; (n = read(fFd, buf, sizeof buf)) > 0;)
      text.append(buf, n);
    close(fFd);
    fFd = fSaved = -1;
    return text;
  }

private:
  int fFd = -1;
  int fSaved = -1;
};

} // namespace cppjit::interop

#endif // !CPPJIT_INTEROP_STDERRCAPTURE_H
