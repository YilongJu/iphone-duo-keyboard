/*
 Runs the language model test of LanguageModel/duo_lm_probe.c from a command line and prints
 its result lines. run_on_linux.sh builds and runs this program.

 Usage: probe_cli MODEL.gguf
 The exit code is 0 when every step of the test ran.
 */
#include "duo_lm_probe.h"

#include <stdio.h>

static void print_line(const char *line, void *context) {
    (void)context;
    puts(line);
    fflush(stdout);
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: probe_cli MODEL.gguf\n");
        return 2;
    }
    return duo_lm_measure(argv[1], print_line, NULL) == 1 ? 0 : 1;
}
