/*
 Two measurements of the process for the speed test of docs/model-speed-design.md
 (Shared/ModelSpeedTest.swift). Neither changes what the process does.
 */
#ifndef DUO_SPEED_PROBE_H
#define DUO_SPEED_PROBE_H

#ifdef __cplusplus
extern "C" {
#endif

/* The share, 0 to 1, of the pages of the file at `path` that are in memory now, from mincore.
   The file is mapped and unmapped again, and no page of it is read. Returns -1 when the file
   does not open, does not map or mincore refuses, and -2 for an empty file. */
double duo_speed_resident_share(const char *path);

/* The processor time of the whole process so far, user and system, in milliseconds, from
   getrusage. Returns -1 when getrusage refuses. */
double duo_speed_process_milliseconds(void);

#ifdef __cplusplus
}
#endif

#endif
