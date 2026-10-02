/* domlayers.c with the V of Wolk: two dominoes leaning together, straddling an outer corner of
 * the upright diagram D that pokes into the band under band k (see the V code below). At each
 * leaf of the enumeration, every corner of D at a suitable depth may carry a V in each band; the
 * best subset of compatible V's is kept. Stacks are not combined with V's.
 *
 * Build: gcc -O2 -o domv domv.c -lm      Run: ./domv [stacks 0|1] [a c ...]
 */
#define _GNU_SOURCE
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAXW 20
#define MAXK 16
#define EPS 1e-9
#define MAXN 80

static const double R2 = 1.4142135623730951;
static double S;
static int K;                         /* levels with l >= 0.5 */
static double L[MAXK];
static int H[MAXW + 2];
/* Stack forbidden p-intervals per level, for the single strip (l, l+1) and the double (l, l+2). */
static double SB[MAXK][2][4][2];
static int NSB[MAXK][2];
static double rect[4][4];             /* stacks as u0, u1, v0, v1 */
static int nrect;
static int apex_kind, apex_n, corner_kind, corner_n, stack_count;
static int cur_best;
static int list_n, list_max, listed;   /* list mode: print structures with V's holding list_n */
static char cur_how[300];

/* p-extent of the rectangle [u0,u1] x [v0,v1] inside the open strip l < q < l + w. */
static int strip_extent(const double *r, double l, double w, double *lo, double *hi) {
    double u[4] = {r[0], r[1], r[1], r[0]}, v[4] = {r[2], r[2], r[3], r[3]};
    double P[12], Q[12], P2[12], Q2[12];
    int k = 4;
    for (int i = 0; i < 4; i++) { P[i] = (u[i] - v[i]) / R2; Q[i] = (u[i] + v[i]) / R2; }
    for (int side = 0; side < 2; side++) {
        int k2 = 0;
        for (int i = 0; i < k; i++) {
            int j = (i + 1) % k;
            double fi = side == 0 ? Q[i] - l : l + w - Q[i];
            double fj = side == 0 ? Q[j] - l : l + w - Q[j];
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
    if (qb - qa < EPS || b - a < EPS) return 0;
    *lo = a; *hi = b;
    return 1;
}

/* Dominoes in the free interval [a, b] of level k, minus the stack intervals: per piece of
 * length x, floor(x / 2) lying (kind 0) or floor(x) standing (kind 1). */
static int count_free(double a, double b, int k, int kind) {
    int n = 0;
    double x = a;
    for (int i = 0; i < NSB[k][kind]; i++) {
        double lo = SB[k][kind][i][0], hi = SB[k][kind][i][1];
        if (hi <= x || lo >= b) continue;
        if (lo > x) n += (int)floor((lo - x + EPS) / (kind == 0 ? 2.0 : 1.0));
        if (hi > x) x = hi;
    }
    if (b > x) n += (int)floor((b - x + EPS) / (kind == 0 ? 2.0 : 1.0));
    return n;
}

typedef struct { int blocked[MAXK]; double start[MAXK]; int lie[MAXK], stand[MAXK]; } Bands;

static void segment(Bands *B, double p0, double q0, double p1, double q1) {
    for (int k = 0; k < K; k++) {
        double l = L[k];
        if (B->blocked[k]) {
            if (q1 <= l + EPS) {
                double t = (q0 - l) / (q0 - q1);
                B->blocked[k] = 0;
                B->start[k] = p0 + t * (p1 - p0);
            }
        } else if (q1 > l + EPS) {
            double t = (l - q0) / (q1 - q0);
            double pc = p0 + t * (p1 - p0);
            B->lie[k] += count_free(B->start[k], pc, k, 0);
            B->stand[k] += count_free(B->start[k], pc, k, 1);
            B->blocked[k] = 1;
        }
    }
}

static int best_bands(const Bands *B, int *choice) {
    int best[MAXK + 1], how[MAXK + 1];
    best[0] = 0;
    for (int k = 0; k < K; k++) {
        best[k + 1] = best[k] + B->lie[k]; how[k + 1] = 0;
        if (k >= 1 && best[k - 1] + B->stand[k] > best[k + 1]) { best[k + 1] = best[k - 1] + B->stand[k]; how[k + 1] = 1; }
    }
    if (choice) {
        int k = K;
        while (k > 0) {
            if (how[k]) { choice[k - 1] = 2; choice[k - 2] = 2; k -= 2; } else { choice[k - 1] = 1; k -= 1; }
        }
    }
    return best[K];
}

static int dominoes_in_D(int W) {
    int area = 0, e = 0, o = 0;
    for (int i = 0; i < W; i++) {
        area += H[i];
        int beta = H[i] + (W - 1 - i);
        if (beta % 2) o++; else e++;
    }
    int core = e * (e - 1) + o * o - W * (W - 1) / 2;
    return (area - core) / 2;
}

static int row_length(int W, int j) {
    int w = 0;
    while (w < W && H[w] > j) w++;
    return w;
}

/* --- V pairs: the gesture of Wolk's 32 and 38 ----------------------------------------------
 * Two dominoes in band k lean towards each other by delta from the band normal, touch at the
 * top on the axis p = pm and touch the outer edge of the band (depth k) with their outer top
 * corners; they straddle an outer corner of D at depth h below the hypotenuse, k + 1 < h, and
 * clear it when 2 cos(delta) - sin(delta) <= h - k. The smallest such delta is used. */
#define MAXV 24
typedef struct { int band; double pm, h, delta; double P[2][4], Q[2][4]; } Vee;

static double gfun(double d) { return 2 * cos(d) - sin(d); }

static int make_vee(int k, double pm, double h, Vee *v) {
    double target = h - k, delta = 0;
    if (target < 2 - EPS) {
        double lo = 0, hi = 30 * M_PI / 180;
        if (gfun(hi) > target) return 0;
        for (int it = 0; it < 60; it++) { double mid = (lo + hi) / 2; if (gfun(mid) > target) lo = mid; else hi = mid; }
        delta = hi;
    }
    double sd = sin(delta), cd = cos(delta), top = S / R2;
    double pc = pm - sd - 0.5 * cd, hc = k + cd + 0.5 * sd;   /* centre of the left domino (p, depth) */
    const double sa[4] = {1, 1, -1, -1}, sw[4] = {1, -1, -1, 1};   /* TR, TL, BL, BR */
    for (int c = 0; c < 4; c++) {
        double p = pc + sa[c] * sd + sw[c] * 0.5 * cd;
        double depth = hc - sa[c] * cd + sw[c] * 0.5 * sd;
        v->P[0][c] = p; v->Q[0][c] = top - depth;
        v->P[1][c] = 2 * pm - p; v->Q[1][c] = top - depth;
    }
    v->band = k; v->pm = pm; v->h = h; v->delta = delta;
    return 1;
}

/* Separating-axis test between two convex quadrilaterals given in (p, q). */
static int quads_overlap(const double *P1, const double *Q1, const double *P2, const double *Q2) {
    const double *Ps[2] = {P1, P2}, *Qs[2] = {Q1, Q2};
    for (int s = 0; s < 2; s++)
        for (int e = 0; e < 4; e++) {
            double nx = -(Qs[s][(e + 1) % 4] - Qs[s][e]), ny = Ps[s][(e + 1) % 4] - Ps[s][e];
            double a0 = 1e18, a1 = -1e18, b0 = 1e18, b1 = -1e18;
            for (int c = 0; c < 4; c++) {
                double x = P1[c] * nx + Q1[c] * ny, y = P2[c] * nx + Q2[c] * ny;
                if (x < a0) a0 = x;
                if (x > a1) a1 = x;
                if (y < b0) b0 = y;
                if (y > b1) b1 = y;
            }
            double norm = sqrt(nx * nx + ny * ny);
            if (a1 <= b0 + EPS * norm || b1 <= a0 + EPS * norm) return 0;
        }
    return 1;
}

static int vee_valid(const Vee *v, int W) {
    for (int d = 0; d < 2; d++)
        for (int c = 0; c < 4; c++) {
            double p = v->P[d][c], q = v->Q[d][c];
            if (q > S / R2 + EPS || q < fabs(p) - EPS) return 0;   /* hypotenuse and legs */
        }
    for (int i = 0; i < W; i++)
        for (int j = 0; j < H[i]; j++) {
            double u[4] = {i, i + 1, i + 1, i}, w[4] = {j, j, j + 1, j + 1}, P[4], Q[4];
            for (int c = 0; c < 4; c++) { P[c] = (u[c] - w[c]) / R2; Q[c] = (u[c] + w[c]) / R2; }
            if (quads_overlap(v->P[0], v->Q[0], P, Q) || quads_overlap(v->P[1], v->Q[1], P, Q)) return 0;
        }
    return 1;
}

static int vees_clash(const Vee *a, const Vee *b) {
    for (int x = 0; x < 2; x++) for (int y = 0; y < 2; y++)
        if (quads_overlap(a->P[x], a->Q[x], b->P[y], b->Q[y])) return 1;
    return 0;
}

/* p-extent of a quadrilateral (p, q) inside the open strip l < q < l + w. */
static int quad_strip(const double *P0, const double *Q0, double l, double w, double *lo, double *hi) {
    double P[12], Q[12], P2[12], Q2[12];
    int k = 4;
    memcpy(P, P0, 4 * sizeof(double)); memcpy(Q, Q0, 4 * sizeof(double));
    for (int side = 0; side < 2; side++) {
        int k2 = 0;
        for (int i = 0; i < k; i++) {
            int j = (i + 1) % k;
            double fi = side == 0 ? Q[i] - l : l + w - Q[i];
            double fj = side == 0 ? Q[j] - l : l + w - Q[j];
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
    if (qb - qa < EPS || b - a < EPS) return 0;
    *lo = a; *hi = b;
    return 1;
}

/* Open p-intervals of level l where the boundary path of D is above it. */
static int d_intervals(int W, double l, double (*out)[2]) {
    int n = 0;
    if (W == 0) return 0;
    double pu[2 * MAXW + 40], pv[2 * MAXW + 40];
    int np = 0;
    pu[np] = 0; pv[np] = H[0]; np++;
    for (int i = 0; i < W; i++) {
        pu[np] = i + 1; pv[np] = H[i]; np++;
        for (int h = H[i] - 1; h >= H[i + 1]; h--) { pu[np] = i + 1; pv[np] = h; np++; }
    }
    int inside = 0;
    double start = 0;
    for (int i = 0; i < np; i++) {
        double p = (pu[i] - pv[i]) / R2, q = (pu[i] + pv[i]) / R2;
        if (i == 0) { if (q > l + EPS) { inside = 1; start = p; } continue; }
        double p0 = (pu[i - 1] - pv[i - 1]) / R2, q0 = (pu[i - 1] + pv[i - 1]) / R2;
        if (!inside && q > l + EPS) {
            double t = (l - q0) / (q - q0);
            if (t < 0) t = 0;
            start = p0 + t * (p - p0); inside = 1;
        } else if (inside && q <= l + EPS) {
            double t = (q0 - l) / (q0 - q);
            if (t > 1) t = 1;
            out[n][0] = start; out[n][1] = p0 + t * (p - p0); n++; inside = 0;
        }
    }
    if (inside) { out[n][0] = start; out[n][1] = (pu[np - 1] - pv[np - 1]) / R2; n++; }
    return n;
}

static int cmp2(const void *a, const void *b) {
    double d = ((const double *)a)[0] - ((const double *)b)[0];
    return (d > 0) - (d < 0);
}

/* Bands with D and the chosen V's as obstacles: lying or standing per band, as best_bands. */
static int bands_with(int W, const Vee *vs, int nv, int *choice) {
    int lie[MAXK], stand[MAXK];
    for (int k = 0; k < K; k++)
        for (int kind = 0; kind < 2; kind++) {
            double width = kind == 0 ? 1.0 : 2.0, bad[96][2];
            int nb = d_intervals(W, L[k], bad);
            for (int i = 0; i < nv; i++)
                for (int d = 0; d < 2; d++) {
                    double lo, hi;
                    if (quad_strip(vs[i].P[d], vs[i].Q[d], L[k], width, &lo, &hi)) { bad[nb][0] = lo; bad[nb][1] = hi; nb++; }
                }
            qsort(bad, nb, sizeof bad[0], cmp2);
            double unit = kind == 0 ? 2.0 : 1.0, x = -L[k];
            int count = 0;
            for (int i = 0; i < nb; i++) {
                if (bad[i][1] <= x) continue;
                if (bad[i][0] > x) count += (int)floor((fmin(bad[i][0], L[k]) - x + EPS) / unit);
                if (bad[i][1] > x) x = bad[i][1];
                if (x >= L[k]) break;
            }
            if (x < L[k]) count += (int)floor((L[k] - x + EPS) / unit);
            if (kind == 0) lie[k] = count; else stand[k] = count;
        }
    int best[MAXK + 1], how[MAXK + 1];
    best[0] = 0;
    for (int k = 0; k < K; k++) {
        best[k + 1] = best[k] + lie[k]; how[k + 1] = 0;
        if (k >= 1 && best[k - 1] + stand[k] > best[k + 1]) { best[k + 1] = best[k - 1] + stand[k]; how[k + 1] = 1; }
    }
    if (choice) {
        int k = K;
        while (k > 0) {
            if (how[k]) { choice[k - 1] = 2; choice[k - 2] = 2; k -= 2; } else { choice[k - 1] = 1; k -= 1; }
        }
    }
    return best[K];
}

static Vee VS[MAXV];
static int NVS, vee_best, vee_pick[MAXV], vee_npick, cur_pick[MAXV];
static unsigned char clash[MAXV][MAXV];

static void subsets(int W, int i, int npick, int dominoes) {
    if (i == NVS) {
        if (list_n && npick == 0) return;   /* list mode: structures that use a V */
        Vee chosen[MAXV];
        for (int j = 0; j < npick; j++) chosen[j] = VS[cur_pick[j]];
        int total = dominoes + 2 * npick + bands_with(W, chosen, npick, NULL);
        if (total > vee_best) { vee_best = total; vee_npick = npick; memcpy(vee_pick, cur_pick, sizeof cur_pick); }
        return;
    }
    subsets(W, i + 1, npick, dominoes);
    for (int j = 0; j < npick; j++) if (clash[cur_pick[j]][i]) return;
    cur_pick[npick] = i;
    subsets(W, i + 1, npick + 1, dominoes);
}

/* The best count with V's for the current D, or -1 when it cannot beat floor_count. */
static int with_vees(int W, int layered, int floor_count, char *how, size_t size) {
    NVS = 0;
    for (int i = 0; i < W; i++) {
        if (H[i] <= H[i + 1]) continue;
        double pm = (i + 1 - H[i]) / R2, h = S / R2 - (i + 1 + H[i]) / R2;
        for (int k = 0; k < K && NVS < MAXV; k++) {
            if (h <= k + 1 + EPS || h > k + 2.75) continue;
            Vee v;
            if (make_vee(k, pm, h, &v) && vee_valid(&v, W)) VS[NVS++] = v;
        }
    }
    if (NVS == 0 || layered + NVS <= floor_count) return -1;
    for (int a = 0; a < NVS; a++) for (int b = 0; b < NVS; b++) clash[a][b] = a != b && vees_clash(&VS[a], &VS[b]);
    vee_best = -1; vee_npick = 0;
    subsets(W, 0, 0, dominoes_in_D(W));
    if (vee_best <= floor_count) return -1;
    Vee chosen[MAXV];
    for (int j = 0; j < vee_npick; j++) chosen[j] = VS[vee_pick[j]];
    int choice[MAXK];
    bands_with(W, chosen, vee_npick, choice);
    int o = snprintf(how, size, "D=[");
    for (int i = 0; i < W; i++) o += snprintf(how + o, size - o, "%s%d", i ? "," : "", H[i]);
    o += snprintf(how + o, size - o, "] bands=");
    for (int k = 0; k < K; k++) o += snprintf(how + o, size - o, "%c", choice[k] == 1 ? 'l' : 's');
    o += snprintf(how + o, size - o, " V=");
    for (int j = 0; j < vee_npick; j++)
        o += snprintf(how + o, size - o, "%s(%d,%.6f,%.4f)", j ? "," : "", chosen[j].band, chosen[j].pm, chosen[j].delta * 180 / M_PI);
    return vee_best;
}

static void leaf(int W, Bands *B) {
    /* Corner stacks against D's first rows. */
    if (corner_kind == 1 && row_length(W, 0) > S - 1 - 2 * corner_n + EPS) return;
    if (corner_kind == 2 && (row_length(W, 0) > S - 2 - corner_n + EPS || row_length(W, 1) > S - 2 - corner_n + EPS)) return;
    Bands F = *B;
    for (int k = 0; k < K; k++)
        if (!F.blocked[k]) {
            F.lie[k] += count_free(F.start[k], L[k], k, 0);
            F.stand[k] += count_free(F.start[k], L[k], k, 1);
        }
    int total = dominoes_in_D(W) + stack_count + best_bands(&F, NULL);
    if (total > cur_best) {
        cur_best = total;
        int choice[MAXK];
        best_bands(&F, choice);
        int o = snprintf(cur_how, sizeof cur_how, "D=[");
        for (int i = 0; i < W; i++) o += snprintf(cur_how + o, sizeof cur_how - o, "%s%d", i ? "," : "", H[i]);
        o += snprintf(cur_how + o, sizeof cur_how - o, "] uprightD=%d apex=%c%d corner=%c%d bands=", dominoes_in_D(W),
                      " VH"[apex_kind], apex_n, " HV"[corner_kind], corner_n);
        for (int k = 0; k < K; k++) o += snprintf(cur_how + o, sizeof cur_how - o, "%c", choice[k] == 1 ? 'l' : 's');
    }
    if (stack_count == 0) {
        char how[300];
        int floor_count = list_n ? list_n - 1 : cur_best;
        int v = with_vees(W, total, floor_count, how, sizeof how);
        if (v > cur_best) { cur_best = v; memcpy(cur_how, how, sizeof how); }
        if (list_n && v >= list_n && vee_npick > 0 && listed < list_max) { printf("%d %s\n", v, how); listed++; }
    }
}

/* Column i of D (0-based); the path is at (i, H[i-1]) after the previous column's top. */
static void columns(int i, int limit, Bands *B) {
    /* Height 0 ends D: the path goes down to (i, 0). */
    {
        Bands C = *B;
        if (i > 0) {
            for (int h = H[i - 1]; h > 0; h--)
                segment(&C, (i - h) / R2, (i + h) / R2, (i - h + 1) / R2, (i + h - 1) / R2);
        }
        H[i] = 0;
        leaf(i, &C);
    }
    for (int h = 1; h <= limit; h++) {
        if (i + 1 + h > S + EPS) break;
        if (i == 0) {
            if (apex_kind == 1 && h > S - 1 - 2 * apex_n + EPS) break;
            if (apex_kind == 2 && h > S - 2 - apex_n + EPS) break;
        }
        if (i == 1 && apex_kind == 2 && h > S - 2 - apex_n + EPS) break;
        Bands C;
        if (i == 0) {
            for (int k = 0; k < K; k++) {
                C.lie[k] = C.stand[k] = 0;
                if (h / R2 > L[k] + EPS) C.blocked[k] = 1;
                else { C.blocked[k] = 0; C.start[k] = -L[k]; }
            }
        } else {
            C = *B;
            for (int d = H[i - 1]; d > h; d--)
                segment(&C, (i - d) / R2, (i + d) / R2, (i - d + 1) / R2, (i + d - 1) / R2);
        }
        /* The top of column i: from (i, h) to (i + 1, h). */
        segment(&C, (i - h) / R2, (i + h) / R2, (i + 1 - h) / R2, (i + 1 + h) / R2);
        H[i] = h;
        columns(i + 1, h, &C);
    }
    H[i] = 0;
}

static void run_legs(void) {
    K = 0;
    for (int k = 0; k < MAXK; k++) {
        double l = S / R2 - (k + 1);
        if (l < 0.5 - EPS) break;
        L[K++] = l;
    }
    nrect = 0;
    stack_count = 0;
    if (apex_kind == 1) { double r[4] = {0, 1, S - 1 - 2 * apex_n, S - 1}; memcpy(rect[nrect++], r, sizeof r); stack_count += apex_n; }
    if (apex_kind == 2) { double r[4] = {0, 2, S - 2 - apex_n, S - 2}; memcpy(rect[nrect++], r, sizeof r); stack_count += apex_n; }
    if (corner_kind == 1) { double r[4] = {S - 1 - 2 * corner_n, S - 1, 0, 1}; memcpy(rect[nrect++], r, sizeof r); stack_count += corner_n; }
    if (corner_kind == 2) { double r[4] = {S - 2 - corner_n, S - 2, 0, 2}; memcpy(rect[nrect++], r, sizeof r); stack_count += corner_n; }
    for (int i = 0; i < nrect; i++) if (rect[i][0] < -EPS || rect[i][2] < -EPS) return;
    if (nrect == 2) {   /* the two stacks must not overlap */
        if (rect[0][1] > rect[1][0] + EPS && rect[1][1] > rect[0][0] + EPS &&
            rect[0][3] > rect[1][2] + EPS && rect[1][3] > rect[0][2] + EPS) return;
    }
    for (int k = 0; k < K; k++)
        for (int kind = 0; kind < 2; kind++) {
            NSB[k][kind] = 0;
            for (int i = 0; i < nrect; i++) {
                double lo, hi;
                if (strip_extent(rect[i], L[k], kind == 0 ? 1.0 : 2.0, &lo, &hi)) {
                    SB[k][kind][NSB[k][kind]][0] = lo; SB[k][kind][NSB[k][kind]][1] = hi; NSB[k][kind]++;
                }
            }
            /* sort by lo */
            for (int a = 0; a < NSB[k][kind]; a++) for (int b = a + 1; b < NSB[k][kind]; b++)
                if (SB[k][kind][b][0] < SB[k][kind][a][0]) {
                    double t0 = SB[k][kind][a][0], t1 = SB[k][kind][a][1];
                    SB[k][kind][a][0] = SB[k][kind][b][0]; SB[k][kind][a][1] = SB[k][kind][b][1];
                    SB[k][kind][b][0] = t0; SB[k][kind][b][1] = t1;
                }
        }
    Bands B;
    memset(&B, 0, sizeof B);
    for (int k = 0; k < K; k++) B.start[k] = -L[k];   /* an empty D leaves every band free */
    memset(H, 0, sizeof H);
    columns(0, MAXW, &B);
}

static void best_for_legs(int stacks) {
    cur_best = 0;
    int amax = stacks ? 2 : 0;
    for (apex_kind = 0; apex_kind <= amax; apex_kind++)
        for (apex_n = apex_kind ? 1 : 0; apex_n <= (apex_kind ? 3 : 0); apex_n++)
            for (corner_kind = 0; corner_kind <= amax; corner_kind++)
                for (corner_n = corner_kind ? 1 : 0; corner_n <= (corner_kind ? 3 : 0); corner_n++)
                    run_legs();
}

int main(int argc, char **argv) {
    int stacks = argc > 1 ? atoi(argv[1]) : 0;
    if (argc > 2 && strcmp(argv[2], "list") == 0) {
        /* ./domv 0 list N S MAX: up to MAX structures with V's holding N dominoes at legs S. */
        list_n = atoi(argv[3]); S = atof(argv[4]); list_max = argc > 5 ? atoi(argv[5]) : 50;
        best_for_legs(0);
        return 0;
    }
    if (argc > 2 && strcmp(argv[2], "live") == 0) {
        /* Just below each live value: does the model with V's still hold n? */
        const double r = R2;
        const double lv[51] = {0, 2 * r, 1 + 2 * r, 3 * r, 2 + 2 * r, 1 + 3 * r, 4 * r, 2 + 3 * r, 5 + r, 4 + 2 * r,
            5 * r, 6 + r, 5 + 2 * r, 8, 4 + 3 * r, 6 * r, 6 + 2 * r, 9, 5 + 3 * r, 1 + 6 * r, 7 + 2 * r,
            7 * r, 3 + 5 * r, 9 + r, 10.57901, 8 + 2 * r, 10.99322, 4 + 5 * r, 8 * r, 3 + 6 * r, 9 + 2 * r,
            2 + 7 * r, 12.0569644, 8 + 3 * r, 11 + r, 12.59172, 9 * r, 3 + 7 * r, 13.0569644, 9 + 3 * r, 12 + r,
            8 + 4 * r, 1 + 9 * r, 4 + 7 * r, 14.02663, 10 * r, 3 + 8 * r, 6 + 6 * r, 9 + 4 * r, 12 + 2 * r, 5 + 7 * r};
        int first = argc > 3 ? atoi(argv[3]) : 1, last = argc > 4 ? atoi(argv[4]) : 50;
        double shift = argc > 5 ? atof(argv[5]) : -1e-6;   /* where to look, relative to the live value */
        for (int n = first; n <= last; n++) {
            S = lv[n] + shift;
            best_for_legs(stacks);
            printf("%2d  at %.6f holds %d %s  %s\n", n, S, cur_best, cur_best >= n ? "BEATS" : "", cur_best >= n ? cur_how : "");
            fflush(stdout);
        }
        return 0;
    }
    if (argc > 3) {
        for (int i = 2; i + 1 < argc; i += 2) {
            int a = atoi(argv[i]), c = atoi(argv[i + 1]);
            S = a + c / R2;
            best_for_legs(stacks);
            printf("%d + %d/sqrt2 = %.5f holds %d: %s\n", a, c, S, cur_best, cur_how);
        }
        return 0;
    }
    const double r = R2;
    const double live[51] = {0, 2 * r, 1 + 2 * r, 3 * r, 2 + 2 * r, 1 + 3 * r, 4 * r, 2 + 3 * r, 5 + r, 4 + 2 * r,
        5 * r, 6 + r, 5 + 2 * r, 8, 4 + 3 * r, 6 * r, 6 + 2 * r, 9, 5 + 3 * r, 1 + 6 * r, 7 + 2 * r,
        7 * r, 3 + 5 * r, 9 + r, 10.57901, 8 + 2 * r, 10.99322, 4 + 5 * r, 8 * r, 3 + 6 * r, 9 + 2 * r,
        2 + 7 * r, 12.0569644, 8 + 3 * r, 11 + r, 12.59172, 9 * r, 3 + 7 * r, 13.0569644, 9 + 3 * r, 12 + r,
        8 + 4 * r, 1 + 9 * r, 4 + 7 * r, 14.02663, 10 * r, 3 + 8 * r, 6 + 6 * r, 14.65686, 12 + 2 * r, 5 + 7 * r};
    static double best_s[MAXN + 1];
    static char best_how[MAXN + 1][360];
    for (int n = 0; n <= MAXN; n++) best_s[n] = 1e9;
    for (int a = 0; a <= 16; a++) for (int c = 0; c <= 24; c++) {
        S = a + c / R2;
        if (S < 2.8 || S > 15.0) continue;
        best_for_legs(stacks);
        for (int n = 1; n <= cur_best && n <= MAXN; n++)
            if (S < best_s[n] - EPS) {
                best_s[n] = S;
                snprintf(best_how[n], sizeof best_how[n], "%d + %d/sqrt2 holds %d: %s", a, c, cur_best, cur_how);
            }
    }
    for (int n = 1; n <= 50; n++)
        printf("%2d  %9.5f  live %9.5f %s  %s\n", n, best_s[n], live[n],
               best_s[n] < live[n] - 1e-6 ? "BEATS" : best_s[n] > live[n] + 1e-6 ? "worse" : "  =  ", best_how[n]);
    return 0;
}
