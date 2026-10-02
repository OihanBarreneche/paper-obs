/* Squares in a tan, two orientations: upright squares fill a Young diagram D in the right-angle
 * corner, plus stacks of any size pushed into the two acute corners (column stacks against the left leg and
 * the hypotenuse, row stacks against the bottom leg and the hypotenuse); squares turned by 45
 * degrees fill bands of width 1 along the hypotenuse, each band greedily, around the upright
 * squares. Wolk's records are all of this kind: his 34 is a 4 x 4 block and three bands, his 42 a
 * staircase, two bands and a stack of two squares at the apex.
 *
 * Tan units: right angle at the origin, legs along u and v, hypotenuse u + v = s. Band frame:
 * p = (u - v)/sqrt2 along the hypotenuse, q = (u + v)/sqrt2 across it. Band k is the strip
 * q in [l, l + 1] with l = s/sqrt2 - (k + 1); its squares are p-intervals [x, x + 1] inside
 * [-l, l] (the legs) that avoid every p where an upright square enters the open strip.
 *
 * Legs run over the grid a + c/sqrt2 (0 <= a <= 12, 0 <= c <= 18): every critical length of this
 * model lies on it. For each count n the program prints the smallest legs it reaches and how.
 *
 * Build: gcc -O2 -o tanlayers tanlayers.c -lm      Run: ./tanlayers [max_n]
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAXC 16
#define EPS 1e-9
#define MAXN 80

static const double R2 = 1.4142135623730951;
static double S;                 /* current legs */
static int H[MAXC + 2];          /* column heights of D, H[W] = 0 */
static int CS[2], RS[2];         /* stacks: columns 0-1 at the apex, rows 0-1 at the far corner */
static double best_s[MAXN + 1];
static char best_how[MAXN + 1][256];
static int cur_best;
static char cur_how[256];

typedef struct { double lo, hi; } Interval;

static int cmp_interval(const void *a, const void *b) {
    double d = ((const Interval *)a)->lo - ((const Interval *)b)->lo;
    return (d > 0) - (d < 0);
}

/* p-extent of a convex polygon (u, v vertices) inside the open strip l < q < l + 1. */
static int strip_extent(const double *u, const double *v, int m, double l, double *lo, double *hi) {
    double P[16], Q[16], P2[16], Q2[16];
    int k = m;
    for (int i = 0; i < m; i++) { P[i] = (u[i] - v[i]) / R2; Q[i] = (u[i] + v[i]) / R2; }
    for (int side = 0; side < 2; side++) {   /* clip q >= l, then q <= l + 1 */
        int k2 = 0;
        for (int i = 0; i < k; i++) {
            int j = (i + 1) % k;
            double fi = side == 0 ? Q[i] - l : l + 1 - Q[i];
            double fj = side == 0 ? Q[j] - l : l + 1 - Q[j];
            if (fi >= 0) { P2[k2] = P[i]; Q2[k2] = Q[i]; k2++; }
            if ((fi >= 0) != (fj >= 0)) {
                double t = fi / (fi - fj);
                P2[k2] = P[i] + t * (P[j] - P[i]); Q2[k2] = Q[i] + t * (Q[j] - Q[i]); k2++;
            }
        }
        memcpy(P, P2, sizeof(double) * k2); memcpy(Q, Q2, sizeof(double) * k2); k = k2;
        if (k == 0) return 0;
    }
    double a = 1e9, b = -1e9, qa = 1e9, qb = -1e9;
    for (int i = 0; i < k; i++) {
        if (P[i] < a) a = P[i];
        if (P[i] > b) b = P[i];
        if (Q[i] < qa) qa = Q[i];
        if (Q[i] > qb) qb = Q[i];
    }
    if (qb - qa < EPS || b - a < EPS) return 0;   /* only touches the strip */
    *lo = a; *hi = b;
    return 1;
}

static int band_count(double l, int W) {
    Interval bad[64];
    int nb = 0;
    /* D: the boundary path from (0, H0) by unit steps right and down to (W, 0). */
    double pu[2 * MAXC + 40], pv[2 * MAXC + 40];
    int np = 0;
    if (W > 0) {
        pu[np] = 0; pv[np] = H[0]; np++;
        for (int i = 0; i < W; i++) {
            pu[np] = i + 1; pv[np] = H[i]; np++;
            for (int h = H[i] - 1; h >= H[i + 1]; h--) { pu[np] = i + 1; pv[np] = h; np++; }
        }
        int inside = 0;
        double start = 0;
        for (int i = 0; i < np; i++) {
            double p = (pu[i] - pv[i]) / R2, q = (pu[i] + pv[i]) / R2;
            if (i == 0) {
                if (q > l + EPS) { inside = 1; start = p; }
                continue;
            }
            double p0 = (pu[i - 1] - pv[i - 1]) / R2, q0 = (pu[i - 1] + pv[i - 1]) / R2;
            if (!inside && q > l + EPS) {
                double t = (l - q0) / (q - q0);
                if (t < 0) t = 0;
                start = p0 + t * (p - p0); inside = 1;
            } else if (inside && q <= l + EPS) {
                double t = (q0 - l) / (q0 - q);
                if (t > 1) t = 1;
                bad[nb].lo = start; bad[nb].hi = p0 + t * (p - p0); nb++; inside = 0;
            }
        }
        if (inside) { bad[nb].lo = start; bad[nb].hi = (pu[np - 1] - pv[np - 1]) / R2; nb++; }
    }
    /* Stacks. */
    for (int i = 0; i < 2; i++) {
        if (CS[i] > 0) {
            double top = S - i - 1, bottom = top - CS[i];
            double u[4] = {i, i + 1, i + 1, i}, v[4] = {bottom, bottom, top, top};
            double lo, hi;
            if (strip_extent(u, v, 4, l, &lo, &hi)) { bad[nb].lo = lo; bad[nb].hi = hi; nb++; }
        }
        if (RS[i] > 0) {
            double right = S - i - 1, left = right - RS[i];
            double u[4] = {left, right, right, left}, v[4] = {i, i, i + 1, i + 1};
            double lo, hi;
            if (strip_extent(u, v, 4, l, &lo, &hi)) { bad[nb].lo = lo; bad[nb].hi = hi; nb++; }
        }
    }
    qsort(bad, nb, sizeof(Interval), cmp_interval);
    int count = 0;
    double x = -l;
    for (int i = 0; i < nb; i++) {
        if (bad[i].hi <= x) continue;
        if (bad[i].lo > x) count += (int)floor(fmin(bad[i].lo, l) - x + EPS);
        if (bad[i].hi > x) x = bad[i].hi;
        if (x >= l) break;
    }
    if (x < l) count += (int)floor(l - x + EPS);
    return count;
}

static void evaluate_stacks(int W);

/* Every stack size that clears D: column stacks up to the room above column i, row stacks up to
 * the room right of row j. */
static void evaluate(int W) {
    int room[2], wide[2];
    for (int i = 0; i < 2; i++) {
        room[i] = (int)floor(S - i - 1 - H[i] + EPS);
        int w = 0;
        while (w < W && H[w] > i) w++;
        wide[i] = (int)floor(S - i - 1 - w + EPS);
        if (room[i] < 0) room[i] = 0;
        if (wide[i] < 0) wide[i] = 0;
    }
    for (CS[0] = 0; CS[0] <= room[0]; CS[0]++) for (CS[1] = 0; CS[1] <= room[1]; CS[1]++)
    for (RS[0] = 0; RS[0] <= wide[0]; RS[0]++) for (RS[1] = 0; RS[1] <= wide[1]; RS[1]++)
        evaluate_stacks(W);
    CS[0] = CS[1] = RS[0] = RS[1] = 0;
}

static void evaluate_stacks(int W) {
    int area = 0;
    for (int i = 0; i < W; i++) area += H[i];
    /* Stacks must clear D (column i above H[i], row j right of row j's length) and each other. */
    for (int i = 0; i < 2; i++) {
        if (CS[i] && S - i - 1 - CS[i] < H[i] - EPS) return;
        int w = 0;
        while (w < W && H[w] > i) w++;
        if (RS[i] && S - i - 1 - RS[i] < w - EPS) return;
        for (int j = 0; j < 2; j++)
            if (CS[i] && RS[j] && i + 1 > S - j - 1 - RS[j] + EPS && j + 1 > S - i - 1 - CS[i] + EPS) return;
    }
    int count = area + CS[0] + CS[1] + RS[0] + RS[1];
    for (int k = 0;; k++) {
        double l = S / R2 - (k + 1);
        if (2 * l < 1 - EPS) break;
        count += band_count(l, W);
    }
    if (count > cur_best) {
        cur_best = count;
        int o = snprintf(cur_how, sizeof cur_how, "D=[");
        for (int i = 0; i < W; i++) o += snprintf(cur_how + o, sizeof cur_how - o, "%s%d", i ? "," : "", H[i]);
        snprintf(cur_how + o, sizeof cur_how - o, "] apex=%d,%d corner=%d,%d", CS[0], CS[1], RS[0], RS[1]);
    }
}

static void columns(int i, int limit) {
    /* Column i gets a height in [0, limit]; a zero height ends D. */
    H[i] = 0;
    evaluate(i);
    for (int h = 1; h <= limit; h++) {
        if (i + 1 + h > S + EPS) break;
        H[i] = h; H[i + 1] = 0;
        columns(i + 1, h);
    }
    H[i] = 0;
}

int main(int argc, char **argv) {
    int max_n = argc > 1 ? atoi(argv[1]) : 50;
    for (int n = 0; n <= MAXN; n++) best_s[n] = 1e9;
    for (int a = 0; a <= 12; a++) for (int c = 0; c <= 18; c++) {
        S = a + c / R2;
        if (S < 2 - EPS || S > 11.3) continue;
        cur_best = 0;
        memset(H, 0, sizeof H);
        columns(0, MAXC);
        for (int n = 1; n <= cur_best && n <= MAXN; n++)
            if (S < best_s[n] - EPS) {
                best_s[n] = S;
                snprintf(best_how[n], sizeof best_how[n], "%d + %d/sqrt2 holds %d: %s", a, c, cur_best, cur_how);
            }
    }
    /* The live page, read on 2026-10-01. */
    const double r = R2, live[51] = {0, 2, 2 * r, 3, 5 / r, 4, 4, 3 + r, 2 + 2 * r, 7 / r, 5, 4 + r, 4 * r,
        3 + 2 * r, 6, 6, 9 / r, 5 + r, 4 + 2 * r, 2 + 7 / r, 7, 7, 1 + 9 / r, 6 + r, 7 + 1 / r, 11 / r,
        5 + 2 * r, 8, 8, 2 + 9 / r, 7 + r, 6 * r, 1 + 11 / r, 6 + 2 * r, 4 + 7 / r, 9, 9, 5 + 3 * r, 8 + r,
        8 + r, 2 + 11 / r, 7 + 2 * r, 7 + 2 * r, 7 * r, 10, 10, 6 + 3 * r, 9 + r, 9 + r, 15 / r, 3 + 11 / r};
    for (int n = 1; n <= max_n && n <= 50; n++)
        printf("%2d  %9.5f  live %9.5f %s  %s\n", n, best_s[n], live[n],
               best_s[n] < live[n] - EPS ? "BEATS" : best_s[n] > live[n] + EPS ? "worse" : "  =  ", best_how[n]);
    return 0;
}
