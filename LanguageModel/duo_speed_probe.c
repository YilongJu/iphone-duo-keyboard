#include "duo_speed_probe.h"

#include <fcntl.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>

double duo_speed_resident_share(const char *path) {
    int file = open(path, O_RDONLY);
    if (file < 0) return -1;
    struct stat facts;
    if (fstat(file, &facts) != 0) {
        close(file);
        return -1;
    }
    size_t size = (size_t)facts.st_size;
    if (size == 0) {
        close(file);
        return -2;
    }
    void *base = mmap(NULL, size, PROT_READ, MAP_SHARED, file, 0);
    close(file);
    if (base == MAP_FAILED) return -1;
    size_t page = (size_t)getpagesize();
    size_t pages = (size + page - 1) / page;
    /* Darwin declares the vector of mincore as char, Linux as unsigned char. */
#if defined(__APPLE__)
    char *vector = (char *)malloc(pages);
#else
    unsigned char *vector = (unsigned char *)malloc(pages);
#endif
    if (vector == NULL) {
        munmap(base, size);
        return -1;
    }
    double share = -1;
    if (mincore(base, size, vector) == 0) {
        size_t resident = 0;
        for (size_t index = 0; index < pages; index++) resident += (vector[index] & 1) != 0;
        share = (double)resident / (double)pages;
    }
    free(vector);
    munmap(base, size);
    return share;
}

double duo_speed_process_milliseconds(void) {
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) != 0) return -1;
    return (double)(usage.ru_utime.tv_sec + usage.ru_stime.tv_sec) * 1000.0
        + (double)(usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) / 1000.0;
}
