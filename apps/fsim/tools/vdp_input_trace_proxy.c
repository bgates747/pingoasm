#define _POSIX_C_SOURCE 200809L

/*
 * Headless keyboard-input proxy for Fab Agon Emulator native VDP modules.
 *
 * Fab already delivers SDL keyboard events through the native VDP ABI entry
 * point sendPS2KbEventToFabgl(). This diagnostic shim forwards that complete
 * ABI to an unchanged real module and, once per host vblank, drains optional
 * set-2 make/break commands from a named pipe through the same entry point.
 *
 * Required environment:
 *   FAB_INPUT_REAL_VDP=/absolute/path/to/real-vdp.so
 * Optional environment:
 *   FAB_INPUT_FIFO=/absolute/path/to/named-pipe
 *
 * FIFO commands (one per line):
 *   down 0x002a
 *   up   0x002a
 *   tap  0x002a 4
 *   tapafter 0xe072 380 18
 *
 * "tap" emits the make event at the vblank that consumes the command and the
 * break event after the requested number of subsequent vblanks. FabGL's
 * sendPS2KbEventToFabgl() takes the complete set-2 code in a uint16_t, so
 * extended keys use values such as 0xe075 for Up.
 * "tapafter" schedules that make/break pair after a positive vblank delay.
 */

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define INPUT_BUFFER_CAPACITY 4096u
#define PENDING_EVENT_CAPACITY 64u

typedef void (*void_fn)(void);
typedef void (*set_mode_fn)(uint32_t);
typedef bool (*uart_cts_fn)(void);
typedef void (*uart_send_fn)(uint8_t);
typedef bool (*uart_recv_fn)(uint8_t *);
typedef void (*key_fn)(uint16_t, uint8_t);
typedef void (*vkey_fn)(uint32_t, uint8_t);
typedef void (*mouse_fn)(const uint8_t *);
typedef void (*debug_fn)(bool);
typedef void (*audio_fn)(uint8_t *, uint32_t);
typedef void (*framebuffer_fn)(uint32_t *, uint32_t *, uint8_t *, float *);

struct pending_event {
    uint16_t scancode;
    uint64_t due_frame;
    bool down;
    bool used;
    const char *source;
};

static void *real_vdp;
static int input_fifo = -1;
static uint64_t input_frame;
static char input_buffer[INPUT_BUFFER_CAPACITY];
static size_t input_buffer_length;
static struct pending_event pending_events[PENDING_EVENT_CAPACITY];

static void fail_closed(const char *message) {
    const char *detail = dlerror();
    fprintf(
        stderr,
        "FAB_INPUT_FATAL %s%s%s\n",
        message,
        detail == NULL ? "" : ": ",
        detail == NULL ? "" : detail);
    fflush(stderr);
    _exit(127);
}

static void ensure_real_vdp(void) {
    if (real_vdp != NULL) {
        return;
    }

    const char *path = getenv("FAB_INPUT_REAL_VDP");
    if (path == NULL || *path == '\0') {
        fail_closed("FAB_INPUT_REAL_VDP is unset");
    }

    dlerror();
    real_vdp = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (real_vdp == NULL) {
        fail_closed("could not load real VDP module");
    }

    const char *fifo_path = getenv("FAB_INPUT_FIFO");
    if (fifo_path != NULL && *fifo_path != '\0') {
        input_fifo = open(fifo_path, O_RDONLY | O_NONBLOCK);
        if (input_fifo < 0) {
            fprintf(
                stderr,
                "FAB_INPUT_FATAL could not open FIFO %s: %s\n",
                fifo_path,
                strerror(errno));
            fflush(stderr);
            _exit(127);
        }
        struct stat status;
        if (fstat(input_fifo, &status) != 0 || !S_ISFIFO(status.st_mode)) {
            fprintf(
                stderr,
                "FAB_INPUT_FATAL input path is not a named pipe: %s\n",
                fifo_path);
            fflush(stderr);
            _exit(127);
        }
    }

    fprintf(
        stderr,
        "FAB_INPUT_READY real_vdp=%s fifo=%s\n",
        path,
        input_fifo < 0 ? "disabled" : fifo_path);
    fflush(stderr);
}

static void *required_symbol(const char *name) {
    ensure_real_vdp();
    dlerror();
    void *symbol = dlsym(real_vdp, name);
    const char *error = dlerror();
    if (symbol == NULL || error != NULL) {
        fprintf(
            stderr,
            "FAB_INPUT_FATAL missing real VDP symbol %s%s%s\n",
            name,
            error == NULL ? "" : ": ",
            error == NULL ? "" : error);
        fflush(stderr);
        _exit(127);
    }
    return symbol;
}

#define RESOLVE(type, variable, name) \
    static type variable;              \
    if (variable == NULL) {            \
        *(void **)(&variable) = required_symbol(name); \
    }

static void emit_key_event(uint16_t scancode, bool down, const char *source) {
    RESOLVE(key_fn, send_key, "sendPS2KbEventToFabgl");
    send_key(scancode, down ? 1u : 0u);
    fprintf(
        stderr,
        "FAB_INPUT frame=%" PRIu64 " action=%s scancode=0x%04x source=%s\n",
        input_frame,
        down ? "down" : "up",
        (unsigned int)scancode,
        source);
    fflush(stderr);
}

static bool parse_scancode(const char *text, uint16_t *result) {
    errno = 0;
    char *end = NULL;
    unsigned long value = strtoul(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0' || value > UINT16_MAX) {
        return false;
    }
    *result = (uint16_t)value;
    return true;
}

static bool parse_frames(const char *text, uint64_t *result) {
    errno = 0;
    char *end = NULL;
    unsigned long long value = strtoull(text, &end, 0);
    if (errno != 0 || end == text || *end != '\0' || value == 0) {
        return false;
    }
    *result = (uint64_t)value;
    return true;
}

static int schedule_event(
        uint16_t scancode,
        uint64_t frames,
        bool down,
        const char *source) {
    if (frames > UINT64_MAX - input_frame) {
        return -1;
    }
    for (size_t index = 0; index < PENDING_EVENT_CAPACITY; ++index) {
        if (!pending_events[index].used) {
            pending_events[index].used = true;
            pending_events[index].scancode = scancode;
            pending_events[index].due_frame = input_frame + frames;
            pending_events[index].down = down;
            pending_events[index].source = source;
            return (int)index;
        }
    }
    return -1;
}

static bool schedule_tap(
        uint16_t scancode,
        uint64_t delay,
        uint64_t frames) {
    int make_index = schedule_event(
        scancode, delay, true, "tapafter-make");
    if (make_index < 0) {
        return false;
    }
    if (schedule_event(
            scancode, delay + frames, false, "tapafter-release") < 0) {
        pending_events[make_index].used = false;
        return false;
    }
    return true;
}

static void report_bad_command(const char *verb) {
    fprintf(
        stderr,
        "FAB_INPUT_ERROR frame=%" PRIu64 " command=%s\n",
        input_frame,
        verb == NULL ? "(empty)" : verb);
    fflush(stderr);
}

static void execute_command(char *line) {
    char *save = NULL;
    char *verb = strtok_r(line, " \t", &save);
    if (verb == NULL || *verb == '#') {
        return;
    }
    char *code_text = strtok_r(NULL, " \t", &save);
    char *frames_text = strtok_r(NULL, " \t", &save);
    char *hold_text = strtok_r(NULL, " \t", &save);
    char *extra = strtok_r(NULL, " \t", &save);
    uint16_t scancode = 0;

    if (code_text == NULL || !parse_scancode(code_text, &scancode)) {
        report_bad_command(verb);
        return;
    }

    if (strcmp(verb, "down") == 0 && frames_text == NULL) {
        emit_key_event(scancode, true, "fifo");
        return;
    }
    if (strcmp(verb, "up") == 0 && frames_text == NULL) {
        emit_key_event(scancode, false, "fifo");
        return;
    }
    if (strcmp(verb, "tap") == 0 && frames_text != NULL &&
        hold_text == NULL) {
        uint64_t frames = 0;
        if (parse_frames(frames_text, &frames) &&
            schedule_event(
                scancode, frames, false, "tap-release") >= 0) {
            emit_key_event(scancode, true, "fifo-tap");
            return;
        }
    }
    if (strcmp(verb, "tapafter") == 0 && frames_text != NULL &&
        hold_text != NULL && extra == NULL) {
        uint64_t delay = 0;
        uint64_t frames = 0;
        if (parse_frames(frames_text, &delay) &&
            parse_frames(hold_text, &frames) &&
            delay <= UINT64_MAX - frames &&
            schedule_tap(scancode, delay, frames)) {
            return;
        }
    }
    report_bad_command(verb);
}

static void consume_complete_lines(void) {
    size_t consumed = 0;
    while (consumed < input_buffer_length) {
        char *newline = memchr(
            input_buffer + consumed,
            '\n',
            input_buffer_length - consumed);
        if (newline == NULL) {
            break;
        }
        *newline = '\0';
        if (newline > input_buffer + consumed && newline[-1] == '\r') {
            newline[-1] = '\0';
        }
        execute_command(input_buffer + consumed);
        consumed = (size_t)(newline - input_buffer) + 1u;
    }

    if (consumed > 0) {
        memmove(
            input_buffer,
            input_buffer + consumed,
            input_buffer_length - consumed);
        input_buffer_length -= consumed;
    }
}

static void drain_input_fifo(void) {
    if (input_fifo < 0) {
        return;
    }

    for (;;) {
        if (input_buffer_length == sizeof(input_buffer)) {
            fprintf(
                stderr,
                "FAB_INPUT_ERROR frame=%" PRIu64 " input-buffer-overflow\n",
                input_frame);
            fflush(stderr);
            input_buffer_length = 0;
        }

        ssize_t count = read(
            input_fifo,
            input_buffer + input_buffer_length,
            sizeof(input_buffer) - input_buffer_length);
        if (count > 0) {
            input_buffer_length += (size_t)count;
            consume_complete_lines();
            continue;
        }
        if (count == 0 || errno == EAGAIN || errno == EWOULDBLOCK) {
            break;
        }
        fprintf(
            stderr,
            "FAB_INPUT_ERROR frame=%" PRIu64 " fifo-read=%s\n",
            input_frame,
            strerror(errno));
        fflush(stderr);
        break;
    }
}

static void emit_due_events(void) {
    for (size_t index = 0; index < PENDING_EVENT_CAPACITY; ++index) {
        if (pending_events[index].used &&
            pending_events[index].due_frame <= input_frame) {
            uint16_t scancode = pending_events[index].scancode;
            bool down = pending_events[index].down;
            const char *source = pending_events[index].source;
            pending_events[index].used = false;
            emit_key_event(scancode, down, source);
        }
    }
}

/* Complete Fab native VDP ABI forwarding surface. */

void vdp_setup(void) {
    RESOLVE(void_fn, function, "vdp_setup");
    function();
}

void vdp_loop(void) {
    RESOLVE(void_fn, function, "vdp_loop");
    function();
}

void vdp_shutdown(void) {
    RESOLVE(void_fn, function, "vdp_shutdown");
    function();
}

void signal_vblank(void) {
    RESOLVE(void_fn, function, "signal_vblank");
    ++input_frame;
    emit_due_events();
    drain_input_fifo();
    function();
}

void set_startup_screen_mode(uint32_t mode) {
    RESOLVE(set_mode_fn, function, "set_startup_screen_mode");
    function(mode);
}

bool z80_uart0_is_cts(void) {
    RESOLVE(uart_cts_fn, function, "z80_uart0_is_cts");
    return function();
}

void z80_send_to_vdp(uint8_t byte) {
    RESOLVE(uart_send_fn, function, "z80_send_to_vdp");
    function(byte);
}

bool z80_recv_from_vdp(uint8_t *output) {
    RESOLVE(uart_recv_fn, function, "z80_recv_from_vdp");
    return function(output);
}

void sendVKeyEventToFabgl(uint32_t key, uint8_t down) {
    RESOLVE(vkey_fn, function, "sendVKeyEventToFabgl");
    function(key, down);
}

void sendPS2KbEventToFabgl(uint16_t scancode, uint8_t down) {
    RESOLVE(key_fn, function, "sendPS2KbEventToFabgl");
    function(scancode, down);
}

void sendHostMouseEventToFabgl(const uint8_t *packet) {
    RESOLVE(mouse_fn, function, "sendHostMouseEventToFabgl");
    function(packet);
}

void setVdpDebugLogging(bool enabled) {
    RESOLVE(debug_fn, function, "setVdpDebugLogging");
    function(enabled);
}

void getAudioSamples(uint8_t *output, uint32_t length) {
    RESOLVE(audio_fn, function, "getAudioSamples");
    function(output, length);
}

void copyVgaFramebuffer(
    uint32_t *width,
    uint32_t *height,
    uint8_t *output,
    float *frame_rate_hz) {
    RESOLVE(framebuffer_fn, function, "copyVgaFramebuffer");
    function(width, height, output, frame_rate_hz);
}

void dump_vdp_mem_stats(void) {
    RESOLVE(void_fn, function, "dump_vdp_mem_stats");
    function();
}
