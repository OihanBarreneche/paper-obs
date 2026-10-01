/**
 * The arena canvas: the compiled outline, the parts as grabbable handles, and the
 * polygon being drawn.
 *
 * Nothing here decides geometry. A part is drawn from the `path` the engine
 * compiled for it — its own primitive, so a disc is drawn and grabbed as a disc —
 * a gesture either translates a part, scales one of its own numbers or turns it
 * about the part's own origin, and the edited list is only ever reported when the
 * gesture ends: one compile per edit.
 *
 * What a pointer may grab is that same path, and nothing else: the browser's own
 * hit test on the filled outline is what decides whether a press landed on a part,
 * so the box a primitive was compiled inside is never a shape anyone can select.
 * That box still places the corner grip, which is what a hand reaches for to
 * resize a part whose outline is round.
 *
 * The one control the canvas draws for itself is the turn grip: a circular arrow
 * standing just outside the right of the selected part's own box, at the middle of
 * that edge. Where the turn is measured is unchanged — the origin of the part's own
 * frame, which is where the domain turns it, a part being `Translate(Rotate(...))`
 * — and the grip therefore needs no geometry to place: the engine sent the box and
 * the origin, the arrow is sized and set down in screen pixels, and the angle
 * between a pointer and a point is the interface's own arithmetic. The arrow is the
 * whole control: the disc it used to sit on and the line that used to join it to
 * the origin are gone, because a control that already stands outside what it acts
 * on needs neither, and it is kept inside the visible canvas so that a part in the
 * corner of a magnified window still has a control on screen. `Shift`, held through
 * a turn, rounds it to the fifteen-degree steps the shapes canvas' grip and the
 * inspector's knob snap to. The grip is drawn after the parts and stops its own
 * press, so it is on top of them, a drag on a part is never read as a turn, and a
 * press on the grip is neither a pan nor the click that clears the selection.
 * Three pixels of stroke is what its own paint is, though, and a hand a few pixels
 * off it would miss: a transparent band a tolerance wider than that stroke takes
 * the press, it stops at the edge of the part, and the middle of the ring stays
 * clear, so a press on the part or on the canvas behind the ring still reaches
 * what is there. During a turn it orbits the part's origin and stays inside
 * the visible canvas.
 *
 * The picture is not the engine's alone while a gesture is in flight: the outline
 * the engine sent is displaced by the pointer, scaled about the part's own
 * placement by the size the hand is pulling, or turned about the part's own origin
 * by the angle the pointer makes there, so the part follows the hand instead of the
 * round trip. When the part under the hand is the whole stack, the compiled outline
 * is carried along with it — so a part, and the outline it compiles into, are the
 * only two things drawn here that the engine did not answer with, and its next
 * answer replaces both.
 *
 * The picture lives in two nested groups: the outer one is the window the
 * application shares with the shapes canvas, the inner one flips y once, so every
 * coordinate the engine sent is used as it is.
 *
 * A left press grabs a part or clears the selection on the background. The middle
 * button pans. A right click opens the creation menu anywhere.
 *
 * Drawing a polygon is the one mode this canvas has, and it ends on the canvas
 * itself: the last vertex carries a small `Done` and `Cancel`, a right click
 * finishes the polygon where it is — the gesture a drawing is reached for — and
 * `Enter` is the named equivalent of a button nobody should have to go looking for.
 * A drawing in flight owns the right button: finishing it is what that click means,
 * so no creation menu opens over the vertices already placed.
 *
 * The selection is the application's, not this canvas's: a press on a part reports
 * the index it landed on and a press on the background reports none, and the part
 * that is highlighted, gripped and edited is the one the application hands back.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from "react";

import type { ArenaPartDoc, ArenaPartParams, Bounds, Point, ShapePrimitiveDoc } from "../types";
import { sceneBox, useInsideCanvas, viewBoxOf } from "../viewport";
import type { CanvasViewport } from "../viewport";
import { ZoomControl } from "./ZoomControl";
import { useI18n } from "../i18n";

import "./ArenaCanvas.css";

export type ArenaCanvasProps = {
  framingKey: number;
  problemId: string | null;
  /** The parts as the application holds them, in stack order; the first is the base. */
  parts: ArenaPartDoc[];
  /** The compiled outline of the whole stack, as the engine drew it. */
  path: string;
  /** The frame the viewBox covers — the same one the shapes canvas uses. */
  frame: Bounds | null;
  /** The shapes already placed, drawn faded as context. */
  shapes: ShapePrimitiveDoc[];
  /** False when the arena cannot be edited. */
  editable: boolean;
  /** The part the application has selected, or null; index into `parts`. */
  selectedPart: number | null;
  /** Report the selected part: the index of the handle clicked, or null for none. */
  onSelectPart: (index: number | null) => void;
  /** The shared window: magnification, pan, and pointer-to-world conversion. */
  canvas: CanvasViewport;
  /** The part being drawn, or null. Its points are WORLD coordinates. */
  drawing: { points: Point[] } | null;
  /** A click on the background: where it landed, in world units and in client coordinates. */
  onRequestCreate: (world: Point, client: Point) => void;
  /** While drawing: the world point of the click that adds a vertex. */
  onDrawPoint: (world: Point) => void;
  /** The vertices drawn so far are the polygon: it is finished. */
  onFinishDrawing: () => void;
  /** The drawing is thrown away. */
  onCancelDrawing: () => void;
  /** Replace the whole stack (move, resize, reorder, delete, op change). */
  onChange: (parts: ArenaPartDoc[]) => void;
  /** What a canvas with no picture yet says in place of the drawing. */
  emptyText?: string;
};

/** The canvas fills the space its host gives it; `preserveAspectRatio` does the rest. */
const CANVAS_STYLE = { width: "100%", height: "100%" };

/** Side of the corner grip and of a vertex mark, in screen pixels. */
const GRIP_SIZE = 10;

/**
 * Radius of the turn grip's arrow, in screen pixels — what a hand has to hit.
 *
 * The arrow is drawn in a unit frame whose own circle is one unit around the
 * point it is centred on, and scaled by this radius: the whole control is this
 * many screen pixels across, whatever the arena's own scale is, and it is the
 * same radius the shapes canvas' own turn grip keeps.
 */
const ARROW_RADIUS = 12;

/**
 * Gap between the part's box and the arrow's left edge, in screen pixels.
 *
 * The arrow stands outside what it acts on, close enough to read as belonging to
 * it, and the gap is what a part's own outline — up to 2.5 pixels of it — is given
 * room in.
 */
const ARROW_GAP = 8;

/** Half of the arrow's own stroke, in screen pixels: what its paint adds around the arc. */
const ARROW_HALF_STROKE = 1.5;

/**
 * How far the arrow's own pixels reach around the point it is centred on: its
 * radius, plus the half of its stroke the stylesheet draws outside it.
 *
 * This is what the control is kept inside the canvas by, so none of it is ever
 * off screen.
 */
const ARROW_REACH = ARROW_RADIUS + 2;

/**
 * How far beyond its own paint a press still takes hold of the arrow, in screen
 * pixels.
 *
 * Three pixels of stroke is what the whole control is, and a hand a few pixels
 * off it misses what it is reaching for; the arrow therefore answers to presses
 * this far outside its stroke as well. Nothing is drawn for it: the band is
 * transparent, and the arrow itself is unchanged.
 */
const ARROW_TOLERANCE = 11;

/**
 * Radius, in screen pixels, of the clear patch left at the middle of the arrow.
 *
 * The tolerance is spent inward as well, but only this far: the ring is 21 pixels
 * across inside, and a press at its middle — far from the stroke in every
 * direction — is a press on what is underneath it, exactly as it is today.
 */
const ARROW_HOLE = 5.5;

/** Outer edge of the band that takes the press: the stroke's own outer edge, plus the tolerance. */
const HIT_OUTER = ARROW_RADIUS + ARROW_HALF_STROKE + ARROW_TOLERANCE;

/**
 * The band itself, in screen pixels: the radius of its middle, and its width.
 *
 * The band is drawn as a circle whose stroke it is, so these are the circle's own
 * two numbers — expressed in the arrow's frame, where one unit is `ARROW_RADIUS`
 * screen pixels, which is what makes them the same pixels the arrow is sized in.
 */
const HIT_MIDDLE = (HIT_OUTER + ARROW_HOLE) / 2;
const HIT_WIDTH = HIT_OUTER - ARROW_HOLE;

/**
 * The line the band is cut along, in the arrow's own units: the edge of the part's
 * own box.
 *
 * The grip stands `ARROW_GAP + ARROW_RADIUS` screen pixels to the right of that
 * edge whatever part is selected, so the cut is one number for every part, and it
 * is what keeps the tolerance from reaching back over the part: the band is a ring
 * about the arrow, and its far side would otherwise take a press that lands on the
 * part itself.
 */
const HIT_CUT = -(ARROW_GAP + ARROW_RADIUS) / ARROW_RADIUS;

/** How far the band reaches, in the arrow's own units: its outer edge, which is the room the cut is given. */
const HIT_REACH = HIT_OUTER / ARROW_RADIUS;

/** The steps a turn rounds to while `Shift` is held — the shapes canvas' own step. */
const TURN_STEP = 15;

/** Below this, a gesture turned nothing: it is the pointer's own trembling, not a turn. */
const TURN_SLOP = 0.5;

/**
 * Smallest size a corner drag may leave a primitive with, in world units.
 *
 * The panel's size controls enforce the same floor, so neither can ask for a size
 * the other could not have left behind.
 */
export const MIN_SIZE = 0.5;

/** How far the pointer may wander before a press stops counting as a click. */

/**
 * Fewest vertices a drawn polygon may be finished with.
 *
 * The engine refuses fewer in its own words, so the gesture that finishes one —
 * the panel's `Done` is disabled below this too — does not ask for what it would
 * only be told off about.
 */
const MIN_VERTICES = 3;

/** How far the finish control stands off the vertex it belongs to, in screen pixels. */
const FINISH_OFFSET = 14;

/**
 * The finish control before it has been measured, hidden rather than unmounted:
 * a control the browser has not laid out yet has no size to keep inside the canvas.
 */
const UNPLACED = { visibility: "hidden" } as const;

/** What every gesture holds: the pointer that opened it, and the part it grabbed. */
type Grabbed = {
  pointerId: number;
  index: number;
  /** Where the pointer was, in world units, when the press started. */
  pointer: Point;
  /** The part as it was then; a gesture changes only these numbers. */
  part: ArenaPartDoc;
};

/** A gesture that changes where a part is, or how big it is. */
type Dragged = Grabbed & { mode: "move" | "resize" };

/**
 * A gesture that turns a part about the origin of its own frame.
 *
 * A turn is measured by the angle the pointer travels around that origin, so what
 * is worth keeping is where the pointer last stood about it and how far it has come
 * since — step by step, because `atan2` folds back on itself past the half turn and
 * a turn read from the press each time would jump there.
 */
type Turn = Grabbed & {
  mode: "turn";
  /** Where the pointer stood about the part's origin, in degrees, at the last report. */
  last: number;
  /** How far the pointer has travelled round that origin, in degrees, added up. */
  degrees: number;
};

type Drag = Dragged | Turn;

/**
 * What a gesture is holding: the part as the press left it, and how far the hand
 * has taken it — a displacement in world units, and, for a turn, an angle.
 *
 * It is drawn over the engine's answer until that answer arrives, which is what
 * makes a drag continuous instead of a report.
 */
type Pending = {
  index: number;
  mode: Drag["mode"];
  /** The part the hand grabbed; a gesture changes only these numbers. */
  part: ArenaPartDoc;
  dx: number;
  dy: number;
  /** How far a turn has taken the part, in degrees; nothing for the other gestures. */
  turn: number;
};

export function ArenaCanvas({
  framingKey,
  problemId,
  parts,
  path,
  frame,
  shapes,
  editable,
  selectedPart,
  onSelectPart,
  canvas,
  drawing,
  onRequestCreate,
  onDrawPoint,
  onFinishDrawing,
  onCancelDrawing,
  onChange,
  emptyText,
}: ArenaCanvasProps) {
  const { t } = useI18n();
  const dragRef = useRef<Drag | null>(null);
  const [dragging, setDragging] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [pixelsPerUnit, setPixelsPerUnit] = useState<number | null>(null);
  /** Where the finish control is drawn, in this component's own box. */
  const [finishAt, setFinishAt] = useState<Point | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const worldRef = useRef<SVGGElement | null>(null);
  const finishRef = useRef<HTMLDivElement | null>(null);
  const stableFrame = useRef<{ problemId: string | null; key: number; bounds: Bounds } | null>(null);
  if (frame !== null && (stableFrame.current?.problemId !== problemId || stableFrame.current.key !== framingKey)) {
    stableFrame.current = { problemId, key: framingKey, bounds: frame };
  }
  const shownFrame = stableFrame.current?.bounds ?? frame;

  const box = shownFrame === null ? null : sceneBox(shownFrame);
  const boxWidth = box?.width ?? 0;
  const boxHeight = box?.height ?? 0;
  const node = canvas.node;
  // The grip and the vertex marks are drawn in world units but must stay the same
  // size on screen, so the rendered size of the canvas is measured for that
  // conversion alone — at the magnification the window is at.
  const perUnit = pixelsPerUnit === null ? null : pixelsPerUnit * canvas.zoom;
  const gripSize = perUnit === null ? null : GRIP_SIZE / perUnit;

  /**
   * The part the turn grip belongs to, and where it sits in the stack, or null when
   * there is no grip to draw.
   *
   * A grip is a control for one named part, so it exists only while the application
   * has one selected and the arena is editable — and never while a polygon is being
   * drawn, since a drawing owns every press on the canvas and a control standing
   * among the vertices would take the click that adds the next one.
   */
  const selected = selectedPart === null ? undefined : parts[selectedPart];
  const turnable =
    selectedPart === null || selected === undefined || !editable || drawing !== null
      ? null
      : { index: selectedPart, part: selected };

  // The grip is sized and placed in screen pixels, so it keeps the same size, and
  // the same small gap from the part, whatever the window is magnified to; the
  // measured scale is what converts them into the frame's units, exactly as it
  // does for the corner grip. It stands outside the part's own box, at the middle
  // of its right edge — the box is the one the engine compiled, and no size of the
  // outline is measured here — and it is pulled back inside the canvas so a part
  // in the corner of a magnified window still has its control on screen. While a
  // hand is on it, it is drawn where the pointer is instead of beside the part, so
  // the turn looks like the hand's own; the clamp is the one it is already kept
  // by, which is what keeps it on screen when the pointer leaves the canvas
  // mid-gesture.
  const arrowScale = perUnit === null ? null : ARROW_RADIUS / perUnit;
  const placedGrip: Point | null =
    turnable === null || perUnit === null
      ? null
      : [
          turnable.part.bounds[2] + (ARROW_GAP + ARROW_RADIUS) / perUnit,
          (turnable.part.bounds[1] + turnable.part.bounds[3]) / 2,
        ];
  const angle = pending?.mode === "turn" && pending.index === turnable?.index
    ? pending.turn * Math.PI / 180 : 0;
  const turnGripPoint: Point | null = placedGrip === null || turnable === null || angle === 0
    ? placedGrip
    : [
        turnable.part.offset[0] + (placedGrip[0] - turnable.part.offset[0]) * Math.cos(angle)
          - (placedGrip[1] - turnable.part.offset[1]) * Math.sin(angle),
        turnable.part.offset[1] + (placedGrip[0] - turnable.part.offset[0]) * Math.sin(angle)
          + (placedGrip[1] - turnable.part.offset[1]) * Math.cos(angle),
      ];
  const turnGrip = useInsideCanvas(node, worldRef, turnGripPoint, ARROW_REACH);

  useEffect(() => {
    if (node === null || boxWidth === 0) {
      return;
    }
    const measure = () => {
      const { width, height } = node.getBoundingClientRect();
      setPixelsPerUnit(Math.min(width / boxWidth, height / boxHeight));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    measure();
    return () => observer.disconnect();
  }, [node, boxWidth, boxHeight]);

  /** The vertex the drawing is waiting at, or null when there is nothing to finish. */
  const lastVertex: Point | null =
    drawing === null || drawing.points.length === 0
      ? null
      : (drawing.points[drawing.points.length - 1] ?? null);

  /**
   * Finish the drawing, if the engine would accept it.
   *
   * The vertices the pointer has placed are the polygon; asking for it with fewer
   * than three is asking for a refusal, so the gesture says nothing instead.
   */
  const finishDrawing = () => {
    if (drawing !== null && drawing.points.length >= MIN_VERTICES) {
      onFinishDrawing();
    }
  };

  /**
   * Where the finish control stands: just above the vertex it belongs to.
   *
   * The conversion is the browser's own — the group that mirrors y is the frame
   * the vertices are in, so its screen matrix is the whole of the arithmetic — and
   * the result is clamped to the box, because a control that followed a vertex out
   * of sight could not be pressed. Measured rather than read from the component's
   * own state: it is a button, and where it ends up is the browser's business.
   */
  useLayoutEffect(() => {
    const host = hostRef.current;
    const group = worldRef.current;
    const control = finishRef.current;
    const matrix = group === null ? null : group.getScreenCTM();
    if (host === null || control === null || matrix === null || lastVertex === null) {
      if (finishAt !== null) {
        setFinishAt(null);
      }
      return;
    }
    const spot = new DOMPoint(lastVertex[0], lastVertex[1]).matrixTransform(matrix);
    const hostBox = host.getBoundingClientRect();
    const left = spot.x - hostBox.left + host.scrollLeft;
    const top = spot.y - hostBox.top + host.scrollTop;
    const next: Point = [
      Math.min(Math.max(left + FINISH_OFFSET, 0), Math.max(0, hostBox.width - control.offsetWidth)),
      Math.min(
        Math.max(top - FINISH_OFFSET - control.offsetHeight, 0),
        Math.max(0, hostBox.height - control.offsetHeight),
      ),
    ];
    setFinishAt((current) =>
      current !== null && current[0] === next[0] && current[1] === next[1] ? current : next,
    );
  });

  /**
   * `Enter` finishes the drawing, which is what the button beside the last vertex
   * says and what a right click does.
   *
   * It is listened for here rather than with the window's other shortcuts because
   * only a drawing in flight has anything to finish, and it stands aside while a
   * field is being typed into — the panel's size boxes are a keystroke away from a
   * drawing, and `Enter` there means what the field says it means.
   */
  useEffect(() => {
    if (!editable || drawing === null) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" ||
          target.tagName === "SELECT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      if (event.key !== "Enter" || drawing.points.length < MIN_VERTICES) {
        return;
      }
      event.preventDefault();
      onFinishDrawing();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [editable, drawing, onFinishDrawing]);

  /** Report a whole list, numbered the way the engine numbers parts. */
  const send = (next: ArenaPartDoc[]) => {
    onChange(next.map((part, index) => (part.index === index ? part : { ...part, index })));
  };

  /** The numbers a gesture is asking for, read from the part it grabbed. */
  const asked: ArenaPartParams | null =
    pending === null ? null : resized(pending.part.params, pending.dx, pending.dy);

  /**
   * The transform the compiled outline takes while the hand is on it — only when
   * the part under the hand is the whole stack.
   *
   * The outline is one picture of every part at once: with anything on top of the
   * base, what a push makes of the union is the engine's to say, and it says it
   * when the gesture ends. A single part is the whole arena, so displacing it
   * displaces the outline, pulling its size scales it about its own placement, and
   * turning it turns it about its own origin.
   */
  const following =
    pending === null || asked === null || parts.length !== 1
      ? undefined
      : pending.mode === "move"
        ? `translate(${pending.dx} ${pending.dy})`
        : pending.mode === "turn"
          ? turnedAbout(pending.part, pending.turn)
          : scaleAbout(pending.part, asked);

  useEffect(() => {
    // The compile of a gesture is the picture from then on, and it is what leaves
    // the part exactly where the hand left it — but never while the hand is down:
    // an answer to an earlier gesture must not pull the part out from under it.
    if (dragRef.current === null) {
      setPending(null);
    }
  }, [parts]);

  /** The list a gesture is producing right now, from where the pointer is. */
  const dragged = (drag: Dragged, pointer: Point): ArenaPartDoc[] => {
    const dx = pointer[0] - drag.pointer[0];
    const dy = pointer[1] - drag.pointer[1];
    // The list is rebuilt from the parts the application holds, so an answer the
    // engine sends during the gesture is not undone by the gesture's own numbers.
    return parts.map((part, index) => {
      if (index !== drag.index) {
        return part;
      }
      // A drag is a translation of the placement or a scaling of the primitive;
      // what that means for the outline is the engine's business, not ours.
      return drag.mode === "move"
        ? { ...part, offset: [drag.part.offset[0] + dx, drag.part.offset[1] + dy] }
        : { ...part, params: resized(drag.part.params, dx, dy) };
    });
  };

  const press = (
    part: ArenaPartDoc,
    index: number,
    mode: Drag["mode"],
    event: ReactPointerEvent<SVGElement>,
  ) => {
    // Only a plain left press grabs. While a polygon is being drawn every click on
    // the canvas is a vertex, so a handle under the pointer must not start a
    // gesture instead — and must let the press through to the background, which is
    // what adds it.
    if (!editable || drawing !== null || event.button !== 0) {
      return;
    }
    const pointer = canvas.worldAt(event);
    if (pointer === null) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    // A press on a part is a command on the stack, not a text edit: the keyboard
    // focus leaves whatever field was holding it, so a `Delete` reaches the part
    // instead of being typed into a number. `preventDefault` above is what kept the
    // field focused, so the release is asked for here.
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
    // Capturing keeps the gesture alive once the pointer leaves the small grip it
    // started on, and stopping here keeps the press off the background.
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current =
      mode === "turn"
        ? {
            pointerId: event.pointerId,
            index,
            mode,
            pointer,
            part,
            // The turn is measured from the angle the press landed at, so taking
            // hold of the grip turns nothing by itself, exactly as grabbing a shape
            // with `Alt` does not.
            last: angleAbout(part.offset, pointer),
            degrees: 0,
          }
        : { pointerId: event.pointerId, index, mode, pointer, part };
    // Grabbing a part chooses it as well: the marked card and the highlighted
    // outline are the ones the application's `Delete` acts on.
    onSelectPart(index);
    setDragging(true);
  };

  /**
   * Where the hand is: the picture is redrawn from here, not from the release.
   *
   * A move and a pull report the pointer's own displacement since the press, and
   * are drawn from it; a turn reports how far the pointer has travelled round the
   * part's own origin — so what is drawn under the hand is exactly what the gesture
   * will report when it ends.
   */
  const move = (event: ReactPointerEvent<SVGElement>) => {
    const drag = dragRef.current;
    if (drag === null || drag.pointerId !== event.pointerId) {
      return;
    }
    const pointer = canvas.worldAt(event);
    if (pointer === null) {
      return;
    }
    if (drag.mode === "turn") {
      // The step since the last report, added up: a turn is measured by how far the
      // pointer went round, not by the angle it stands at. The step is folded into a
      // half turn — `atan2` wraps at ±180°, so the raw difference jumps there — and
      // the positive remainder is what brings a negative step back into that range.
      const about = angleAbout(drag.part.offset, pointer);
      const step = about - drag.last;
      drag.degrees += ((((step + 180) % 360) + 360) % 360) - 180;
      drag.last = about;
    }
    setPending({
      index: drag.index,
      mode: drag.mode,
      part: drag.part,
      dx: pointer[0] - drag.pointer[0],
      dy: pointer[1] - drag.pointer[1],
      turn: drag.mode === "turn" ? turnedDegrees(drag.degrees, event.shiftKey) : 0,
    });
  };

  const release = (event: ReactPointerEvent<SVGElement>) => {
    const drag = dragRef.current;
    if (drag === null || drag.pointerId !== event.pointerId) {
      return;
    }
    dragRef.current = null;
    setDragging(false);
    if (drag.mode === "turn") {
      const settled = turnedDegrees(drag.degrees, event.shiftKey);
      if (Math.abs(settled) < TURN_SLOP) {
        // A press that turned nothing is a click: the part goes back to the picture
        // and nothing is written, as a knob let go where it started writes nothing.
        setPending(null);
        return;
      }
      // The whole turn is reported here, once, as a step from the angle the engine
      // last sent: that is what makes one drag one edit and one entry in the undo
      // stack. The pending picture stays until this compile answers, since dropping
      // it now would send the part back to where the previous compile had it for as
      // long as the round trip takes.
      setPending({ index: drag.index, mode: "turn", part: drag.part, dx: 0, dy: 0, turn: settled });
      send(
        parts.map((part, index) =>
          // A part the engine answered without an angle is one that is not turned,
          // so the turn is counted from zero rather than from `undefined` — which
          // would put `NaN` in the request and in the transform under the hand.
          index === drag.index ? { ...part, angle: (part.angle ?? 0) + settled } : part,
        ),
      );
      return;
    }
    const pointer = canvas.worldAt(event);
    if (pointer === null) {
      setPending(null);
      return;
    }
    // A press that never moved is a selection, not an edit: nothing to compile.
    if (pointer[0] === drag.pointer[0] && pointer[1] === drag.pointer[1]) {
      setPending(null);
      return;
    }
    // The pending picture stays until this compile answers: dropping it now would
    // send the part back to where the previous compile had it, for as long as the
    // round trip takes.
    send(dragged(drag, pointer));
  };

  /** The middle button moves the window, wherever it is pressed. */
  const grabWindow = (event: ReactPointerEvent<SVGElement>) => {
    if (event.button !== 1) {
      return;
    }
    // Read in the capture phase, and stopped there: a middle press that landed on
    // a part or its grip must not also reach the part's own handler.
    event.stopPropagation();
    canvas.beginPan(event);
  };

  const background = (event: ReactPointerEvent<SVGElement>) => {
    if (event.button !== 0) {
      return;
    }
    const world = canvas.worldAt(event);
    if (world === null) {
      return;
    }
    // While a polygon is being drawn, the background is the drawing surface: a
    // click there is a vertex, and the window does not move.
    if (editable && drawing !== null) {
      onDrawPoint(world);
      return;
    }
    // An empty left press clears the part selection. Panning belongs to the middle button.
    onSelectPart(null);
  };

  /** Open the creation menu at the right-clicked world point. */
  const askForCreate = (event: ReactMouseEvent<SVGSVGElement>) => {
    const world = canvas.worldAt(event);
    if (drawing === null && editable && world !== null) {
      onRequestCreate(world, [event.clientX, event.clientY]);
    }
  };

  /** A right click completes a drawn polygon, or opens creation elsewhere. */
  const askForCreateHere = (event: ReactMouseEvent<SVGSVGElement>) => {
    event.preventDefault();
    if (editable && drawing !== null) {
      finishDrawing();
      return;
    }
    askForCreate(event);
  };

  /**
   * A double click is the other half of the same gesture: create here.
   *
   * A double click that landed on a part is a selection, not a creation — the
   * part's own press already read it — so only the background opens the menu.
   */
  const askForCreateDbl = (event: ReactMouseEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest("[data-part-index]") === null) {
      askForCreate(event);
    }
  };

  return (
    <div className="canvas-host" ref={hostRef}>
      {shownFrame === null ? (
        <p className="muted">{emptyText ?? t("No arena loaded yet — pick an example, then edit its arena.")}</p>
      ) : (
        <>
          <div className="canvas-sheet">
          <svg
            ref={canvas.ref}
            className={dragging ? "arena-canvas canvas--dragging" : "arena-canvas"}
            viewBox={viewBoxOf(shownFrame)}
            preserveAspectRatio="xMidYMid meet"
            style={CANVAS_STYLE}
            onPointerDownCapture={grabWindow}
            onPointerDown={background}
            onContextMenu={askForCreateHere}
            onDoubleClick={askForCreateDbl}
          >
            <g transform={canvas.transform}>
              <g ref={worldRef} transform="scale(1 -1)">
                {/* The compiled arena, carried by the hand only while it is the
                    whole stack; `following` says when. */}
                <path className="arena" d={path} transform={following} />
                <path className="arena arena--sketch" d={path} transform={following} />
                {shapes.map((primitive) => (
                  <g
                    key={primitive.shape_id}
                    transform={`translate(${primitive.center[0]} ${primitive.center[1]})`}
                  >
                    {primitive.kind === "circle" ? (
                      <circle className="arena-part--context" cx={0} cy={0} r={primitive.radius} />
                    ) : (
                      <polygon className="arena-part--context" points={relativePoints(primitive)} />
                    )}
                  </g>
                ))}
                {editable &&
                  parts.map((part, index) => {
                    const isSelected = index === selectedPart;
                    const classes = ["arena-part"];
                    if (index === 0) {
                      classes.push("arena-part--base");
                    }
                    if (part.op === "difference") {
                      classes.push("arena-part--cut");
                    }
                    if (isSelected) {
                      classes.push("arena-part--selected");
                    }
                    const holding =
                      pending !== null && asked !== null && pending.index === index
                        ? { pending, asked }
                        : null;
                    // The primitive's own outline, which is what the pointer reaches
                    // for and what a press on it drags. It is shown where the engine
                    // put it, and — while the hand is on it — where the hand is
                    // asking for it, by the engine's own numbers scaled by the pull.
                    // The grip keeps to the box the engine compiled: a round outline
                    // has to be resizable from somewhere a hand can find.
                    const grip =
                      holding === null ? part.bounds : gripBox(holding.pending, holding.asked);
                    // The box's own top-right corner, and nothing else of it.
                    const [, minY, maxX] = grip;
                    return (
                      <g key={`part-${index}`} data-part-index={index}>
                        <path
                          className={classes.join(" ")}
                          d={part.path}
                          transform={
                            holding === null
                              ? undefined
                              : heldTransform(holding.pending, holding.asked)
                          }
                          onPointerDown={(event) => press(part, index, "move", event)}
                          onPointerMove={move}
                          onPointerUp={release}
                          onPointerCancel={release}
                        />
                        {isSelected && gripSize !== null && part.params.kind !== "polygon" && (
                          <rect
                            className="arena-grip"
                            x={maxX - gripSize / 2}
                            y={minY - gripSize / 2}
                            width={gripSize}
                            height={gripSize}
                            onPointerDown={(event) => press(part, index, "resize", event)}
                            onPointerMove={move}
                            onPointerUp={release}
                            onPointerCancel={release}
                          />
                        )}
                      </g>
                    );
                  })}
                {turnable !== null && turnGrip !== null && arrowScale !== null && (
                  // Drawn after the parts, so it is on top of them and a press on it
                  // is never a press on the part underneath. Its own press stops in
                  // `press`, which is what keeps the background — the pan, and the
                  // click that clears the selection — out of it.
                  <g
                    className="arena-turn-grip"
                    transform={`translate(${turnGrip[0]} ${turnGrip[1]})`}
                    onPointerDown={(event) =>
                      press(turnable.part, turnable.index, "turn", event)
                    }
                    onPointerMove={move}
                    onPointerUp={release}
                    onPointerCancel={release}
                  >
                    {/* The arrow, and the whole of the control: drawn in a unit frame
                        whose own circle is one unit around the point the group is
                        translated to, and scaled to the screen pixels it is measured
                        in. It nearly closes its circle, so a hand reads it as a turn,
                        and the gap it leaves is where its head points. */}
                    <g transform={`scale(${arrowScale})`}>
                      <circle className="arena-turn-grip__core" r={1.25} />
                      {/* The band a press has to land in, drawn first so the arrow is
                          over it: a circle whose own stroke is the band, transparent,
                          and wider than the arrow's stroke by the tolerance. One unit
                          of this frame is `ARROW_RADIUS` screen pixels, so the band's
                          two numbers are screen pixels too, and the painted arrow is
                          not one pixel different for it. It is cut at the edge of the
                          part's own box, which is where the part begins: the
                          tolerance is room beside the arrow, not a press taken off the
                          part it turns. */}
                      <clipPath id="arena-turn-grip-cut">
                        <rect
                          x={HIT_CUT}
                          y={-HIT_REACH}
                          width={HIT_REACH - HIT_CUT}
                          height={2 * HIT_REACH}
                        />
                      </clipPath>
                      <circle
                        className="arena-turn-grip__hit"
                        r={HIT_MIDDLE / ARROW_RADIUS}
                        strokeWidth={HIT_WIDTH / ARROW_RADIUS}
                        clipPath="url(#arena-turn-grip-cut)"
                      />
                      <path
                        className="arena-turn-grip__mark"
                        d="M -0.866 -0.5 A 1 1 0 1 0 0.1392 -0.9903"
                      />
                      <path
                        className="arena-turn-grip__mark"
                        d="M 0.1657 -0.4362 L 0.1392 -0.9903 L -0.354 -0.7362"
                      />
                    </g>
                  </g>
                )}
                {editable && drawing !== null && (
                  <g>
                    {/* The polygon being drawn: the vertices placed so far are the
                        shape, closed as soon as there are three of them, and drawn
                        over the parts because it is what the pointer is building. */}
                    <path
                      className="arena-part arena-part--drawing"
                      d={pathThrough(drawing.points)}
                      pointerEvents="none"
                    />
                    {gripSize !== null &&
                      drawing.points.map(([x, y], at) => (
                        <circle
                          key={`vertex-${at}`}
                          className="arena-vertex"
                          cx={x}
                          cy={y}
                          r={gripSize / 2}
                        />
                      ))}
                  </g>
                )}
              </g>
            </g>
          </svg>
          <ZoomControl view={canvas} />
          </div>
          {editable && drawing !== null && lastVertex !== null && (
            <div
              ref={finishRef}
              className="arena-finish"
              style={
                finishAt === null
                  ? UNPLACED
                  : { left: `${finishAt[0]}px`, top: `${finishAt[1]}px` }
              }
            >
              <button
                className="button button--primary button--small"
                type="button"
                disabled={drawing.points.length < MIN_VERTICES}
                title={t("finish the polygon here")}
                onClick={finishDrawing}
              >
                {t("Done")}
              </button>
              <button
                className="button button--ghost button--small"
                type="button"
                onClick={onCancelDrawing}
              >
                {t("Cancel")}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/**
 * How much longer each axis of a primitive becomes when the pointer moves by
 * `dx, dy`.
 *
 * The canvas mirrors y once, so world y grows upwards while the pointer itself
 * moves downwards: the two axes therefore read the same pull with opposite signs.
 * A pull away from the part enlarges it and a pull into it shrinks it, on either
 * axis — the part follows the hand instead of running away from it. A rectangle
 * and an ellipse have a size per axis; a disc and a regular polygon have a single
 * one, so both axes take the larger of the two pulls.
 */
function pull(kind: ArenaPartParams["kind"], dx: number, dy: number): [number, number] {
  if (kind === "rect" || kind === "ellipse") {
    return [dx, -dy];
  }
  const size = Math.max(dx, -dy);
  return [size, size];
}

/** The one size a primitive's box is drawn from, so a pull can be read as a scale. */
function sizeOf(params: ArenaPartParams): [number, number] {
  switch (params.kind) {
    case "rect":
      return [params.width, params.height];
    case "disk":
      return [params.radius, params.radius];
    case "ellipse":
      return [params.a, params.b];
    case "regular_ngon":
      return [params.circumradius, params.circumradius];
    case "polygon":
      // A polygon is the points the user drew: it has no size to read.
      return [1, 1];
  }
}

/** The numbers a pull leaves on a primitive: each axis on its own, or one size. */
function resized(params: ArenaPartParams, dx: number, dy: number): ArenaPartParams {
  const [growX, growY] = pull(params.kind, dx, dy);
  switch (params.kind) {
    case "rect":
      return {
        kind: "rect",
        width: Math.max(MIN_SIZE, params.width + growX),
        height: Math.max(MIN_SIZE, params.height + growY),
      };
    case "disk":
      // One size, and `pull` reports the same growth on both axes for one.
      return { kind: "disk", radius: Math.max(MIN_SIZE, params.radius + growX) };
    case "ellipse":
      return {
        kind: "ellipse",
        a: Math.max(MIN_SIZE, params.a + growX),
        b: Math.max(MIN_SIZE, params.b + growY),
      };
    case "regular_ngon":
      return {
        kind: "regular_ngon",
        sides: params.sides,
        circumradius: Math.max(MIN_SIZE, params.circumradius + growX),
      };
    case "polygon":
      // A polygon is the points the user drew: it has no size to scale, and its
      // handle only moves it.
      return params;
  }
}

/** The scale a pull asks of a primitive: the size it will have over the size it has. */
function scaleOf(from: ArenaPartParams, to: ArenaPartParams): [number, number] {
  const [wasX, wasY] = sizeOf(from);
  const [willX, willY] = sizeOf(to);
  return [willX / wasX, willY / wasY];
}

/**
 * The angle of a point about a pole, in degrees, counter-clockwise.
 *
 * That is the whole of a turn's arithmetic, and it is the interface's own: the pole
 * is the origin of the part's own frame, which is where the engine turns the part,
 * and the angle is measured in the world the engine sent — the group that mirrors y
 * is what makes a counter-clockwise pointer a positive turn, as everywhere else in
 * this project.
 */
function angleAbout(pole: Point, point: Point): number {
  return (Math.atan2(point[1] - pole[1], point[0] - pole[0]) * 180) / Math.PI;
}

/** The transform that turns what is drawn about the part's own origin. */
function turnedAbout(part: ArenaPartDoc, turn: number): string {
  const [x, y] = part.offset;
  return `rotate(${turn} ${x} ${y})`;
}

/**
 * The turn a gesture has reached, rounded to the fifteen-degree steps a hand thinks
 * in while `Shift` is held — the same step the shapes canvas' turn grip and the
 * inspector's knob take, so the two canvases turn alike.
 */
function turnedDegrees(degrees: number, snap: boolean): number {
  return snap ? Math.round(degrees / TURN_STEP) * TURN_STEP : degrees;
}

/**
 * The box a part's grip is drawn at while a gesture holds the part.
 *
 * The box the engine sent is taken as it is: a move displaces it by the pointer's
 * own displacement, and a pull scales it about the part's placement — a primitive
 * is defined at the origin and placed there, so that is the point its size grows
 * around. The outline is drawn by a transform of the same pull, so the two agree
 * corner for corner; this one is here because the grip is a mark on screen rather
 * than a coordinate of the picture. A turn leaves the box where the engine put it:
 * the box is what the corner grip is drawn from, and the outline is the only thing
 * a turn moves.
 */
function gripBox(pending: Pending, asked: ArenaPartParams): Bounds {
  const [minX, minY, maxX, maxY] = pending.part.bounds;
  if (pending.mode === "turn") {
    return [minX, minY, maxX, maxY];
  }
  if (pending.mode === "move") {
    return [
      minX + pending.dx,
      minY + pending.dy,
      maxX + pending.dx,
      maxY + pending.dy,
    ];
  }
  const [scaleX, scaleY] = scaleOf(pending.part.params, asked);
  const [centreX, centreY] = pending.part.offset;
  return [
    centreX + (minX - centreX) * scaleX,
    centreY + (minY - centreY) * scaleY,
    centreX + (maxX - centreX) * scaleX,
    centreY + (maxY - centreY) * scaleY,
  ];
}

/**
 * The transform that grows what is drawn around the part's own placement.
 *
 * A pull changes the primitive's own numbers, so it is applied in the primitive's
 * frame: for a turned part the axes of the pull are the part's own, and a rectangle
 * pulled along its length grows along its length whichever way it points.
 */
function scaleAbout(part: ArenaPartDoc, asked: ArenaPartParams): string {
  const [scaleX, scaleY] = scaleOf(part.params, asked);
  const [x, y] = part.offset;
  return `translate(${x} ${y}) rotate(${part.angle}) scale(${scaleX} ${scaleY}) rotate(${-part.angle}) translate(${-x} ${-y})`;
}

/**
 * How a part's own outline is shown while the hand is on it.
 *
 * A move carries it by the pointer's own displacement, a pull grows it about the
 * part's placement and a turn rotates it about the part's own origin: the same three
 * answers the engine would give, taken from the numbers the engine sent, so what is
 * under the hand is what the gesture will report when it ends.
 */
function heldTransform(pending: Pending, asked: ArenaPartParams): string {
  if (pending.mode === "move") {
    return `translate(${pending.dx} ${pending.dy})`;
  }
  return pending.mode === "turn" ? turnedAbout(pending.part, pending.turn) : scaleAbout(pending.part, asked);
}

/**
 * The polygon being drawn, through the vertices already placed.
 *
 * Closed once there are three of them, since that is the region a finished part
 * would be — and the same three the engine is asked for when the drawing ends.
 */
function pathThrough(points: Point[]): string {
  const line = points.map(([x, y], at) => `${at === 0 ? "M" : "L"} ${x} ${y}`).join(" ");
  return points.length >= MIN_VERTICES ? `${line} Z` : line;
}

/**
 * The corners of a placed shape relative to its own centre.
 *
 * The engine sends them in world coordinates and the shape is drawn inside a group
 * already translated to its centre, so the centre has to come off here — otherwise
 * the translation would be counted twice.
 */
function relativePoints(primitive: ShapePrimitiveDoc): string {
  const [centerX, centerY] = primitive.center;
  return (primitive.points ?? [])
    .map(([x, y]) => `${x - centerX},${y - centerY}`)
    .join(" ");
}
