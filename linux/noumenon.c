/* Noumenon: native X11/XScreenSaver renderer. */
#define _POSIX_C_SOURCE 200809L
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <cairo/cairo.h>
#include <cairo/cairo-xlib.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "glyph_data.h"

enum { LAYER_COUNT = 3, FPS = 40, MAX_SIZE = 8192 };
/* Live glyphs: the newest SVGs that `python -m live` writes to the feed folder
   join the original family while the saver runs. As in the web explorer they
   fill the pool beside the 192 approved originals and then replace them one by
   one, so up to 256 originals are in play and the newest are always among them. */
enum { LIVE_MAX = 256, LIVE_POOL = 256, LIVE_NAME = 96, LIVE_PATH = 4096,
       LIVE_FILE_BYTES = 262144, LIVE_COMMANDS = 16000, LIVE_LISTED = 65536 };
#define LIVE_SCAN_SECONDS 2.0
#define GLYPH_SLOTS (GLYPH_COUNT + LIVE_MAX)
typedef struct {
    char name[LIVE_NAME];
    GlyphCommand *commands;
    int count, used;
} LiveGlyph;
typedef struct { char name[LIVE_NAME]; } LiveName;
typedef struct {
    double x, y, rate, accumulator, burst;
    int glyph, phase;
    uint32_t seed;
} Column;
typedef struct {
    cairo_surface_t *trail[GLYPH_SLOTS], *head[GLYPH_SLOTS];
    Column *columns;
    int count;
    double cell, pad, step, speed, level;
} Layer;
typedef struct {
    Layer layers[LAYER_COUNT];
    cairo_surface_t *image;
    int width, height;
    uint64_t reference_cells, original_cells, blank_cells, live_cells;
} Scene;

static volatile sig_atomic_t stopping = 0;
static int x_error = 0;
static Window live_window = 0;
static uint32_t random_state = 0x534d5954u;
static double original_mix = GLYPH_ORIGINAL_SHARE;
static LiveGlyph live[LIVE_MAX];
static int live_order[LIVE_MAX], live_count = 0, live_files = 0, live_considered = 0;
static int live_trail = 18;
static double live_speed = 1.5;
static char live_folder[LIVE_PATH];

static void stop_signal(int number) { (void)number; stopping = 1; }
static int handle_x_error(Display *display, XErrorEvent *event) {
    /* A manager may destroy its preview between our event pump and paint.
       A vanished established target is normal shutdown, not a bad CLI ID. */
    if (live_window && event->resourceid == live_window &&
        (event->error_code == BadWindow || event->error_code == BadDrawable)) {
        stopping = 1;
        return 0;
    }
    char message[256];
    XGetErrorText(display, event->error_code, message, sizeof(message));
    fprintf(stderr, "X11: %s (request=%u resource=0x%lx)\n",
            message, event->request_code, event->resourceid);
    x_error = 1;
    stopping = 1;
    return 0;
}
static double random_unit(void) {
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return (double)random_state / 4294967296.0;
}
/* Slots at or above GLYPH_COUNT are live glyphs; they move at the approved
   originals' median speed and trail. */
static double glyph_speed(int glyph) { return glyph < GLYPH_COUNT ? GLYPHS[glyph].speed : live_speed; }
static int glyph_trail(int glyph) { return glyph < GLYPH_COUNT ? GLYPHS[glyph].trail : live_trail; }
static const GlyphCommand *glyph_program(int glyph, int *count) {
    if (glyph >= GLYPH_COUNT) {
        *count = live[glyph - GLYPH_COUNT].count;
        return live[glyph - GLYPH_COUNT].commands;
    }
    *count = GLYPHS[glyph].count;
    return &GLYPH_COMMANDS[GLYPHS[glyph].offset];
}
static int approved_in_pool(void) {
    return live_count < LIVE_POOL - GLYPH_ORIGINAL_COUNT ? GLYPH_ORIGINAL_COUNT : LIVE_POOL - live_count;
}
static uint32_t original_pool(void) { return (uint32_t)(live_count + approved_in_pool()); }
/* The newest live glyphs first, then the approved originals that remain. */
static int original_glyph(uint32_t index) {
    int approved = approved_in_pool();
    index %= original_pool();
    if (index < (uint32_t)live_count) return GLYPH_COUNT + live_order[index];
    return GLYPH_ORIGINAL_OFFSET + GLYPH_ORIGINAL_COUNT - approved + (int)(index - (uint32_t)live_count);
}
static int random_glyph(void) {
    return random_unit() < original_mix
        ? original_glyph((uint32_t)(random_unit() * original_pool()))
        : (int)(random_unit() * GLYPH_REFERENCE_COUNT);
}
static uint32_t mix_bits(uint32_t value) {
    value ^= value >> 16;
    value *= 0x7feb352du;
    value ^= value >> 15;
    value *= 0x846ca68bu;
    return value ^ (value >> 16);
}
static int cell_glyph(const Column *column, int tail) {
    /* Decide the family first: a larger original catalog must not increase
       its selection probability. A stable cell seed keeps redraws identical. */
    uint32_t value = mix_bits(column->seed + (uint32_t)(column->phase - tail * 7));
    uint32_t index = mix_bits(value ^ 0xa511e9b3u);
    return (double)value / 4294967296.0 < original_mix
        ? original_glyph(index)
        : (int)(index % GLYPH_REFERENCE_COUNT);
}
static double monotonic_seconds(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (double)now.tv_sec + (double)now.tv_nsec / 1e9;
}

static void draw_program(cairo_t *cr, int glyph, double ox, double oy,
                         double unit,
                         double red, double green, double blue, double alpha) {
    int count;
    const GlyphCommand *program = glyph_program(glyph, &count);
    cairo_set_source_rgba(cr, red / 255, green / 255, blue / 255, alpha);
    cairo_set_fill_rule(cr, CAIRO_FILL_RULE_WINDING);
    cairo_new_path(cr);
    for (int i = 0; i < count; i++) {
        const GlyphCommand *command = &program[i];
        const double *v = command->values;
        switch (command->kind) {
            case 0: cairo_move_to(cr, ox + v[0] * unit, oy + v[1] * unit); break;
            case 1: cairo_line_to(cr, ox + v[0] * unit, oy + v[1] * unit); break;
            case 2: cairo_curve_to(cr, ox + v[0] * unit, oy + v[1] * unit,
                                   ox + v[2] * unit, oy + v[3] * unit,
                                   ox + v[4] * unit, oy + v[5] * unit); break;
            case 3: cairo_close_path(cr); break;
        }
    }
    /* One compound fill preserves holes, overlapping contours, and curves. */
    cairo_fill(cr);
}

static cairo_surface_t *make_sprite(int glyph, double cell, double pad,
                                    double level, int head) {
    int size = (int)ceil(cell + 2 * pad);
    cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, size, size);
    cairo_t *cr = cairo_create(surface);
    double unit = cell / GLYPH_CANVAS_H;
    double ox = pad + (cell - GLYPH_CANVAS_W * unit) / 2;
    /* A small cached halo surrounds the original contour; the opaque core is
       never stroked or enlarged. This is Cairo glow, not the REGL bloom pass. */
    for (int pass = 0; pass < 2; pass++) {
        double radius = (pass ? .75 : 1.5) * fmax(.5, cell / 24);
        for (int direction = 0; direction < 8; direction++) {
            double angle = direction * 6.283185307179586 / 8;
            draw_program(cr, glyph, ox + cos(angle) * radius, pad + sin(angle) * radius,
                         unit, 25.5, 229.5, 83.3, (head ? .025 : .012) * level);
        }
    }
    /* Body: HSL(137deg, 80%, 50%). Head: the web explorer's #A2FFD8 mint. */
    draw_program(cr, glyph, ox, pad, unit,
                 (head ? 162 : 25.5) * level,
                 (head ? 255 : 229.5) * level,
                 (head ? 216 : 83.3) * level, 1);
    cairo_destroy(cr);
    return surface;
}

static void free_scene(Scene *scene) {
    for (int l = 0; l < LAYER_COUNT; l++) {
        Layer *layer = &scene->layers[l];
        for (int g = 0; g < GLYPH_SLOTS; g++) {
            if (layer->trail[g]) cairo_surface_destroy(layer->trail[g]);
            if (layer->head[g]) cairo_surface_destroy(layer->head[g]);
        }
        free(layer->columns);
    }
    if (scene->image) cairo_surface_destroy(scene->image);
    memset(scene, 0, sizeof(*scene));
}

static int layer_sprites(Layer *layer, int g) {
    layer->trail[g] = make_sprite(g, layer->cell, layer->pad, layer->level, 0);
    layer->head[g] = make_sprite(g, layer->cell, layer->pad, layer->level, 1);
    return cairo_surface_status(layer->trail[g]) == CAIRO_STATUS_SUCCESS &&
           cairo_surface_status(layer->head[g]) == CAIRO_STATUS_SUCCESS;
}

static int build_scene(Scene *scene, int width, int height) {
    static const double cells[] = {11, 20, 36};
    static const double spacing[] = {1.2, 1.35, 2.5};
    static const double speeds[] = {.62, .8, 1};
    static const double levels[] = {.48, .75, 1};
    if (width < 1 || height < 1 || width > MAX_SIZE || height > MAX_SIZE) {
        fprintf(stderr, "Window dimensions must be between 1 and %d\n", MAX_SIZE);
        return 0;
    }
    free_scene(scene);
    scene->width = width;
    scene->height = height;
    scene->image = cairo_image_surface_create(CAIRO_FORMAT_RGB24, width, height);
    if (cairo_surface_status(scene->image) != CAIRO_STATUS_SUCCESS) return 0;
    double scale = fmax(.5, fmin(1.5, height / 720.0));
    for (int l = 0; l < LAYER_COUNT; l++) {
        Layer *layer = &scene->layers[l];
        layer->cell = cells[l] * scale;
        layer->pad = ceil(layer->cell * .5);
        layer->step = fmax(3, layer->cell * 1.04);
        layer->speed = speeds[l];
        layer->level = levels[l];
        double lane = layer->cell * spacing[l];
        layer->count = (int)ceil(width / lane) + 1;
        layer->columns = calloc((size_t)layer->count, sizeof(Column));
        if (!layer->columns) return 0;
        for (int g = 0; g < GLYPH_COUNT; g++)
            if (!layer_sprites(layer, g)) return 0;
        for (int s = 0; s < LIVE_MAX; s++)
            if (live[s].count && !layer_sprites(layer, GLYPH_COUNT + s)) return 0;
        for (int i = 0; i < layer->count; i++) {
            Column *col = &layer->columns[i];
            col->x = i * lane + random_unit() * 7 - 3;
            col->glyph = random_glyph();
            col->phase = random_glyph();
            col->seed = (uint32_t)(random_unit() * 4294967296.0);
            col->y = random_unit() * (height + glyph_trail(col->glyph) * layer->step);
            col->rate = glyph_speed(col->glyph) * 5.6 * layer->speed;
            col->accumulator = random_unit();
        }
    }
    return 1;
}

static void render_scene(Scene *scene, double dt) {
    cairo_t *cr = cairo_create(scene->image);
    cairo_set_source_rgb(cr, 0, 0, 0);
    cairo_paint(cr);
    for (int l = 0; l < LAYER_COUNT; l++) {
        Layer *layer = &scene->layers[l];
        for (int i = 0; i < layer->count; i++) {
            Column *col = &layer->columns[i];
            col->accumulator += dt * col->rate * (col->burst > 0 ? 1.9 : 1);
            if (col->burst > 0) col->burst -= dt;
            while (col->accumulator >= 1) {
                col->accumulator -= 1;
                col->y += layer->step;
                col->phase = (col->phase + 7) % 1000000;
                double past = col->y - glyph_trail(col->glyph) * layer->step * 1.15;
                if (past > scene->height && random_unit() < .6) {
                    col->y = -layer->step * (int)(random_unit() * 7);
                    col->glyph = random_glyph();
                    col->rate = glyph_speed(col->glyph) * 5.6 * layer->speed;
                    if (random_unit() < .06) col->burst = 1.6;
                }
            }
            int length = (int)lround(glyph_trail(col->glyph) * 1.15);
            for (int tail = length; tail >= 0; tail--) {
                double y = col->y - tail * layer->step;
                if (y < -layer->step || y > scene->height + layer->step) continue;
                int glyph = cell_glyph(col, tail);
                if (glyph >= GLYPH_ORIGINAL_OFFSET) scene->original_cells++;
                else scene->reference_cells++;
                if (glyph == GLYPH_BLANK_INDEX) scene->blank_cells++;
                if (glyph >= GLYPH_COUNT) scene->live_cells++;
                double near = 1 - (double)tail / length;
                double alpha = tail == 0 ? 1 : (.25 + .75 * sqrt(near)) * (.75 + (glyph % 5) * .0625);
                cairo_set_source_surface(cr, tail == 0 ? layer->head[glyph] : layer->trail[glyph],
                                         col->x - layer->pad, y - layer->pad);
                cairo_paint_with_alpha(cr, alpha);
            }
        }
    }
    cairo_destroy(cr);
}

/* ---------- Live feed ---------- */
static int compare_numbers(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}
static double median(double *values, int count) {
    qsort(values, (size_t)count, sizeof(double), compare_numbers);
    return count % 2 ? values[count / 2] : (values[count / 2 - 1] + values[count / 2]) / 2;
}
static void live_motion(void) {
    double speeds[GLYPH_ORIGINAL_COUNT], trails[GLYPH_ORIGINAL_COUNT];
    for (int i = 0; i < GLYPH_ORIGINAL_COUNT; i++) {
        speeds[i] = GLYPHS[GLYPH_ORIGINAL_OFFSET + i].speed;
        trails[i] = GLYPHS[GLYPH_ORIGINAL_OFFSET + i].trail;
    }
    live_speed = median(speeds, GLYPH_ORIGINAL_COUNT);
    live_trail = (int)floor(median(trails, GLYPH_ORIGINAL_COUNT) + .5);
}

/* The per-user feed folder, the same one the generator writes by default. */
static int live_default_folder(char *out, size_t size) {
    const char *override = getenv("NOUMENON_LIVE_FEED"), *home = getenv("HOME");
    const char *data = getenv("XDG_DATA_HOME");
    int written;
    if (override && *override) {
        if (override[0] == '~' && (override[1] == '/' || !override[1]) && home && *home)
            written = snprintf(out, size, "%s%s", home, override + 1);
        else written = snprintf(out, size, "%s", override);
    } else if (data && *data) written = snprintf(out, size, "%s/noumenon/live-feed", data);
    else if (home && *home) written = snprintf(out, size, "%s/.local/share/noumenon/live-feed", home);
    else return 0;
    return written > 0 && (size_t)written < size;
}

/* Feed names sort in arrival order; anything else in the folder is ignored. */
static int live_name(const char *name) {
    size_t length = strlen(name);
    if (length < 5 || length >= LIVE_NAME || name[0] == '.' || strcmp(name + length - 4, ".svg")) return 0;
    for (size_t i = 0; i < length; i++) {
        char c = name[i];
        if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
              c == '-' || c == '_' || c == '.')) return 0;
    }
    return 1;
}

static char *live_read(const char *path) {
    /* Regular files only: never follow a link or wait on a pipe. */
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return NULL;
    struct stat info;
    char *text = NULL;
    if (!fstat(fd, &info) && S_ISREG(info.st_mode) && info.st_size > 0 &&
        info.st_size <= LIVE_FILE_BYTES && (text = malloc((size_t)info.st_size + 1))) {
        size_t total = 0;
        while (total < (size_t)info.st_size) {
            ssize_t got = read(fd, text + total, (size_t)info.st_size - total);
            if (got < 0 && errno == EINTR) continue;
            if (got <= 0) break;
            total += (size_t)got;
        }
        if (total == (size_t)info.st_size) text[total] = 0;
        else { free(text); text = NULL; }
    }
    close(fd);
    return text;
}

static int live_append(GlyphCommand **commands, int *count, int *capacity, int kind, double x, double y) {
    if (*count >= LIVE_COMMANDS) return 0;
    if (*count == *capacity) {
        int next = *capacity ? *capacity * 2 : 64;
        GlyphCommand *grown = realloc(*commands, (size_t)next * sizeof(GlyphCommand));
        if (!grown) return 0;
        *commands = grown;
        *capacity = next;
    }
    GlyphCommand *command = &(*commands)[(*count)++];
    memset(command, 0, sizeof(*command));
    command->kind = kind;
    command->values[0] = x;
    command->values[1] = y;
    return 1;
}

/* The generator's format: 100-unit SVGs whose black nonzero paths are closed
   polygons in absolute M, L and Z commands, every point inside the canvas. */
static int live_parse(const char *text, GlyphCommand **out, int *out_count) {
    GlyphCommand *commands = NULL;
    int count = 0, capacity = 0, contours = 0;
    if (strncmp(text, "<svg", 4) || strstr(text, "<!") || strstr(text, "<?") ||
        !strstr(text, " viewBox=\"0 0 100 100\"") || strstr(text, "evenodd")) return 0;
    for (const char *cursor = text; (cursor = strstr(cursor, "<path")); ) {
        const char *end = strchr(cursor, '>'), *data = strstr(cursor, " d=\"");
        if (!end || !data || data > end) goto fail;
        data += 4;
        const char *stop = strchr(data, '"');
        if (!stop || stop > end) goto fail;
        int open_contour = 0, points = 0, pending = 0;
        double pair[2];
        char command = 0;
        for (const char *p = data; p < stop; ) {
            if (*p == ' ' || *p == ',' || *p == '\t' || *p == '\n' || *p == '\r') { p++; continue; }
            if (*p == 'M' || *p == 'L' || *p == 'Z') {
                if (pending) goto fail;  /* a coordinate needs both of its numbers */
                if (*p == 'Z') {
                    if (!open_contour || points < 3 ||
                        !live_append(&commands, &count, &capacity, 3, 0, 0)) goto fail;
                    open_contour = 0; points = 0; command = 0; contours++;
                } else command = *p;
                p++;
                continue;
            }
            /* A number is a whole run of number characters, so no hexadecimal
               or two numbers run together. */
            size_t span = strspn(p, "0123456789.+-eE");
            char *after;
            double value = span ? strtod(p, &after) : 0;
            if (!span || after != p + span || !isfinite(value) || value < 0 || value > 100) goto fail;
            p = after;
            pair[pending++] = value;
            if (pending < 2) continue;
            pending = 0;
            if (command == 'M' && !open_contour) {
                if (!live_append(&commands, &count, &capacity, 0, pair[0], pair[1])) goto fail;
                open_contour = 1; points = 1; command = 'L';
            } else if (command == 'L' && open_contour) {
                if (!live_append(&commands, &count, &capacity, 1, pair[0], pair[1])) goto fail;
                points++;
            } else goto fail;
        }
        if (pending || open_contour) goto fail;
        cursor = end;
    }
    if (!contours) goto fail;
    *out = commands;
    *out_count = count;
    return 1;
fail:
    free(commands);
    return 0;
}

static void live_release(Scene *scene, int slot) {
    if (scene) {
        for (int l = 0; l < LAYER_COUNT; l++) {
            Layer *layer = &scene->layers[l];
            int g = GLYPH_COUNT + slot;
            if (layer->trail[g]) cairo_surface_destroy(layer->trail[g]);
            if (layer->head[g]) cairo_surface_destroy(layer->head[g]);
            layer->trail[g] = layer->head[g] = NULL;
        }
    }
    free(live[slot].commands);
    memset(&live[slot], 0, sizeof(live[slot]));
}

static int compare_names(const void *a, const void *b) {
    return strcmp(((const LiveName *)b)->name, ((const LiveName *)a)->name);
}
static int compare_slots(const void *a, const void *b) {
    return strcmp(live[*(const int *)b].name, live[*(const int *)a].name);
}

/* Bring the live set up to date with the newest files in the feed. A glyph
   is read once, while its file stays among the newest; a file that fails
   validation is skipped. Returns 1 when the set changed. */
static int live_scan(Scene *scene) {
    DIR *dir = opendir(live_folder);
    if (!dir) return 0;
    LiveName *names = NULL;
    size_t found = 0, capacity = 0;
    for (struct dirent *entry; (entry = readdir(dir)) && found < LIVE_LISTED; ) {
        if (!live_name(entry->d_name)) continue;
        if (found == capacity) {
            size_t next = capacity ? capacity * 2 : 64;
            LiveName *grown = realloc(names, next * sizeof(LiveName));
            if (!grown) break;
            names = grown;
            capacity = next;
        }
        snprintf(names[found++].name, LIVE_NAME, "%s", entry->d_name);
    }
    closedir(dir);
    if (found) qsort(names, found, sizeof(LiveName), compare_names);
    size_t window = found < LIVE_MAX ? found : LIVE_MAX;
    int changed = 0;
    for (int s = 0; s < LIVE_MAX; s++) {
        if (!live[s].used) continue;
        int kept = 0;
        for (size_t i = 0; i < window && !kept; i++) kept = !strcmp(live[s].name, names[i].name);
        if (!kept) { live_release(scene, s); changed = 1; }
    }
    for (size_t i = 0; i < window; i++) {
        int known = 0, slot = -1;
        for (int s = 0; s < LIVE_MAX && !known; s++) {
            if (live[s].used) known = !strcmp(live[s].name, names[i].name);
            else if (slot < 0) slot = s;
        }
        if (known || slot < 0) continue;
        LiveGlyph *glyph = &live[slot];
        glyph->used = 1;
        snprintf(glyph->name, LIVE_NAME, "%s", names[i].name);
        char path[LIVE_PATH + LIVE_NAME + 2];
        snprintf(path, sizeof(path), "%s/%s", live_folder, glyph->name);
        char *text = live_read(path);
        if (text && live_parse(text, &glyph->commands, &glyph->count) && scene) {
            for (int l = 0; l < LAYER_COUNT; l++) {
                if (!layer_sprites(&scene->layers[l], GLYPH_COUNT + slot)) {
                    live_release(scene, slot);
                    glyph->used = 1;  /* keep the name so it is not read again */
                    snprintf(glyph->name, LIVE_NAME, "%s", names[i].name);
                    break;
                }
            }
        }
        free(text);
        changed = 1;
    }
    free(names);
    live_files = (int)found;
    live_considered = (int)window;
    live_count = 0;
    for (int s = 0; s < LIVE_MAX; s++)
        if (live[s].count) live_order[live_count++] = s;
    qsort(live_order, (size_t)live_count, sizeof(int), compare_slots);
    return changed;
}

/* A JSON account of the feed, for tests and for checking a feed folder. */
static void print_live_report(void) {
    int rejected[LIVE_MAX], count = 0;
    for (int s = 0; s < LIVE_MAX; s++)
        if (live[s].used && !live[s].count) rejected[count++] = s;
    qsort(rejected, (size_t)count, sizeof(int), compare_slots);
    printf("{\"version\":\"native-live-feed-v1\",\"files\":%d,\"considered\":%d,\"live\":%d,"
           "\"approved_in_pool\":%d,\"pool\":%u,\"speed\":%.6f,\"trail\":%d,\"rejected\":[",
           live_files, live_considered, live_count, approved_in_pool(), original_pool(),
           live_speed, live_trail);
    for (int i = 0; i < count; i++) printf("%s\"%s\"", i ? "," : "", live[rejected[i]].name);
    printf("],\"glyphs\":[");
    for (int i = 0; i < live_count; i++)
        printf("%s{\"name\":\"%s\",\"commands\":%d}", i ? "," : "",
               live[live_order[i]].name, live[live_order[i]].count);
    printf("]}\n");
}

/* Live glyphs newest first, drawn like the catalog sheet: 16 by 16 tiles. */
static int write_live_sheet(const char *path) {
    enum { TILE = 128, COLUMNS = 16, MARGIN = 4 };
    cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_RGB24, COLUMNS * TILE,
                                                         LIVE_MAX / COLUMNS * TILE);
    cairo_t *cr = cairo_create(surface);
    cairo_set_source_rgb(cr, 1, 1, 1);
    cairo_paint(cr);
    for (int i = 0; i < live_count; i++)
        draw_program(cr, GLYPH_COUNT + live_order[i], (i % COLUMNS) * TILE + MARGIN,
                     (i / COLUMNS) * TILE + MARGIN, (double)(TILE - 2 * MARGIN) / GLYPH_CANVAS_H,
                     0, 0, 0, 1);
    cairo_status_t status = cairo_status(cr);
    if (status == CAIRO_STATUS_SUCCESS) status = cairo_surface_write_to_png(surface, path);
    cairo_destroy(cr);
    cairo_surface_destroy(surface);
    if (status != CAIRO_STATUS_SUCCESS) {
        fprintf(stderr, "Live sheet: %s\n", cairo_status_to_string(status));
        return 1;
    }
    return 0;
}

static int number(const char *text, unsigned long limit, unsigned long *value) {
    char *end;
    errno = 0;
    if (!text || !*text || *text == '-') return 0;
    unsigned long result = strtoul(text, &end, 0);
    if (errno || *end || result > limit) return 0;
    *value = result;
    return 1;
}

static void print_catalog(void) {
    printf("{\"version\":\"native-mixed-svg-v1\",\"catalog_sha256\":\"%s\","
           "\"reference_sha256\":\"%s\",\"original_sha256\":\"%s\","
           "\"glyph_count\":%d,\"reference_count\":%d,\"reference_visible_count\":%d,"
           "\"original_count\":%d,\"original_offset\":%d,\"blank_index\":%d,"
           "\"canvas\":[%d,%d],\"fill_rule\":\"%s\",\"default_original_mix\":%.1f}\n",
           GLYPH_CATALOG_SHA256, GLYPH_REFERENCE_SHA256, GLYPH_ORIGINAL_SHA256,
           GLYPH_COUNT, GLYPH_REFERENCE_COUNT, GLYPH_REFERENCE_VISIBLE_COUNT,
           GLYPH_ORIGINAL_COUNT, GLYPH_ORIGINAL_OFFSET, GLYPH_BLANK_INDEX,
           GLYPH_CANVAS_W, GLYPH_CANVAS_H, GLYPH_FILL_RULE, GLYPH_ORIGINAL_SHARE);
}

static int write_glyph_sheet(const char *path) {
    enum { TILE = 128, COLUMNS = 16, MARGIN = 4 };
    int rows = (GLYPH_COUNT + COLUMNS - 1) / COLUMNS;
    cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_RGB24,
                                                         COLUMNS * TILE, rows * TILE);
    cairo_t *cr = cairo_create(surface);
    cairo_set_source_rgb(cr, 1, 1, 1);
    cairo_paint(cr);
    for (int glyph = 0; glyph < GLYPH_COUNT; glyph++) {
        draw_program(cr, glyph, (glyph % COLUMNS) * TILE + MARGIN,
                     (glyph / COLUMNS) * TILE + MARGIN,
                     (double)(TILE - 2 * MARGIN) / GLYPH_CANVAS_H, 0, 0, 0, 1);
    }
    cairo_status_t status = cairo_status(cr);
    if (status == CAIRO_STATUS_SUCCESS) status = cairo_surface_write_to_png(surface, path);
    cairo_destroy(cr);
    cairo_surface_destroy(surface);
    if (status != CAIRO_STATUS_SUCCESS) {
        fprintf(stderr, "Glyph sheet: %s\n", cairo_status_to_string(status));
        return 1;
    }
    print_catalog();
    return 0;
}

static void usage(FILE *stream) {
    fprintf(stream,
        "Noumenon — %d reference slots + %d original SVGs, native X11\n"
        "Usage: noumenon [options]\n"
        "  --window                 Resizable preview window (default)\n"
        "  --fullscreen             Fullscreen standalone window\n"
        "  -root                    Paint root/XScreenSaver window\n"
        "  -window-id ID            Paint an existing X11 window\n"
        "  -display DISPLAY         Select an X server\n"
        "  --width N --height N     Preview size (default 960x640)\n"
        "  --frames N --seed N      Bounded deterministic validation run\n"
        "  --snapshot FILE.png      Save final frame (requires --frames)\n"
        "  --mix FRACTION           Original glyph share, 0 to 1 (default 0.1)\n"
        "  --glyph-sheet FILE.png   Write all filled contours without X11\n"
        "  --live-feed DIR          Read live glyphs from DIR while running (default:\n"
        "                           $NOUMENON_LIVE_FEED, else $XDG_DATA_HOME/noumenon/live-feed)\n"
        "  --no-live                Show only the built-in catalog\n"
        "  --live-report DIR        Describe the live glyphs in DIR as JSON without X11\n"
        "  --live-sheet FILE.png    With --live-report, also draw those glyphs\n"
        "  --catalog | --license    Catalog hashes or included MIT notices\n"
        "  --help | --version       Print information and exit\n"
        "XSCREENSAVER_WINDOW is honored unless --window is explicit.\n"
        "Bounded --frames runs read live glyphs only from an explicit --live-feed.\n"
        "Escape closes standalone preview. SIGTERM exits cleanly.\n",
        GLYPH_REFERENCE_COUNT, GLYPH_ORIGINAL_COUNT);
}

int main(int argc, char **argv) {
    int width = 960, height = 640, root_mode = 0, fullscreen = 0, explicit_window = 0, no_live = 0;
    unsigned long window_id = 0, frames_limit = 0;
    const char *display_name = NULL, *snapshot = NULL, *glyph_sheet = NULL;
    const char *live_feed = NULL, *live_report = NULL, *live_sheet = NULL;
    random_state = (uint32_t)time(NULL) ^ (uint32_t)clock();
    if (!random_state) random_state = 1;
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!strcmp(arg, "--help") || !strcmp(arg, "-help")) { usage(stdout); return 0; }
        if (!strcmp(arg, "--version")) {
            printf("Noumenon X11; glyphs=%d reference=%d original=%d catalog=%s\n",
                   GLYPH_COUNT, GLYPH_REFERENCE_COUNT, GLYPH_ORIGINAL_COUNT, GLYPH_CATALOG_SHA256);
            return 0;
        }
        if (!strcmp(arg, "--catalog")) { print_catalog(); return 0; }
        if (!strcmp(arg, "--license")) { puts(GLYPH_LICENSE_NOTICE); return 0; }
        if (!strcmp(arg, "-root") || !strcmp(arg, "--root")) { root_mode = 1; continue; }
        if (!strcmp(arg, "--window") || !strcmp(arg, "-window")) { explicit_window = 1; continue; }
        if (!strcmp(arg, "--fullscreen")) { fullscreen = 1; explicit_window = 1; continue; }
        if (!strcmp(arg, "--no-live")) { no_live = 1; continue; }
        if (i + 1 >= argc) { fprintf(stderr, "Missing value for %s\n", arg); return 2; }
        const char *value = argv[++i];
        unsigned long parsed;
        if (!strcmp(arg, "-display") || !strcmp(arg, "--display")) display_name = value;
        else if (!strcmp(arg, "--snapshot")) snapshot = value;
        else if (!strcmp(arg, "--glyph-sheet")) glyph_sheet = value;
        else if (!strcmp(arg, "--live-sheet")) live_sheet = value;
        else if (!strcmp(arg, "--live-feed") || !strcmp(arg, "--live-report")) {
            if (!*value || strlen(value) >= LIVE_PATH) goto invalid;
            if (!strcmp(arg, "--live-feed")) live_feed = value; else live_report = value;
        }
        else if (!strcmp(arg, "--mix")) {
            char *end;
            errno = 0;
            double result = strtod(value, &end);
            if (errno || end == value || *end || !isfinite(result) || result < 0 || result > 1) goto invalid;
            original_mix = result;
        }
        else if (!strcmp(arg, "-window-id") || !strcmp(arg, "--window-id")) {
            if (!number(value, ULONG_MAX, &window_id) || !window_id) goto invalid;
        } else if (!strcmp(arg, "--width") || !strcmp(arg, "--height")) {
            if (!number(value, MAX_SIZE, &parsed) || !parsed) goto invalid;
            if (!strcmp(arg, "--width")) width = (int)parsed; else height = (int)parsed;
        } else if (!strcmp(arg, "--frames")) {
            if (!number(value, 1000000, &frames_limit) || !frames_limit) goto invalid;
        } else if (!strcmp(arg, "--seed")) {
            if (!number(value, UINT32_MAX, &parsed)) goto invalid;
            random_state = parsed ? (uint32_t)parsed : 1;
        } else { fprintf(stderr, "Unknown option: %s\n", arg); return 2; }
        continue;
invalid:
        fprintf(stderr, "Invalid value for %s: %s\n", arg, value);
        return 2;
    }
    live_motion();
    if (live_report) {
        snprintf(live_folder, sizeof(live_folder), "%s", live_report);
        live_scan(NULL);
        int status = live_sheet ? write_live_sheet(live_sheet) : 0;
        print_live_report();
        for (int s = 0; s < LIVE_MAX; s++) live_release(NULL, s);
        return status;
    }
    if (live_sheet) { fprintf(stderr, "--live-sheet requires --live-report\n"); return 2; }
    if (glyph_sheet) return write_glyph_sheet(glyph_sheet);
    /* Bounded validation runs stay deterministic: they read only a named feed. */
    int live_enabled = !no_live && (live_feed || !frames_limit);
    if (live_enabled && live_feed) snprintf(live_folder, sizeof(live_folder), "%s", live_feed);
    else if (live_enabled) live_enabled = live_default_folder(live_folder, sizeof(live_folder));
    if (live_enabled) live_scan(NULL);
    if (snapshot && !frames_limit) { fprintf(stderr, "--snapshot requires --frames\n"); return 2; }
    if (!window_id && !explicit_window) {
        const char *parent = getenv("XSCREENSAVER_WINDOW");
        if (parent && (!number(parent, ULONG_MAX, &window_id) || !window_id)) {
            fprintf(stderr, "Invalid XSCREENSAVER_WINDOW\n"); return 2;
        }
    }
    Display *display = XOpenDisplay(display_name);
    if (!display) { fprintf(stderr, "Cannot open X11 display; set DISPLAY or use -display.\n"); return 1; }
    XSetErrorHandler(handle_x_error);
    int screen = DefaultScreen(display), owned = !window_id && !root_mode;
    Window window = window_id ? (Window)window_id : RootWindow(display, screen);
    Atom wm_delete = XInternAtom(display, "WM_DELETE_WINDOW", False);
    if (owned) {
        if (fullscreen) { width = DisplayWidth(display, screen); height = DisplayHeight(display, screen); }
        window = XCreateSimpleWindow(display, RootWindow(display, screen), 0, 0,
                                     (unsigned)width, (unsigned)height, 0, 0, 0);
        if (fullscreen) {
            XSetWindowAttributes attributes;
            attributes.override_redirect = True;
            XChangeWindowAttributes(display, window, CWOverrideRedirect, &attributes);
        }
        XStoreName(display, window, "Noumenon");
        XSetWMProtocols(display, window, &wm_delete, 1);
        XMapWindow(display, window);
        if (fullscreen) {
            XSync(display, False);
            XSetInputFocus(display, window, RevertToParent, CurrentTime);
        }
    }
    XWindowAttributes attributes;
    if (!XGetWindowAttributes(display, window, &attributes) || x_error) {
        fprintf(stderr, "Cannot inspect target window\n"); XCloseDisplay(display); return 1;
    }
    width = attributes.width; height = attributes.height;
    XSelectInput(display, window, ExposureMask | StructureNotifyMask | (owned ? KeyPressMask : 0));
    /* Cairo owns only our offscreen pixmap. A screensaver manager can destroy
       its window at any point; that must not invalidate Cairo's resource
       construction or teardown. Only the final CopyArea touches the window. */
    Pixmap backbuffer = XCreatePixmap(display, attributes.root, (unsigned)width,
                                      (unsigned)height, (unsigned)attributes.depth);
    GC blit_gc = XCreateGC(display, backbuffer, 0, NULL);
    cairo_surface_t *surface = cairo_xlib_surface_create(display, backbuffer,
                                                        attributes.visual, width, height);
    Scene scene = {0};
    int result = 0;
    if (cairo_surface_status(surface) != CAIRO_STATUS_SUCCESS || !build_scene(&scene, width, height)) {
        fprintf(stderr, "Cannot allocate rendering surfaces\n"); result = 1; goto cleanup;
    }
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_handler = stop_signal;
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);
    unsigned long frames = 0;
    double previous = monotonic_seconds(), next_scan = previous + LIVE_SCAN_SECONDS;
    live_window = window;
    printf("window=0x%lx mode=%s glyphs=%d live=%d\n", window, owned ? "preview" : "embedded",
           GLYPH_COUNT, live_count);
    fflush(stdout);
    while (!stopping) {
        double started = monotonic_seconds();
        while (XPending(display)) {
            XEvent event;
            XNextEvent(display, &event);
            if (event.type == DestroyNotify) { owned = 0; stopping = 1; }
            if (
                (event.type == ClientMessage && (Atom)event.xclient.data.l[0] == wm_delete) ||
                (event.type == KeyPress && XLookupKeysym(&event.xkey, 0) == XK_Escape)) stopping = 1;
            if (event.type == ConfigureNotify &&
                (event.xconfigure.width != scene.width || event.xconfigure.height != scene.height)) {
                if (!build_scene(&scene, event.xconfigure.width, event.xconfigure.height)) { result = 1; stopping = 1; }
                if (!stopping) {
                    cairo_surface_destroy(surface);
                    XFreePixmap(display, backbuffer);
                    backbuffer = XCreatePixmap(display, attributes.root,
                                                (unsigned)scene.width, (unsigned)scene.height,
                                                (unsigned)attributes.depth);
                    surface = cairo_xlib_surface_create(display, backbuffer, attributes.visual,
                                                         scene.width, scene.height);
                    if (cairo_surface_status(surface) != CAIRO_STATUS_SUCCESS) {
                        result = 1; stopping = 1;
                    }
                }
            }
        }
        if (stopping) break;
        if (live_enabled && !frames_limit && started >= next_scan) {
            live_scan(&scene);
            next_scan = started + LIVE_SCAN_SECONDS;
        }
        double dt = frames_limit ? 1.0 / FPS : fmax(0, fmin(.05, started - previous));
        previous = started;
        render_scene(&scene, frames == 0 ? 0 : dt);
        cairo_t *cr = cairo_create(surface);
        cairo_set_source_surface(cr, scene.image, 0, 0);
        cairo_paint(cr);
        if (cairo_status(cr) != CAIRO_STATUS_SUCCESS) { result = 1; stopping = 1; }
        cairo_destroy(cr);
        cairo_surface_flush(surface);
        XCopyArea(display, backbuffer, window, blit_gc, 0, 0,
                  (unsigned)scene.width, (unsigned)scene.height, 0, 0);
        XSync(display, False);
        frames++;
        if (frames_limit && frames >= frames_limit) break;
        double remaining = 1.0 / FPS - (monotonic_seconds() - started);
        if (remaining > 0) {
            struct timespec delay = {0, (long)(remaining * 1e9)};
            nanosleep(&delay, NULL);
        }
    }
    if (snapshot && !x_error && frames) {
        cairo_status_t status = cairo_surface_write_to_png(scene.image, snapshot);
        if (status != CAIRO_STATUS_SUCCESS) { fprintf(stderr, "Snapshot: %s\n", cairo_status_to_string(status)); result = 1; }
    }
    printf("frames=%lu width=%d height=%d stopped=%d\n", frames, scene.width, scene.height, stopping ? 1 : 0);
    printf("selected_reference=%llu selected_original=%llu selected_blank=%llu mix=%.6f\n",
           (unsigned long long)scene.reference_cells, (unsigned long long)scene.original_cells,
           (unsigned long long)scene.blank_cells, original_mix);
    printf("live=%d selected_live=%llu\n", live_count, (unsigned long long)scene.live_cells);
cleanup:
    free_scene(&scene);
    for (int s = 0; s < LIVE_MAX; s++) live_release(NULL, s);
    cairo_surface_destroy(surface);
    XFreeGC(display, blit_gc);
    XFreePixmap(display, backbuffer);
    if (owned && !x_error) XDestroyWindow(display, window);
    XCloseDisplay(display);
    return x_error ? 1 : result;
}
