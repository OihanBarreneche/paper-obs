import type { ProblemDoc } from "./types";

export type ReferenceSource = { label: string; url: string };
export type ProblemReference = {
  status: "proved" | "best_known" | "none";
  value: number | null;
  unit: string;
  author: string;
  date: string;
  proved_by: string;
  proof_date: string;
  verified_on: string;
  note: string;
  preview: string;
  sources: ReferenceSource[];
};

/** Whether a preview is the source's own bitmap rather than the lab's own drawing. */
export function sourceFigure(url: string): boolean {
  return /^https?:/i.test(url);
}

export type SquareRecord = {
  count: number;
  side: number;
  reference: ProblemReference;
  /** True when the published layout ships with the interface as a candidate file. */
  hasCandidate: boolean;
};

/**
 * The largest number of shapes a record may pack and still be listed.
 *
 * Large arrangements have not been validated for smooth interaction, so a record whose
 * own count is larger is kept in the data — the catalogue asset and `SQUARE_RECORDS`
 * below both stay complete — but the navigator does not list it. That is a display
 * rule, not a deletion: see docs/precision-and-performance.md. The curated squares and the generated catalogue
 * share it through `withinVisibleCount`, so one threshold governs the whole page.
 */
export const MAX_VISIBLE_COUNT = 100;

/** Whether a record's own shape count is small enough for the navigator to list. */
export function withinVisibleCount(count: number): boolean {
  return count <= MAX_VISIBLE_COUNT;
}

const SQUARES_SOURCE = "https://kingbird.myphotos.cc/packing/squares_in_squares.html";
/** The page's own SVGs: the published layouts it serves, hotlinked by the cards. */
const SQUARES_FIGURE_BASE = "https://kingbird.myphotos.cc/packing/";
/** The largest count whose published layout ships locally as a candidate file. */
const LOCAL_CANDIDATE_MAX = 29;
export const PACKING_INDEX = "https://erich-friedman.github.io/packing/index.html";

// One row is one published record: its count, its container side, who found it,
// who proved it optimal, and the page's own figure when it has one. The rows
// below are exactly the records the source page lists, in its own order, read
// from kingbird.myphotos.cc/packing/squares_in_squares.html: no count it leaves
// out is invented here, and none it publishes is dropped. The page jumps from 11
// to 13, from 41 to 46 and skips every straight-grid count (12, 16, 20, 21, 25,
// 30-32, ...); the catalogue shows the same gaps.
type Row = [count: number, side: number, author?: string, date?: string, provedBy?: string, proofDate?: string, figure?: string];

// The records up to 29: the lab also ships their arrangements as candidate
// files, so their cards open on the published packing rather than on a figure.
const ROWS: Row[] = [
  [1, 1],
  [2, 2, "", "", "Frits Göbel", "1979"],
  [3, 2, "", "", "Frits Göbel", "1979"],
  [4, 2],
  [5, 2.70710678118654, "Frits Göbel", "1979", "Frits Göbel", "1979"],
  [6, 3, "", "", "Michael Kearney and Peter Shiu", "2001"],
  [7, 3, "", "", "Erich Friedman", "1999"],
  [8, 3, "", "", "Erich Friedman", "1999"],
  [9, 3],
  [10, 3.70710678118654, "Frits Göbel", "1979", "Walter Stromquist", "2003"],
  [11, 3.87708359002281, "Walter Trump", "1979"],
  [13, 4, "", "", "Wolfram Bentz", "2009"],
  [14, 4, "", "", "Erich Friedman", "1999"],
  [15, 4, "", "", "Erich Friedman", "1999"],
  [17, 4.67553009360455, "John Bidwell", "1998"],
  [18, 4.82287565553229, "Pertti Hämäläinen", "1980"],
  [19, 4.88561808316412, "Robert Wainwright", "1979"],
  [22, 5, "", "", "Wolfram Bentz", "2018"],
  [23, 5, "", "", "Hiroshi Nagamochi", "2005"],
  [24, 5, "", "", "Erich Friedman", "1999"],
  [26, 5.62132034355964, "Erich Friedman", "1997"],
  [27, 5.70710678118654, "Frits Göbel", "1979"],
  [28, 5.82444461667405, "David Ellsworth", "2025"],
  [29, 5.93383346267692, "Thomas Schadt", "2025"],
];

// The records above 29: the page's own figures are the only arrangement the lab
// can show, and the card hotlinks them.
const EXTRA_ROWS: Row[] = [
  [33, 6.0, "", "", "Wolfram Bentz", "October 2018", "square-33.svg"],
  [34, 6.0, "", "", "Hiroshi Nagamochi", "2005", "square-34.svg"],
  [35, 6.0, "", "", "Erich Friedman", "1999", "square-35.svg"],
  [37, 6.59861960924436, "David W. Cantrell", "September 2002", "", "", "square-37.svg"],
  [38, 6.70710678118654, "Frits Göbel", "early 1979", "", "", "square-38.svg"],
  [39, 6.81072208306864, "Thomas Schadt", "January 2026", "", "", "square-39.svg"],
  [40, 6.82842712474619, "Frits Göbel", "early 1979", "", "", "square-40.svg"],
  [41, 6.9266930944688, "Thomas Schadt", "December 2025", "", "", "square-41.svg"],
  [46, 7.0, "", "", "Wolfram Bentz", "August 2009", "square-46.svg"],
  [47, 7.0, "", "", "Hiroshi Nagamochi", "2005", "square-48.svg"],
  [48, 7.0, "", "", "Hiroshi Nagamochi", "2005", "square-48.svg"],
  [50, 7.57142857142857, "Thomas Schadt", "December 2025", "", "", "square-50.svg"],
  [51, 7.70079923541701, "Thomas Schadt", "January 2026", "", "", "square-51.svg"],
  [52, 7.70710678118654, "Frits Göbel", "early 1979", "", "", "square-52.svg"],
  [53, 7.82287565553229, "David W. Cantrell", "September 2002", "", "", "square-53.svg"],
  [54, 7.84666719284348, "David W. Cantrell", "October 2005", "", "", "square-54.svg"],
  [55, 7.94577100750391, "Thomas Schadt", "January 2026", "", "", "square-55.svg"],
  [62, 8.0, "", "", "Hiroshi Nagamochi", "2005", "square-63.svg"],
  [63, 8.0, "", "", "Hiroshi Nagamochi", "2005", "square-63.svg"],
  [65, 8.53553390593273, "Frits Göbel", "early 1979", "", "", "square-65.svg"],
  [66, 8.65685424949238, "Evert Stenlund", "early 1980", "", "", "square-66.svg"],
  [67, 8.70710678118654, "Evert Stenlund", "early 1980", "", "", "square-67.svg"],
  [68, 8.7987961402601, "Sigvart Brendberg", "June 2023", "", "", "square-68.svg"],
  [69, 8.82719465572973, "Maurizio Morandi", "June 2010", "", "", "square-69.svg"],
  [70, 8.881666757009, "Joe DeVincentis", "April 2014", "", "", "square-70.svg"],
  [71, 8.94407155757031, "Thomas Schadt", "December 2025", "", "", "square-71.svg"],
  [79, 9.0, "", "", "Hiroshi Nagamochi", "2005", "square-80.svg"],
  [80, 9.0, "", "", "Hiroshi Nagamochi", "2005", "square-80.svg"],
  [82, 9.53553390593273, "Frits Göbel", "early 1979", "", "", "square-82.svg"],
  [83, 9.63475764863108, "Károly Hajba", "September 2024", "", "", "square-83.svg"],
  [84, 9.70710678118654, "Evert Stenlund", "early 1980", "", "", "square-84.svg"],
  [85, 9.74264068711928, "Erich Friedman", "1997", "", "", "square-85b.svg"],
  [86, 9.82287565553229, "Erich Friedman", "1997", "", "", "square-86.svg"],
  [87, 9.83881526994826, "David Ellsworth", "December 2024", "", "", "square-87.svg"],
  [88, 9.88815305375857, "David Ellsworth", "November 2024", "", "", "square-88.svg"],
  [89, 9.94974746830583, "Evert Stenlund", "early 1980", "", "", "square-89.svg"],
  [98, 10.0, "", "", "Hiroshi Nagamochi", "2005", "square-99.svg"],
  [99, 10.0, "", "", "Hiroshi Nagamochi", "2005", "square-99.svg"],
  [101, 10.53553390593273, "Frits Göbel", "early 1979", "", "", "square-101.svg"],
  [102, 10.61138794077522, "Károly Hajba", "September 2024", "", "", "square-102.svg"],
  [103, 10.70378195534367, "Thomas Schadt", "December 2025", "", "", "square-103.svg"],
  [104, 10.70710678118654, "Frits Göbel", "early 1979", "", "", "square-104.svg"],
  [105, 10.80761933330707, "Thomas Schadt", "December 2025", "", "", "square-105.svg"],
  [106, 10.82297973416944, "David Ellsworth", "November 2024", "", "", "square-106.svg"],
  [107, 10.84666719284348, "Károly Hajba", "November 2024", "", "", "square-107.svg"],
  [108, 10.92591939016138, "Károly Hajba", "October 2024", "", "", "square-108.svg"],
  [109, 10.94974746830583, "Frits Göbel", "early 1979", "", "", "square-109.svg"],
  [110, 10.99679327401957, "David W. Cantrell", "February 2025", "", "", "square-110.svg"],
  [119, 11.0, "", "", "Hiroshi Nagamochi", "2005", "square-120.svg"],
  [120, 11.0, "", "", "Hiroshi Nagamochi", "2005", "square-120.svg"],
  [122, 11.53553390593273, "Frits Göbel", "early 1979", "", "", "square-122.svg"],
  [123, 11.60139979378801, "Károly Hajba", "September 2024 and adapting and extending the $s(37)$ improvement found by David W", "", "", "square-123.svg"],
  [124, 11.65685424949238, "Frits Göbel", "early 1979", "", "", "square-124.svg"],
  [125, 11.70710678118654, "Frits Göbel", "early 1979", "", "", "square-125.svg"],
  [126, 11.77473513240654, "Joost de Winter", "August 2026", "", "", "square-126.svg"],
  [127, 11.82287565553229, "Erich Friedman", "1997", "", "", "square-127.svg"],
  [128, 11.82509196821368, "David Ellsworth", "November 2024", "", "", "square-128.svg"],
  [129, 11.88130621809, "David W. Cantrell", "September 2002", "", "", "square-129.svg"],
  [130, 11.91119052015898, "David Ellsworth", "November 2024", "", "", "square-130.svg"],
  [131, 11.95652543280926, "David Ellsworth", "January 2026", "", "", "square-131.svg"],
  [132, 11.99137344423646, "M.Z. Arslanov, S.A. Mustafin, and Z.K. Shangitbayev", "March 2019", "", "", "square-132.svg"],
  [142, 12.0, "", "", "Hiroshi Nagamochi", "2005", "square-143.svg"],
  [143, 12.0, "", "", "Hiroshi Nagamochi", "2005", "square-143.svg"],
  [145, 12.53553390593273, "Frits Göbel", "early 1979", "", "", "square-145.svg"],
  [146, 12.60090777851301, "David W. Cantrell", "January 2025 by switching to the rotationally symmetric form of adding an \"L\" to the $s(123)$ found and improved by David Ellsworth in December 2024 and improved by David W", "", "", "square-146.svg"],
  [147, 12.65685424949238, "Frits Göbel", "early 1979", "", "", "square-148.svg"],
  [148, 12.65685424949238, "Frits Göbel", "early 1979", "", "", "square-148.svg"],
  [149, 12.70710678118654, "Frits Göbel", "early 1979", "", "", "square-149.svg"],
  [150, 12.77817459305202, "David Ellsworth", "January 2025", "", "", "square-150.svg"],
  [151, 12.82287565553229, "David Ellsworth", "November 2024", "", "", "square-151.svg"],
  [152, 12.830959544726, "David Ellsworth and David W. Cantrell", "January 2025", "", "", "square-152.svg"],
  [153, 12.881666757009, "David Ellsworth", "November 2024", "", "", "square-153.svg"],
  [154, 12.93166712962655, "David Ellsworth", "December 2024", "", "", "square-154.svg"],
  [155, 12.95844711161529, "David Ellsworth", "January 2026", "", "", "square-155.svg"],
  [156, 12.98208376048414, "M.Z. Arslanov, S.A. Mustafin, and Z.K. Shangitbayev", "March 2019", "", "", "square-156.svg"],
  [167, 13.0, "", "", "Hiroshi Nagamochi", "2005", "square-168.svg"],
  [168, 13.0, "", "", "Hiroshi Nagamochi", "2005", "square-168.svg"],
  [170, 13.53553390593273, "Frits Göbel", "early 1979", "", "", "square-170b.svg"],
  [171, 13.57142857142857, "David Ellsworth", "December 2025", "", "", "square-171.svg"],
  [172, 13.6189889866016, "Károly Hajba", "November 2024", "", "", "square-172.svg"],
  [173, 13.65685424949238, "Frits Göbel", "early 1979", "", "", "square-173.svg"],
  [174, 13.70710678118654, "Frits Göbel", "early 1979", "", "", "square-174.svg"],
  [175, 13.77817459305202, "David Ellsworth", "December 2024", "", "", "square-175.svg"],
  [176, 13.82287565553229, "Erich Friedman", "1997", "", "", "square-176.svg"],
  [177, 13.82302875075647, "", "", "", "", "square-177.svg"],
  [178, 13.84666719284348, "Joe DeVincentis", "April 2014", "", "", "square-178.svg"],
  [179, 13.89534106997649, "David Ellsworth", "January 2025", "", "", "square-179.svg"],
  [180, 13.93508705291129, "David Ellsworth", "January 2026", "", "", "square-180.svg"],
  [181, 13.95690672341755, "David Ellsworth", "January 2026", "", "", "square-181.svg"],
  [182, 13.97419105332569, "M.Z. Arslanov, S.A. Mustafin, and Z.K. Shangitbayev", "March 2019", "", "", "square-182.svg"],
  [194, 14.0, "", "", "Hiroshi Nagamochi", "2005", "square-195.svg"],
  [195, 14.0, "", "", "Hiroshi Nagamochi", "2005", "square-195.svg"],
  [197, 14.53553390593273, "Frits Göbel", "early 1979", "", "", "square-197.svg"],
  [198, 14.57142857142857, "David Ellsworth", "December 2025 by combining two copies of the $s(50)$ found by Thomas Schadt in December 2025 (using a simulated annealing program he wrote", "", "", "square-198.svg"],
  [199, 14.6189889866016, "Károly Hajba", "November 2024", "", "", "square-199.svg"],
  [200, 14.65685424949238, "Frits Göbel", "early 1979", "", "", "square-200.svg"],
  [201, 14.70710678118654, "Frits Göbel", "early 1979", "", "", "square-201.svg"],
  [202, 14.72792206135785, "Frits Göbel", "early 1979", "", "", "square-202.svg"],
  [203, 14.77817459305202, "David Ellsworth", "December 2024", "", "", "square-203a.svg"],
  [204, 14.82287565553229, "Erich Friedman", "1997", "", "", "square-204.svg"],
  [205, 14.82445114612408, "David Ellsworth", "December 2024", "", "", "square-205.svg"],
  [206, 14.87221902560728, "David W. Cantrell", "September 2002", "", "", "square-206.svg"],
  [207, 14.89395494255333, "David Ellsworth", "November 2024", "", "", "square-207.svg"],
  [208, 14.93776656277905, "David Ellsworth", "January 2026", "", "", "square-208.svg"],
  [209, 14.95861500087481, "David Ellsworth", "January 2026", "", "", "square-209.svg"],
  [210, 14.97413341886404, "M.Z. Arslanov, S.A. Mustafin, and Z.K. Shangitbayev", "March 2019", "", "", "square-210.svg"],
  [223, 15.0, "", "", "Hiroshi Nagamochi", "2005", "square-224.svg"],
  [224, 15.0, "", "", "Hiroshi Nagamochi", "2005", "square-224.svg"],
  [226, 15.53553390593273, "Frits Göbel", "early 1979", "", "", "square-226.svg"],
  [227, 15.57106781186547, "David Ellsworth", "January 2025", "", "", "square-227.svg"],
  [228, 15.60902282132495, "David Ellsworth", "November 2024", "", "", "square-228.svg"],
  [229, 15.65685424949238, "Frits Göbel", "early 1979", "", "", "square-229.svg"],
  [230, 15.68292682926829, "David W. Cantrell", "January 2025", "", "", "square-230.svg"],
  [231, 15.70710678118654, "Frits Göbel", "early 1979", "", "", "square-231.svg"],
  [232, 15.77817459305202, "Frits Göbel", "early 1979", "", "", "square-233.svg"],
  [233, 15.77817459305202, "Frits Göbel", "early 1979", "", "", "square-233.svg"],
  [234, 15.82287565553229, "David Ellsworth", "December 2024", "", "", "square-234.svg"],
  [235, 15.82660563342856, "David Ellsworth and David W. Cantrell", "January 2025", "", "", "square-235.svg"],
  [236, 15.87607539315201, "David Ellsworth", "November 2024", "", "", "square-236.svg"],
  [237, 15.91421356237309, "David Ellsworth", "December 2024", "", "", "square-237.svg"],
  [238, 15.93965520031394, "David Ellsworth", "February 2026", "", "", "square-238.svg"],
  [239, 15.95635358406308, "David Ellsworth", "January 2026", "", "", "square-239.svg"],
  [240, 15.97556282833087, "Károly Hajba", "September 2015", "", "", "square-240.svg"],
  [241, 15.9908051781052, "M.Z. Arslanov, S.A. Mustafin, and Z.K. Shangitbayev", "March 2019", "", "", "square-241.svg"],
  [254, 16.0, "", "", "Hiroshi Nagamochi", "2005", "square-255.svg"],
  [255, 16.0, "", "", "Hiroshi Nagamochi", "2005", "square-255.svg"],
  [257, 16.53553390593273, "Frits Göbel", "early 1979", "", "", "square-257a.svg"],
  [258, 16.57106781186547, "David Ellsworth", "January 2025 (using a computer program he wrote) which continues the $s(26)$", "", "", "square-258.svg"],
  [259, 16.60257141234448, "David Ellsworth", "December 2024", "", "", "square-259.svg"],
  [260, 16.65685424949238, "Frits Göbel", "early 1979", "", "", "square-260b.svg"],
  [261, 16.68292682926829, "David W. Cantrell", "January 2025", "", "", "square-261.svg"],
  [262, 16.70710678118654, "Frits Göbel", "early 1979", "", "", "square-262.svg"],
  [263, 16.74264068711928, "David Ellsworth", "January 2025", "", "", "square-263.svg"],
  [264, 16.77817459305202, "Frits Göbel", "early 1979", "", "", "square-265.svg"],
  [265, 16.77817459305202, "Frits Göbel", "early 1979", "", "", "square-265.svg"],
  [266, 16.8230620828378, "", "", "", "", "square-266.svg"],
  [267, 16.84666719284348, "Károly Hajba", "November 2024", "", "", "square-267.svg"],
  [268, 16.87931143465371, "David Ellsworth", "November 2024", "", "", "square-268.svg"],
  [269, 16.90596764828402, "David Ellsworth", "November 2024", "", "", "square-269.svg"],
  [270, 16.94062059800744, "David Ellsworth", "February 2026", "", "", "square-270.svg"],
  [271, 16.95499909412532, "David Ellsworth", "February 2026", "", "", "square-271.svg"],
  [272, 16.96971602419903, "Lars Cleemann between 1991 and 1998. Bounded the $s(n^2-n)=n$ conjecture to $n \\lt 17$. Converted", "December 2024 from the $s(210)$ found by M", "", "", "square-272.svg"],
  [273, 16.98820725030513, "M.Z. Arslanov, S.A. Mustafin, and Z.K. Shangitbayev", "March 2019", "", "", "square-273.svg"],
  [287, 17.0, "", "", "Hiroshi Nagamochi", "2005", "square-288.svg"],
  [288, 17.0, "", "", "Hiroshi Nagamochi", "2005", "square-288.svg"],
  [290, 17.53553390593273, "Frits Göbel", "early 1979", "", "", "square-291.svg"],
  [291, 17.53553390593273, "Frits Göbel", "early 1979", "", "", "square-291.svg"],
  [292, 17.60257141234448, "Károly Hajba", "September 2024 and adapting and extending the $s(37)$ improvement found by David W", "", "", "square-292.svg"],
  [293, 17.63414634146341, "David Ellsworth", "December 2024", "", "", "square-293.svg"],
  [294, 17.65685424949238, "Frits Göbel", "early 1979", "", "", "square-294.svg"],
  [295, 17.70710678118654, "Frits Göbel", "early 1979", "", "", "square-296.svg"],
  [296, 17.70710678118654, "Frits Göbel", "early 1979", "", "", "square-296.svg"],
  [297, 17.74106074604732, "David Ellsworth", "January 2025", "", "", "square-297.svg"],
  [298, 17.77817459305202, "Frits Göbel", "early 1979", "", "", "square-298.svg"],
  [299, 17.82287565553229, "Erich Friedman", "1997", "", "", "square-299.svg"],
  [300, 17.82412338847854, "David Ellsworth", "January 2025", "", "", "square-300.svg"],
  [301, 17.8688915555743, "David W. Cantrell", "September 2002", "", "", "square-301.svg"],
  [302, 17.88674602860566, "David Ellsworth", "December 2024 (including re-adapting the techniques from the $s(130)$ and $s(129)$/$s(206)$ he improved)", "", "", "square-302.svg"],
  [303, 17.93125509556197, "David Ellsworth", "April 2026", "", "", "square-303.svg"],
  [304, 17.94910783564662, "David Ellsworth", "May 2026", "", "", "square-304.svg"],
  [305, 17.96066201401205, "David Ellsworth", "March 2026", "", "", "square-305.svg"],
  [306, 17.96913960675661, "David Ellsworth", "February 2026", "", "", "square-306.svg"],
  [307, 17.9827220157961, "M.Z. Arslanov, S.A. Mustafin, and Z.K. Shangitbayev", "March 2019", "", "", "square-307.svg"],
  [322, 18.0, "", "", "Hiroshi Nagamochi", "2005", "square-323.svg"],
  [323, 18.0, "", "", "Hiroshi Nagamochi", "2005", "square-323.svg"],
  [626, 25.5208152801713, "David Ellsworth", "January 2025", "", "", "square-626.svg"],
  [1453, 38.62799971540531, "David Ellsworth", "December 2024", "", "", "square-1453.svg"],
  [1765, 42.48797851186022, "Károly Hajba", "November 2024", "", "", "square-1765.svg"],
  [1850, 43.48797851186022, "Michael J. Kearney and Peter Shiu", "June 2001", "", "", "square-1850.svg"],
  [2043, 45.69642783940993, "David Ellsworth", "December 2024", "", "", "square-2043.svg"],
];

const NOTES: Record<number, string> = {
  1: "The square grid attains the elementary area lower bound.",
  4: "The square grid attains the elementary area lower bound.",
  9: "The square grid attains the elementary area lower bound.",
  17: "Bidwell's construction builds on a packing by Pertti Hämäläinen (1980); optimality is unproved.",
  18: "The pictured alternative with fewer rotated squares is by Mats Gustafsson (1981).",
  19: "Wainwright's construction builds on a packing by Charles F. Cottingham (1979).",
  29: "Found by Thomas Schadt in December 2025, then optimized by David Ellsworth in December 2025.",
};

const VERIFIED_ON = "2026-09-26";

export const SQUARE_RECORDS: SquareRecord[] = [...ROWS, ...EXTRA_ROWS].map(([count, side, author = "", date = "", provedBy = "", proofDate = "", figure = ""]) => {
  const hasCandidate = count <= LOCAL_CANDIDATE_MAX;
  return {
    count,
    side,
    hasCandidate,
    reference: {
      status: provedBy !== "" || [1, 4, 9].includes(count) ? "proved" : "best_known",
      value: side,
      unit: "container side",
      author,
      date,
      proved_by: provedBy,
      proof_date: proofDate,
      verified_on: VERIFIED_ON,
      note: NOTES[count] ?? "",
      // The lab's own drawing where the layout ships with the interface, the
      // page's own SVG otherwise; a record with neither shows no picture at all.
      preview: figure !== "" ? SQUARES_FIGURE_BASE + figure
        : hasCandidate ? `/catalog/squares/square-${count}.svg` : "",
      sources: [{ label: "David Ellsworth · Squares in Squares", url: SQUARES_SOURCE }],
    },
  };
});

export function builtInReference(problemId: string): ProblemReference | null {
  const square = SQUARE_RECORDS.find((record) => `squares-${record.count}-in-smallest-square` === problemId);
  if (square) return square.reference;
  if (problemId === "circle-25-in-square") return {
    status: "proved", value: 2, unit: "packing scale", author: "",
    date: "", proved_by: "G. Wengerodt", proof_date: "1987",
    verified_on: "2026-09-26",
    note: "Twenty-five equal circles in a 10 × 10 square. Scale 2 gives diameter 2; the displayed 5 × 5 grid is optimal.",
    preview: "/catalog/examples/circle-25.svg", sources: [
      { label: "G. Wengerodt's proof · cited in packing survey", url: "https://inf.u-szeged.hu/~pszabo/Pub/45survey.pdf" },
    ],
  };
  return null;
}

export function squareProblem(record: SquareRecord): ProblemDoc {
  const count = record.count;
  return {
    problem_id: `squares-${count}-in-smallest-square`,
    name: `${count} squares in the smallest square`,
    description: `Pack ${count} unit squares inside the smallest possible square. The reference side ${record.side} is ${record.reference.status === "proved" ? "proved optimal" : "the smallest published construction, not a proved optimum"}.`,
    seed: count,
    shape: { type: "regular_polygon", sides: 4, side: 1 },
    objective: { type: "minimize_container", count, container: "square" },
    rotation: { type: "rotation_policy", mode: "free", angles: [0] },
    constraints: [],
    // Only a record whose layout ships locally can be opened on the record; the
    // others are initialized as a grid by the engine, which their card announces.
    metadata: {
      reference: record.reference,
      ...(record.hasCandidate
        ? { catalog_candidate_url: `/catalog/candidates/squares-${count}.json` }
        : {}),
    },
  };
}

export function readReference(value: unknown): ProblemReference | null {
  if (value === null || typeof value !== "object") return null;
  const record = value as Partial<ProblemReference>;
  if (!["proved", "best_known", "none"].includes(record.status ?? "")) return null;
  return {
    status: record.status ?? "none",
    value: typeof record.value === "number" && Number.isFinite(record.value) ? record.value : null,
    unit: typeof record.unit === "string" ? record.unit : "",
    author: typeof record.author === "string" ? record.author : "",
    date: typeof record.date === "string" ? record.date : "",
    proved_by: typeof record.proved_by === "string" ? record.proved_by : "",
    proof_date: typeof record.proof_date === "string" ? record.proof_date : "",
    verified_on: typeof record.verified_on === "string" ? record.verified_on : "",
    note: typeof record.note === "string" ? record.note : "",
    preview: typeof record.preview === "string" ? record.preview : "",

    sources: Array.isArray(record.sources) ? record.sources.filter((source): source is ReferenceSource =>
      source !== null && typeof source === "object" && typeof source.label === "string" && typeof source.url === "string") : [],
  };
}
