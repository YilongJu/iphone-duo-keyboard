// Shared steps of the two adapter programs in this folder.
//
// Each program gives one function, the search: letters in, the engine's first candidate out,
// with the count of leading letters that the candidate covers. This header reads the cases,
// builds the text of each case from first candidates, and prints the adapter statistics.
//
// Standard input holds one case per line: the case id, a tab, and the typed letters a to z.
// Standard output gets one line per case: the case id, a tab, and the text.
// Standard error gets the adapter statistics.
//
// The text for one case comes from these steps:
//   1. Search with the letters that are left.
//   2. When the engine gives a first candidate, add the candidate to the text.
//   3. When the engine does not give one, search again with one letter fewer.
//   4. A letter that does not start any candidate goes to the text unchanged.
//   5. Repeat from step 1 with the letters after the covered ones.
//
// Every search runs in a child process. The engine libraries in the Ubuntu packages are built
// with assertions on, and a failed assertion aborts the process. The parent process treats an
// aborted search as a search without a candidate, so step 3 applies.
#ifndef TYPING_EVALUATION_FIRST_CANDIDATES_H
#define TYPING_EVALUATION_FIRST_CANDIDATES_H

#include <algorithm>
#include <cerrno>
#include <csignal>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <map>
#include <string>

#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

namespace first_candidates {

// The result of one search with a string of letters.
struct SearchResult {
    size_t covered = 0;          // leading letters that the engine used
    bool has_candidate = false;  // false when the engine does not give a candidate for them
    std::string text;            // the first candidate, in UTF-8
};

using Search = std::function<SearchResult(const std::string &letters)>;

struct Statistics {
    size_t cases = 0;
    size_t cases_with_one_search = 0;
    size_t searches = 0;
    size_t searches_without_candidate = 0;
    size_t aborted_searches = 0;
    size_t cases_with_aborted_search = 0;
    size_t shortest_aborted_search = 0;
    size_t unchanged_letters = 0;
    size_t cases_with_unchanged_letters = 0;
    // Each distinct line that a search process wrote to standard error, with its count.
    std::map<std::string, size_t> error_lines;
};

inline const char *&program_name() {
    static const char *name = "adapter";
    return name;
}

inline bool &in_child_process() {
    static bool value = false;
    return value;
}

[[noreturn]] inline void fail(const std::string &message) {
    std::cerr << program_name() << ": " << message << std::endl;
    if (in_child_process())
        _exit(1);
    std::exit(1);
}

inline std::string read_all(int descriptor) {
    std::string data;
    char buffer[4096];
    for (;;) {
        const ssize_t count = read(descriptor, buffer, sizeof buffer);
        if (count > 0)
            data.append(buffer, static_cast<size_t>(count));
        else if (count == 0)
            break;
        else if (errno != EINTR)
            fail("read from a search process did not work");
    }
    return data;
}

inline void write_all(int descriptor, const std::string &data) {
    size_t written = 0;
    while (written < data.size()) {
        const ssize_t count = write(descriptor, data.data() + written, data.size() - written);
        if (count > 0)
            written += static_cast<size_t>(count);
        else if (errno != EINTR)
            fail("write to the parent process did not work");
    }
}

// Runs one search in a child process. `aborted` becomes true when SIGABRT ended the child.
inline SearchResult search_in_child(const Search &search, const std::string &letters, bool &aborted,
                                    Statistics &statistics) {
    int result_pipe[2];
    int error_pipe[2];
    if (pipe(result_pipe) != 0 || pipe(error_pipe) != 0)
        fail("pipe did not work");
    std::cout.flush();
    const pid_t child = fork();
    if (child < 0)
        fail("fork did not work");
    if (child == 0) {
        in_child_process() = true;
        close(result_pipe[0]);
        close(error_pipe[0]);
        if (dup2(error_pipe[1], STDERR_FILENO) < 0)
            _exit(2);
        const SearchResult result = search(letters);
        std::string message = std::to_string(result.covered);
        message += result.has_candidate ? "\t1\t" : "\t0\t";
        message += result.text;
        write_all(result_pipe[1], message);
        _exit(0);
    }
    close(result_pipe[1]);
    close(error_pipe[1]);
    const std::string message = read_all(result_pipe[0]);
    const std::string error_text = read_all(error_pipe[0]);
    close(result_pipe[0]);
    close(error_pipe[0]);
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR)
            fail("waitpid did not work");
    }

    size_t line_start = 0;
    while (line_start < error_text.size()) {
        size_t line_end = error_text.find('\n', line_start);
        if (line_end == std::string::npos)
            line_end = error_text.size();
        if (line_end > line_start)
            statistics.error_lines[error_text.substr(line_start, line_end - line_start)]++;
        line_start = line_end + 1;
    }

    aborted = WIFSIGNALED(status) && WTERMSIG(status) == SIGABRT;
    if (aborted)
        return SearchResult();
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
        fail("the search process for " + letters + " ended with wait status " + std::to_string(status) + ": " +
             error_text);

    const size_t first_tab = message.find('\t');
    const size_t second_tab = first_tab == std::string::npos ? first_tab : message.find('\t', first_tab + 1);
    if (second_tab == std::string::npos)
        fail("the search process for " + letters + " returned a message without two tabs");
    SearchResult result;
    result.covered = static_cast<size_t>(std::stoull(message.substr(0, first_tab)));
    result.has_candidate = message.substr(first_tab + 1, second_tab - first_tab - 1) == "1";
    result.text = message.substr(second_tab + 1);
    return result;
}

// Puts the first candidate for a leading part of `letters` in `text`.
// Returns the count of letters that the candidate covers.
// Returns 0 when the engine does not give a candidate for any leading part.
// `most_letters` is the count of letters that one search of the engine reads. 0 means every letter.
inline size_t first_candidate(const Search &search, const std::string &letters, size_t most_letters,
                              std::string &text, bool &case_has_aborted_search, Statistics &statistics) {
    size_t length = letters.size();
    if (most_letters > 0)
        length = std::min(length, most_letters);
    while (length > 0) {
        const std::string attempt = letters.substr(0, length);
        bool aborted = false;
        const SearchResult result = search_in_child(search, attempt, aborted, statistics);
        statistics.searches++;
        if (aborted) {
            statistics.aborted_searches++;
            case_has_aborted_search = true;
            if (statistics.shortest_aborted_search == 0 || length < statistics.shortest_aborted_search)
                statistics.shortest_aborted_search = length;
            length -= 1;
            continue;
        }
        if (result.covered > length)
            fail("the engine covered more letters than it got for " + attempt);
        if (result.covered == 0)
            return 0;
        if (result.has_candidate) {
            if (result.text.empty())
                fail("the first candidate is empty for " + attempt);
            text = result.text;
            return result.covered;
        }
        statistics.searches_without_candidate++;
        length = result.covered - 1;
    }
    return 0;
}

inline std::string convert(const Search &search, const std::string &letters, size_t most_letters,
                           Statistics &statistics) {
    std::string output;
    size_t position = 0;
    size_t unchanged = 0;
    bool case_has_aborted_search = false;
    const size_t searches_before = statistics.searches;
    while (position < letters.size()) {
        std::string text;
        const size_t covered = first_candidate(search, letters.substr(position), most_letters, text,
                                               case_has_aborted_search, statistics);
        if (covered == 0) {
            output += letters[position];
            position += 1;
            unchanged++;
        } else {
            output += text;
            position += covered;
        }
    }
    statistics.cases++;
    if (statistics.searches - searches_before == 1 && unchanged == 0)
        statistics.cases_with_one_search++;
    if (case_has_aborted_search)
        statistics.cases_with_aborted_search++;
    statistics.unchanged_letters += unchanged;
    if (unchanged > 0)
        statistics.cases_with_unchanged_letters++;
    return output;
}

// Reads every case from standard input, writes every text to standard output, and prints the statistics.
inline void run_cases(const Search &search, size_t most_letters) {
    Statistics statistics;
    std::string line;
    while (std::getline(std::cin, line)) {
        const size_t tab = line.find('\t');
        if (tab == std::string::npos || tab == 0)
            fail("an input line does not hold an id, a tab and letters: " + line);
        const std::string id = line.substr(0, tab);
        const std::string letters = line.substr(tab + 1);
        if (letters.empty())
            fail("the case " + id + " does not hold letters");
        for (const char letter : letters) {
            if (letter < 'a' || letter > 'z')
                fail("the case " + id + " holds a character outside a to z");
        }
        std::cout << id << '\t' << convert(search, letters, most_letters, statistics) << '\n';
    }
    std::cout.flush();

    std::cerr << "cases: " << statistics.cases << '\n'
              << "cases where one search covered all letters: " << statistics.cases_with_one_search << '\n'
              << "searches: " << statistics.searches << '\n'
              << "searches without a first candidate: " << statistics.searches_without_candidate << '\n'
              << "searches that the engine library aborted: " << statistics.aborted_searches << '\n'
              << "cases with an aborted search: " << statistics.cases_with_aborted_search << '\n'
              << "letters in the shortest aborted search: " << statistics.shortest_aborted_search << '\n'
              << "cases with a letter left unchanged: " << statistics.cases_with_unchanged_letters << '\n'
              << "letters left unchanged: " << statistics.unchanged_letters << '\n';
    for (const auto &entry : statistics.error_lines)
        std::cerr << "standard error of the search processes, " << entry.second << " times: " << entry.first << '\n';
}

}  // namespace first_candidates

#endif  // TYPING_EVALUATION_FIRST_CANDIDATES_H
