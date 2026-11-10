/*
 The language model test of Duo Keyboard.

 The test loads one small language model through llama.cpp, on the processor only, and measures
 its speed and the memory the process holds. The test does not change what the keyboard types.
 It answers one question: can a model of this size score the typing engine's candidate words
 inside the keyboard extension, where iOS allows far less memory than in an app?

 The result is text, one fact per line. Each line starts with a name in a column 12 wide.

   model       file name, file size, count of weights, size of the vocabulary
   memory      at one moment: the footprint (the value iOS holds against the limit), the highest
               footprint of the process so far, and the memory iOS still allows. The footprint
               and the allowed memory together give the limit of the process.
   load        time to open the model. The weights stay in the file and iOS reads them on use.
   threads     count of threads for the lines that do not name a count
   context     time to read 20 tokens of English and give the probability of every next token.
               "cold" is the first run after the load, "warm" a second run on an empty cache.
   per token   time to read one more token and give the scores of every next token, over
               200 tokens that follow the context
   candidates  the measurement the later feature needs: the context is read once, and 8
               candidate continuations of 1 to 3 tokens get their probability from the stored
               state of the context. "one by one" reads each candidate alone. "in one batch"
               reads all of them in one call.
   done        the model is freed and the test is over

 A line that holds the word "failed" names the step that did not run, and the test then frees
 what it loaded and stops. Two checks only mark the result and let the test go on: a memory
 reading that iOS refused, and candidate scores that differ between the two ways.

 1 MB is 1,048,576 bytes in every line.
 */
#ifndef DUO_LM_PROBE_H
#define DUO_LM_PROBE_H

#ifdef __cplusplus
extern "C" {
#endif

/* Receives one result line, without a line break. `context` is the caller's own pointer. */
typedef void (*duo_lm_line_fn)(const char *line, void *context);

/* Runs the whole test on the calling thread with the model file at `model_path`, and hands
   each result line to `emit` as soon as the line exists. The model is freed before the call
   returns. Returns 1 when every step ran and every check held, and 0 otherwise. */
int duo_lm_measure(const char *model_path, duo_lm_line_fn emit, void *context);

#ifdef __cplusplus
}
#endif

#endif
