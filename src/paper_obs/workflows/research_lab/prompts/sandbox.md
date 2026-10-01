
## Computing with Python

`run_python` runs a program of yours in an isolated sandbox, with numpy and the standard
library. Use it to compute what you would otherwise guess: exact positions on a ring or a
lattice, the angle a symmetry repeats at, the distance two edges must keep, a small search over
a few parameters. `PROBLEM` holds what the engine says of the problem, the shape's size
included; `CURRENT` holds the arrangement under work.

End every program with `{"placements": [{"x": ..., "y": ..., "rotation": ...}, ...]}`,
adding `"scale"` where it is free, and the engine judges that arrangement at once, as
`place_shapes` would. A program that only prints costs a call and judges nothing.

Do not write your own overlap or containment tests: the engine answers them exactly, and
`polish` closes small gaps and overlaps better than a search by hand. Compute the idea's
positions, return them, read the verdict, then polish. Each run takes a few seconds and starts
afresh, so compute a whole arrangement per program rather than one number.
