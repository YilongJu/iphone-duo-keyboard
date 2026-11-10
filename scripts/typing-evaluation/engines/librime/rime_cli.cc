// Runs librime over typed Pinyin letters and prints the text that librime would commit.
//
// Build, on a machine with the librime headers:
//   g++ -std=c++17 -O2 -Wall -Wextra rime_cli.cc -o rime_cli -lrime
//
// Usage:
//   rime_cli version
//   rime_cli deploy --shared DIR --user DIR
//   rime_cli run --shared DIR --user DIR --schema ID --correction on|off < cases.tsv > outputs.tsv
//
// "deploy" compiles the schema and its dictionary into DIR/build of the user folder.
// "run" reads one case per line, "id<TAB>letters", and prints one line per case:
//   id<TAB>output<TAB>stop<TAB>selections<TAB>first_candidate
//
// For each case the program types the letters as key events and reads librime's commit preview.
// The commit preview holds the first candidate, followed by the letters that the first candidate
// does not cover. While such letters remain and librime offers a candidate, the program presses
// space. Space selects the first candidate and librime composes the remaining letters again.
// The program reads the commit preview and clears the composition. librime commits only on a
// space press that covers every letter, and the program does not send that press, so the user
// dictionary of librime stays empty and one case does not change the next case.
//
// The column "stop" names the reason the program stopped:
//   covered        the first candidates cover every letter
//   no_candidates  librime offers no candidate for the remaining letters, and the output ends
//                  with these letters, as it would after a commit
//   committed      librime committed on a space press. The program counts these cases, because
//                  a commit feeds the user dictionary.
#include <rime_api.h>

#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <string>

namespace {

const int kSpaceKey = 0x20;

RimeApi* rime = nullptr;
std::string deploy_message;

[[noreturn]] void die(const std::string& message) {
  std::cerr << "rime_cli: error: " << message << std::endl;
  std::exit(1);
}

void on_message(void*, RimeSessionId, const char* type, const char* value) {
  std::cerr << "rime_cli: librime message: " << type << " " << value << std::endl;
  if (std::strcmp(type, "deploy") == 0) {
    deploy_message = value;
  }
}

std::map<std::string, std::string> read_flags(int argc, char** argv, int first) {
  std::map<std::string, std::string> flags;
  for (int i = first; i < argc; i += 2) {
    std::string name = argv[i];
    if (name.rfind("--", 0) != 0 || i + 1 >= argc) {
      die("expected a flag followed by a value, got '" + name + "'");
    }
    flags[name.substr(2)] = argv[i + 1];
  }
  return flags;
}

std::string required(const std::map<std::string, std::string>& flags, const std::string& name) {
  auto found = flags.find(name);
  if (found == flags.end() || found->second.empty()) {
    die("missing the flag --" + name);
  }
  return found->second;
}

// Points librime at the two data folders and starts its service.
void setup(const std::string& shared, const std::string& user, int min_log_level) {
  RimeTraits traits = {};
  RIME_STRUCT_INIT(RimeTraits, traits);
  traits.shared_data_dir = shared.c_str();
  traits.user_data_dir = user.c_str();
  traits.distribution_name = "Typing evaluation";
  traits.distribution_code_name = "typing-evaluation";
  traits.distribution_version = "1";
  traits.app_name = "rime.typing-evaluation";
  traits.min_log_level = min_log_level;  // 0 is INFO, 1 is WARNING
  traits.log_dir = "";                   // an empty folder name sends the librime log to stderr
  rime->setup(&traits);
  rime->set_notification_handler(on_message, nullptr);
  rime->initialize(&traits);
}

int deploy(const std::map<std::string, std::string>& flags) {
  const std::string shared = required(flags, "shared");
  const std::string user = required(flags, "user");
  setup(shared, user, 0);
  if (!rime->start_maintenance(True)) {
    die("start_maintenance(True) returned False");
  }
  rime->join_maintenance_thread();
  rime->finalize();
  if (deploy_message != "success") {
    die("the deployment ended with the message '" + deploy_message + "'");
  }
  std::cerr << "rime_cli: the deployment ended with the message 'success'" << std::endl;
  return 0;
}

// The count of lower-case letters a to z at the end of the text.
size_t trailing_letters(const std::string& text) {
  size_t count = 0;
  while (count < text.size()) {
    char letter = text[text.size() - 1 - count];
    if (letter < 'a' || letter > 'z') {
      break;
    }
    ++count;
  }
  return count;
}

struct Conversion {
  std::string output;
  std::string stop;
  int selections = 0;
  std::string first_candidate;
};

Conversion convert(RimeSessionId session, const std::string& typed) {
  Conversion result;
  rime->clear_composition(session);
  for (char letter : typed) {
    if (letter < 'a' || letter > 'z') {
      die("the typed text '" + typed + "' holds a character outside a to z");
    }
    if (!rime->process_key(session, letter, 0)) {
      die(std::string("librime did not accept the key '") + letter + "' of '" + typed + "'");
    }
  }
  const char* input = rime->get_input(session);
  if (input == nullptr || typed != input) {
    die("librime holds the input '" + std::string(input ? input : "") + "' after the keys of '" + typed + "'");
  }

  size_t previous_remaining = typed.size() + 1;
  for (size_t step = 0;; ++step) {
    RimeContext context = {};
    RIME_STRUCT_INIT(RimeContext, context);
    if (!rime->get_context(session, &context)) {
      die("get_context returned False for '" + typed + "'");
    }
    const std::string preview = context.commit_text_preview ? context.commit_text_preview : "";
    const int candidates = context.menu.num_candidates;
    const int highlighted = context.menu.highlighted_candidate_index;
    const std::string first = candidates > 0 ? context.menu.candidates[0].text : "";
    rime->free_context(&context);

    if (preview.empty()) {
      die("librime gave an empty commit preview for '" + typed + "'");
    }
    if (candidates > 0 && highlighted != 0) {
      die("librime highlights candidate " + std::to_string(highlighted) + " for '" + typed + "', expected 0");
    }
    if (step == 0) {
      result.first_candidate = first;
    }
    const size_t remaining = trailing_letters(preview);
    if (remaining == 0) {
      result.output = preview;
      result.stop = "covered";
      return result;
    }
    if (candidates == 0) {
      result.output = preview;
      result.stop = "no_candidates";
      return result;
    }
    if (remaining >= previous_remaining) {
      die("a space press did not shorten the remaining letters of '" + typed + "', preview '" + preview + "'");
    }
    previous_remaining = remaining;

    if (!rime->process_key(session, kSpaceKey, 0)) {
      die("librime did not accept the space key for '" + typed + "'");
    }
    ++result.selections;
    RimeCommit commit = {};
    RIME_STRUCT_INIT(RimeCommit, commit);
    if (rime->get_commit(session, &commit)) {
      result.output = commit.text;
      result.stop = "committed";
      rime->free_commit(&commit);
      return result;
    }
  }
}

int run(const std::map<std::string, std::string>& flags) {
  const std::string shared = required(flags, "shared");
  const std::string user = required(flags, "user");
  const std::string schema = required(flags, "schema");
  const std::string correction = required(flags, "correction");
  if (correction != "on" && correction != "off") {
    die("--correction takes on or off, got '" + correction + "'");
  }
  setup(shared, user, 1);

  RimeSessionId session = rime->create_session();
  if (!session) {
    die("create_session returned 0");
  }
  if (!rime->select_schema(session, schema.c_str())) {
    die("select_schema returned False for '" + schema + "'");
  }
  char current[256] = "";
  if (!rime->get_current_schema(session, current, sizeof(current) - 1) || schema != current) {
    die("the session runs the schema '" + std::string(current) + "', expected '" + schema + "'");
  }

  // Read the deployed schema, to confirm that the session runs the settings the caller named.
  RimeConfig config = {};
  if (!rime->schema_open(schema.c_str(), &config)) {
    die("schema_open returned False for '" + schema + "'");
  }
  Bool correction_value = False;
  const bool correction_is_set = rime->config_get_bool(&config, "translator/enable_correction", &correction_value);
  const char* dictionary_text = rime->config_get_cstring(&config, "translator/dictionary");
  const std::string dictionary = dictionary_text ? dictionary_text : "";
  rime->config_close(&config);
  std::cerr << "rime_cli: librime " << rime->get_version() << ", schema " << current << ", dictionary " << dictionary
            << ", translator/enable_correction "
            << (correction_is_set ? (correction_value ? "true" : "false") : "absent (librime reads it as false)")
            << ", option ascii_mode " << (rime->get_option(session, "ascii_mode") ? "on" : "off") << ", option zh_simp "
            << (rime->get_option(session, "zh_simp") ? "on" : "off") << std::endl;
  if (dictionary.empty()) {
    die("the deployed schema '" + schema + "' does not name a dictionary");
  }
  const bool correction_on = correction_is_set && correction_value;
  if (correction_on != (correction == "on")) {
    die("translator/enable_correction of the deployed schema does not match --correction " + correction);
  }

  std::map<std::string, int> stops;
  int cases = 0;
  const auto start = std::chrono::steady_clock::now();
  auto seconds = [&start]() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
  };
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty()) {
      continue;
    }
    const size_t tab = line.find('\t');
    if (tab == std::string::npos || tab == 0 || tab + 1 >= line.size()) {
      die("expected 'id<TAB>letters', got '" + line + "'");
    }
    const std::string id = line.substr(0, tab);
    const std::string typed = line.substr(tab + 1);
    const Conversion result = convert(session, typed);
    std::cout << id << '\t' << result.output << '\t' << result.stop << '\t' << result.selections << '\t'
              << result.first_candidate << '\n';
    ++stops[result.stop];
    ++cases;
    if (cases % 500 == 0) {
      std::cerr << "rime_cli: " << cases << " cases after " << seconds() << " s" << std::endl;
    }
  }
  std::cout.flush();
  rime->clear_composition(session);
  std::cerr << "rime_cli: " << cases << " cases in " << seconds() << " s";
  for (const auto& entry : stops) {
    std::cerr << ", " << entry.first << " " << entry.second;
  }
  std::cerr << std::endl;
  rime->destroy_session(session);
  rime->finalize();
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    die("expected a command: version, deploy or run");
  }
  rime = rime_get_api();
  if (rime == nullptr) {
    die("rime_get_api returned a null pointer");
  }
  const std::string command = argv[1];
  if (command == "version") {
    std::cout << rime->get_version() << std::endl;
    return 0;
  }
  if (command == "deploy") {
    return deploy(read_flags(argc, argv, 2));
  }
  if (command == "run") {
    return run(read_flags(argc, argv, 2));
  }
  die("unknown command '" + command + "'");
}
