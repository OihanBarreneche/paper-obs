/**
 * The arena, drawn from the view the engine returned.
 *
 * The component draws exactly the primitives it is given: the arena path, the
 * disc centres and radii, the polygon corners. It never derives a coordinate of
 * its own — dragging reports the pointer's displacement in the domain's units,
 * and lets the application decide which shapes move and ask the engine to judge
 * the result.
 *
 * Two nested groups carry the picture: the outer one is the window (the
 * magnification and the displacement shared with the arena canvas), the inner
 * one flips y once, so every coordinate below is a coordinate of the domain.
 * The engine's own SVG flips the picture the same way, and the two cannot
 * disagree about where a shape is. Text is the exception and is counter-flipped
 * where it is drawn, because flipped text is unreadable.
 *
 * The engine's primitive says where a shape was when it was last judged, the
 * placement says where the user has just put it. The group translation follows
 * the placement, so a shape follows the pointer at once instead of waiting for
 * the engine's answer; only its origin moves, its radius and corners stay the
 * ones the engine computed.
 *
 * A left press chooses or moves a shape; a left drag on the background draws a
 * selection rectangle. The middle button pans and a right click asks what to
 * add. Modifier-click changes the selection without opening a move gesture.
 *
 * A left press with `Alt` held turns the selection in place instead of moving it:
 * one shape turns about its own centre, and a group about its common box centre.
 * Near a five-degree guide the turn settles on it; `Shift` forces the steps.
 *
 * The turn is the one number this component works out for itself, and only
 * because a pointer's angle about a centre is the interface's own arithmetic: no
 * radius, no area, no verdict is computed here. It is also written once, on
 * release, through the same path as everything else — the degrees a gesture has
 * reached so far are a draft the drawing adds to the picture, so the shape turns
 * under the pointer without a single round trip, and the engine judges the result
 * exactly once, when the pointer comes back up. One gesture is one edit, one
 * verdict and one entry in the undo stack.
 *
 * A turn is also something the canvas shows a way to do: while a shape is
 * selected, a circular arrow stands outside the selected polygon's face, or the
 * group's right edge, and dragging it turns the selection exactly as `Alt` does.
 * Its face anchor comes from the engine's view. The arrow is the whole
 * control — the disc it used to sit on, and the line that used to join it to the
 * selection, are gone, because a control that is already outside what it acts on
 * needs neither — and it is drawn after the shapes and stops its own press, so a
 * drag on a shape still moves it, and a press on the grip is never read as one on
 * the shape under it. A transparent disc and band make the small icon easy to
 * grab, including its centre. It is kept inside the visible canvas, so
 * a selection in the corner of a magnified window still has its control on screen,
 * where a hand can reach it. During rotation it orbits the chosen centre.
 */

import { useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from "react";

import type { Bounds, CandidateDoc, Point, ScaleBoundsDoc, ShapePrimitiveDoc, ViewDoc } from "../types";
import { sceneBox, useInsideCanvas, viewBoxOf } from "../viewport";
import type { CanvasViewport } from "../viewport";
import { ZoomControl } from "./ZoomControl";
import { useI18n } from "../i18n";
import { snapAngle } from "../snap";
import { orientationColor } from "../orientationColors";

export type PackingCanvasProps = {
  readOnly?: boolean;
  orientationHighlights?: boolean;
  showIds?: boolean;
  onToggleIds?: () => void;
  framingKey: number;
  view: ViewDoc | null;
  candidate: CandidateDoc | null;
  /** Identifiers of the selected shapes, in selection order. */
  selectedIds: string[];
  /** Replace the selection with these identifiers. */
  onSelect: (shapeIds: string[]) => void;
  /** The window shared with the arena canvas. */
  canvas: CanvasViewport;
  /** A right click asks what to add there: the world point, and where to show it. */
  onRequestCreate: (world: Point, at: Point) => void;
  /** A drag begins: the application snapshots the candidate for the undo stack. */
  onGestureStart: () => void;
  /** Pointer moved, in world units since the gesture started. */
  onDrag: (dx: number, dy: number, shapeIds: string[], contactDistance: number) => void;
  /**
   * A turn gesture ended: how far the selection turned, in degrees, counter-clockwise.
   *
   * It is reported once per gesture, when the pointer comes back up, and never
   * while it is down: the turn is drawn from here until then, and the engine is
   * asked to judge it once.
   */
  onTurn: (degrees: number) => void;
  onGestureEnd: () => void;
  /**
   * The engine's interval for one copy's local size, or null when the family has
   * no such degree of freedom. It is what makes the in-canvas resize handle
   * appear: the handle is offered exactly where the inspector's size slider is.
   */
  localScaleBounds?: ScaleBoundsDoc | null;
  /**
   * A local-size edit in flight, the same write the inspector's slider makes.
   *
   * The handle reports every move while it is dragged and the application asks
   * the engine to judge the arrangement, so the copy grows under the hand. The
   * engine remains the only judge: the handle sends the same request as the
   * slider, it does not derive a size of its own.
   */
  onLocalScale?: (shapeId: string, scale: number) => void;
  /** The local-size gesture ended: one undo step, as the slider's release is. */
  onLocalScaleCommit?: () => void;
  /**
   * Draw the copies translucent and multiplied, so the arena shows through and a
   * point covered by several copies darkens with the number of layers over it.
   *
   * It is on for a covering, whose copies overlap by meaning, and off for every
   * packing, whose copies are solid. The canvas only paints this boolean: it does
   * not decide it, and the arena and composer canvases never take it.
   */
  translucent?: boolean;
};

/** How far the pointer may wander before a press stops counting as a click. */
const CLICK_SLOP = 3;

/** Below this, a gesture turned nothing: it is the pointer's own trembling, not a turn. */
const TURN_SLOP = 0.5;

/**
 * Radius of the turn grip's arrow, in screen pixels — what a hand has to hit.
 *
 * The arrow is drawn in a unit frame whose own circle is one unit around the
 * point it is centred on, and scaled by this radius: the whole control is this
 * many screen pixels across, whatever the window is magnified to.
 */
const ARROW_RADIUS = 12;

/**
 * Gap between the selection's box and the arrow's left edge, in screen pixels.
 *
 * The arrow stands outside what it acts on, close enough to read as belonging to
 * it, and the gap is what a shape's own outline — up to 2.5 pixels of it — is
 * given room in.
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
 * The line the band is cut along, in the arrow's own units: the edge of the
 * selection's box.
 *
 * The grip stands `ARROW_GAP + ARROW_RADIUS` screen pixels to the right of that
 * edge whatever is selected, so the cut is one number for every selection, and it
 * is what keeps the tolerance from reaching back over the object: the band is a
 * ring about the arrow, and its far side would otherwise take a press that lands
 * on the object itself.
 */
const HIT_CUT = -(ARROW_GAP + ARROW_RADIUS) / ARROW_RADIUS;

/** How far the band reaches, in the arrow's own units: its outer edge, which is the room the cut is given. */
const HIT_REACH = HIT_OUTER / ARROW_RADIUS;

/** The canvas fills the space its host gives it; `preserveAspectRatio` does the rest. */
const CANVAS_STYLE = { width: "100%", height: "100%" };

/** Placing a shape is what the whole canvas does, so the whole canvas says so. */

/** While the window is being dragged, the pointer says so. */
const PAN_STYLE = { ...CANVAS_STYLE, cursor: "grabbing" };

type SceneProps = Omit<PackingCanvasProps, "view" | "candidate"> & {
  view: ViewDoc;
  candidate: CandidateDoc;
};

/**
 * A press that may become a drag.
 *
 * Only the pointer's own displacement is kept: which shapes move is the
 * application's decision, taken from the selection the press left behind, so the
 * component never holds a position it would have to keep in step with the
 * candidate.
 */
type Drag = {
  pointerId: number;
  /** Screen displacement uses the scale at press time, even if a derived arena grows. */
  client: Point;
  pixelsPerUnit: number;
  /** True once the pointer has moved: until then the press is still a click. */
  started: boolean;
  ids: string[];
};

/**
 * A press that turns rather than moves.
 *
 * The pointer's angle about the shape's own centre is what drives the turn, and
 * it is counted step by step: every report adds the folded difference from the
 * last one, so a pointer that travels all the way round its centre is a full
 * turn instead of a jump when it passes the halfway mark.
 */
type Turning = {
  pointerId: number;
  /**
   * The centre the pointer's angle is measured about: the shape's own as drawn
   * for an `Alt` press on it, and the middle of the selection's box for a press
   * on the grip.
   */
  pole: Point;
  /** Where the pointer stood, in degrees about that pole, at the last report. */
  last: number;
  /** How far the pointer has turned since the press, in degrees, unfolded. */
  degrees: number;
  /** The first shape's current angle, so a near-right-angle turn lands exactly on it. */
  baseAngle: number;
  /** The degrees the drawing is showing, including any angle guide. */
  shown: number;
  /** The shapes the turn applies to: the selection the press left behind. */
  ids: string[];
};

/**
 * A turn the engine has not drawn yet.
 *
 * The picture is one round trip behind the placement, so a shape drawn from the
 * picture alone would snap back to where it was the moment the pointer came up,
 * and look like a gesture that had undone itself. The degrees of the turn are
 * therefore kept beside the picture they were measured against, and dropped when
 * the engine's next picture arrives with the turn already on it.
 */
type Draft = {
  ids: string[];
  degrees: number;
  /** The picture these degrees are added to; another one means this draft is done. */
  picture: ViewDoc;
};
type DragDraft = { ids: string[]; dx: number; dy: number; picture: ViewDoc };
type Marquee = { pointerId: number; start: Point; current: Point; base: string[] };

/**
 * A press on the in-canvas resize handle of one copy.
 *
 * Every size scales about the placement's own origin, and a uniform local scale
 * multiplies the distance from that origin to every point of the outline by the
 * same factor. The handle therefore reads a scale from the ratio of the pointer's
 * distance to that origin: it is the interface's own arithmetic on two world
 * points, and the size it proposes is judged by the engine like any other.
 */
type ScaleDrag = {
  pointerId: number;
  shapeId: string;
  /** The copy's own origin, the point every size scales about. */
  pole: Point;
  /** The copy's local size when the press started. */
  startScale: number;
  /** The pointer's distance from the pole when the press started. */
  reach: number;
  /** True once the pointer moved, so a click on the grip writes nothing. */
  moved: boolean;
};

/** Side of the resize handle, in screen pixels -- the arena canvas' own grip size. */
const RESIZE_GRIP = 10;

export function PackingCanvas(props: PackingCanvasProps) {
  const { t } = useI18n();
  const { view, candidate } = props;
  return (
    <div className="canvas-host">
      {view === null || candidate === null ? (
        <p className="muted">
          {t("No candidate loaded yet — choose a problem.")}
        </p>
      ) : (
        <Scene
          view={view}
          framingKey={props.framingKey}
          readOnly={props.readOnly}
          orientationHighlights={props.orientationHighlights}
          showIds={props.showIds}
          onToggleIds={props.onToggleIds}
          candidate={candidate}
          selectedIds={props.selectedIds}
          onSelect={props.onSelect}
          canvas={props.canvas}
          onRequestCreate={props.onRequestCreate}
          onGestureStart={props.onGestureStart}
          onDrag={props.onDrag}
          onTurn={props.onTurn}
          onGestureEnd={props.onGestureEnd}
          localScaleBounds={props.localScaleBounds}
          onLocalScale={props.onLocalScale}
          onLocalScaleCommit={props.onLocalScaleCommit}
          translucent={props.translucent}
        />
      )}
    </div>
  );
}

function Scene({
  view,
  framingKey,
  candidate,
  readOnly,
  orientationHighlights,
  showIds,
  onToggleIds,
  selectedIds,
  onSelect,
  canvas,
  onRequestCreate,
  onGestureStart,
  onDrag,
  onTurn,
  onGestureEnd,
  localScaleBounds,
  onLocalScale,
  onLocalScaleCommit,
  translucent,
}: SceneProps) {
  const { t } = useI18n();
  const dragRef = useRef<Drag | null>(null);
  const marqueeRef = useRef<Marquee | null>(null);
  const turnRef = useRef<Turning | null>(null);
  const scaleRef = useRef<ScaleDrag | null>(null);
  const worldRef = useRef<SVGGElement | null>(null);
  // Where the resize handle is drawn while a hand is on it: it follows the
  // pointer, because the copy's own new size only arrives with the engine's next
  // picture and a control left behind would look stuck.
  const [scaleGripAt, setScaleGripAt] = useState<Point | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dragDraft, setDragDraft] = useState<DragDraft | null>(null);
  const [marquee, setMarquee] = useState<Marquee | null>(null);
  const [dragging, setDragging] = useState(false);
  const [pixelsPerUnit, setPixelsPerUnit] = useState<number | null>(null);
  // The union overlay is presentation, like the ID labels: the engine sends the
  // path only when the application asks, and this only shows or hides it.
  const [showUnion, setShowUnion] = useState(false);
  // A picture without a union is a problem that does not have one; leaving the
  // toggle on would make the next covering open with its overlay already shown.
  useEffect(() => {
    if (view.union === undefined && showUnion) {
      setShowUnion(false);
    }
  }, [view.union, showUnion]);

  const stableFrame = useRef<{ problemId: string; key: number; bounds: Bounds } | null>(null);
  if (stableFrame.current?.problemId !== view.problem_id || stableFrame.current.key !== framingKey) {
    stableFrame.current = { problemId: view.problem_id, key: framingKey, bounds: view.frame };
  }
  const frame = stableFrame.current.bounds;
  const box = sceneBox(frame);
  const selected = new Set(selectedIds);

  // A draft belongs to the picture it was measured against, and to no other: any
  // later picture is an answer from the engine, drawn from a document that already
  // carries the turn. The drawing reads that comparison, so it never waits for the
  // state to be cleared below.
  const turn = draft !== null && draft.picture === view ? draft : null;
  useEffect(() => {
    if (draft !== null && draft.picture !== view) {
      setDraft(null);
    }
  }, [draft, view]);
  useEffect(() => {
    if (dragDraft !== null && dragDraft.picture !== view) setDragDraft(null);
  }, [dragDraft, view]);

  // The grip is a control rather than a coordinate of the picture, so it is
  // measured and placed in screen pixels: that is what this measurement is for.
  // A canvas letterboxes the frame inside the element it fills, so the scale is
  // the smaller of the two, and the window magnifies it — a grip stays the same
  // size on screen at 40% and at 400%.
  useEffect(() => {
    const svg = canvas.node;
    if (svg === null) {
      return;
    }
    const measure = () => {
      const { width, height } = svg.getBoundingClientRect();
      setPixelsPerUnit(Math.min(width / box.width, height / box.height));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(svg);
    measure();
    return () => observer.disconnect();
  }, [box.width, box.height, canvas.node]);

  // The application pairs `onGestureStart` with `onGestureEnd` to record one undo
  // step per drag; a gesture left open by an unmount would leave the snapshot of
  // the next drag wrong, so it is closed here. The callback is read through a ref
  // so that only an unmount can close a gesture: a re-render must not.
  const gestureEndRef = useRef(onGestureEnd);
  useEffect(() => {
    gestureEndRef.current = onGestureEnd;
  }, [onGestureEnd]);
  const localScaleEndRef = useRef(onLocalScaleCommit);
  useEffect(() => {
    localScaleEndRef.current = onLocalScaleCommit;
  }, [onLocalScaleCommit]);

  useEffect(() => {
    return () => {
      const drag = dragRef.current;
      dragRef.current = null;
      if (drag !== null && drag.started) {
        gestureEndRef.current();
      }
      // A resize left open by an unmount is closed the same way: the edit was
      // already reported, and the gesture end is what records the undo step.
      const scaling = scaleRef.current;
      scaleRef.current = null;
      if (scaling !== null && scaling.moved) {
        localScaleEndRef.current?.();
      }
    };
  }, []);

  const perUnit = pixelsPerUnit === null ? null : pixelsPerUnit * canvas.zoom;

  // The grip is sized and placed in screen pixels, so it keeps the same size, and
  // the same small gap from the selection, whatever the window is magnified to;
  // the measured scale is what converts them into the frame's units. A single
  // shape uses its engine-supplied face anchor; a group uses its right edge.
  // The control orbits the selection centre during a turn.
  const gripBox = selectionBox(view, candidate, selected);
  const oneShape = selectedIds.length === 1
    ? view.shapes.find((shape) => shape.shape_id === selectedIds[0]) : undefined;
  const onePlacement = oneShape && candidate.placements.find((item) => item.shape_id === oneShape.shape_id);
  const centreShift: Point = oneShape && onePlacement
    ? [onePlacement.x - oneShape.center[0], onePlacement.y - oneShape.center[1]] : [0, 0];
  const gripAnchor: Point | null = oneShape?.turn_anchor
    ? [oneShape.turn_anchor[0] + centreShift[0], oneShape.turn_anchor[1] + centreShift[1]]
    : gripBox === null ? null : [gripBox[2], (gripBox[1] + gripBox[3]) / 2];
  const turnPole: Point | null = onePlacement
    ? [onePlacement.x, onePlacement.y]
    : gripBox === null ? null : [(gripBox[0] + gripBox[2]) / 2, (gripBox[1] + gripBox[3]) / 2];
  const arrowScale = perUnit === null ? null : ARROW_RADIUS / perUnit;
  const direction = oneShape?.turn_direction ?? [1, 0];
  const baseGrip: Point | null =
    gripAnchor === null || perUnit === null
      ? null
      : [gripAnchor[0] + direction[0] * (ARROW_GAP + ARROW_RADIUS) / perUnit,
        gripAnchor[1] + direction[1] * (ARROW_GAP + ARROW_RADIUS) / perUnit];
  const turnAngle = turn !== null && turn.ids.length > 0
    ? turn.degrees * Math.PI / 180 : 0;
  const placedGrip: Point | null = baseGrip === null || turnPole === null || turnAngle === 0
    ? baseGrip
    : [
        turnPole[0] + (baseGrip[0] - turnPole[0]) * Math.cos(turnAngle)
          - (baseGrip[1] - turnPole[1]) * Math.sin(turnAngle),
        turnPole[1] + (baseGrip[0] - turnPole[0]) * Math.sin(turnAngle)
          + (baseGrip[1] - turnPole[1]) * Math.cos(turnAngle),
      ];
  const grip = useInsideCanvas(canvas.node, worldRef, placedGrip, ARROW_REACH);

  // The resize handle lives at the bottom-right of the selected copy's own box,
  // and only where the family gives a copy its own size: `localScaleBounds` is
  // that family's engine interval and nothing else's. The screen bottom-right is
  // (maxX, minY) because the world group flips y once. While a hand is on it, it
  // is drawn at the pointer instead.
  const scalePlacement = selectedIds.length === 1 && localScaleBounds != null
    ? onePlacement ?? null
    : null;
  const scaleBox = scalePlacement !== null ? gripBox : null;
  const gripSizeWorld = perUnit === null ? null : RESIZE_GRIP / perUnit;
  const scaleHandle: Point | null =
    scaleGripAt ?? (scaleBox === null ? null : [scaleBox[2], scaleBox[1]]);

  /**
   * Take the keyboard back for the canvas.
   *
   * A press on the drawing is how the user says "now work on this", but the window
   * shortcuts refuse to fire while a field is focused, so a press that leaves the
   * focus in the inspector makes the keyboard go on editing the number the user
   * has finished with: Delete does nothing, the arrows move a caret instead of a
   * shape. Dropping the focus here is what makes those keys mean the selection
   * again. The arena canvas does the same on its own press.
   */
  const releaseFocus = () => {
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  };

  const press = (shapeId: string, pole: Point, event: ReactPointerEvent<SVGElement>) => {
    // Only a plain left press grabs. The middle button belongs to the window, and
    // the right one asks for the creation menu, which is the canvas's business.
    if (event.button !== 0) {
      return;
    }
    if (readOnly) { event.stopPropagation(); onSelect([shapeId]); return; }
    const pointer = canvas.worldAt(event);
    if (pointer === null) {
      return;
    }
    // Capturing keeps the pointer events coming once it leaves the element, so a
    // drag that leaves the canvas still reports where it is; stopping here keeps
    // the press from also reading as a press on the background.
    event.preventDefault();
    event.stopPropagation();
    releaseFocus();

    const additive = event.ctrlKey || event.metaKey || event.shiftKey;
    const wasSelected = selected.has(shapeId);
    let next = selectedIds;
    if (additive) {
      // A modifier-click trims or grows the selection instead of replacing it.
      next = wasSelected
        ? selectedIds.filter((id) => id !== shapeId)
        : [...selectedIds, shapeId];
    } else if (!wasSelected) {
      next = [shapeId];
    }
    if (next !== selectedIds) {
      onSelect(next);
    }

    // The drag moves whatever the press leaves selected: pressing a shape that is
    // already selected must not shrink the group, and a modifier-press that takes
    // a shape out of the selection leaves nothing of it to drag.
    const movable = !additive;
    dragRef.current = null;
    turnRef.current = null;
    if (!movable) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);

    // `Alt` turns what a plain press would move, in place. The pole is the centre
    // the shape is already drawn about — the placement the drawing follows, which
    // the engine sent — and the angle the press landed at is what the turn is
    // measured against, so grabbing a shape never turns it by itself.
    if (event.altKey) {
      turnRef.current = {
        pointerId: event.pointerId,
        pole,
        last: angleAbout(pole, pointer),
        degrees: 0,
        baseAngle: next.length === 1
          ? candidate.placements.find((item) => item.shape_id === next[0])?.rotation ?? 0 : 0,
        shown: 0,
        ids: next,
      };
      return;
    }
    const matrix = worldRef.current?.getScreenCTM();
    const pixelsPerUnit = matrix === undefined || matrix === null
      ? 0
      : Math.hypot(matrix.a, matrix.b);
    dragRef.current = {
      pointerId: event.pointerId,
      client: [event.clientX, event.clientY],
      pixelsPerUnit,
      started: false,
      ids: next,
    };
  };

  /**
   * A press on the grip turns the selection, exactly as `Alt` turns it.
   *
   * The grip is the canvas's own control, so its press stops here: the
   * background must not read it as a click on the arena, a shape under it must
   * not read it as a press on itself, and the pointer is captured so the turn
   * keeps reporting after it has left the small disc it started on. The pole is
   * the point the grip is anchored on, and the angle the press landed at is what
   * the turn is measured against — so taking hold of the grip turns nothing by
   * itself, exactly as grabbing a shape with `Alt` does not.
   */
  const grabGrip = (event: ReactPointerEvent<SVGElement>) => {
    const anchor = turnPole;
    if (event.button !== 0 || anchor === null) {
      return;
    }
    const pointer = canvas.worldAt(event);
    if (pointer === null) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
    turnRef.current = {
      pointerId: event.pointerId,
      pole: anchor,
      last: angleAbout(anchor, pointer),
      degrees: 0,
      baseAngle: selectedIds.length === 1 ? onePlacement?.rotation ?? 0 : 0,
      shown: 0,
      ids: selectedIds,
    };
  };

  /**
   * A press on the in-canvas resize handle starts a local-size gesture.
   *
   * The handle is the canvas's own control, so its press stops here: the
   * background must not read it as a click on the arena, and the copy under it
   * must not read it as a press on itself. The pointer is captured, and every
   * move proposes a size by the ratio of the pointer's distance to the copy's own
   * origin -- the interface's own arithmetic on two world points -- which the
   * application sends to the engine exactly as the inspector's slider does.
   */
  const grabScale = (event: ReactPointerEvent<SVGElement>) => {
    const bounds = localScaleBounds;
    if (event.button !== 0 || scalePlacement === null || bounds == null) {
      return;
    }
    const pointer = canvas.worldAt(event);
    if (pointer === null) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
    const pole: Point = [scalePlacement.x, scalePlacement.y];
    const reach = Math.hypot(pointer[0] - pole[0], pointer[1] - pole[1]);
    scaleRef.current = {
      pointerId: event.pointerId,
      shapeId: scalePlacement.shape_id,
      pole,
      startScale: scalePlacement.scale ?? candidate.scale ?? 1,
      // A press exactly on the origin has no ratio to read; a hair of reach keeps
      // the arithmetic finite and the gesture starts from the copy's own size.
      reach: reach > 0 ? reach : 1e-9,
      moved: false,
    };
  };

  const move = (event: ReactPointerEvent<SVGElement>) => {
    const scaling = scaleRef.current;
    if (scaling !== null && scaling.pointerId === event.pointerId) {
      const bounds = localScaleBounds;
      const pointer = canvas.worldAt(event);
      if (bounds == null || pointer === null) {
        return;
      }
      const reach = Math.hypot(pointer[0] - scaling.pole[0], pointer[1] - scaling.pole[1]);
      const proposed = scaling.startScale * (reach / scaling.reach);
      scaling.moved = true;
      setScaleGripAt(pointer);
      onLocalScale?.(scaling.shapeId, Math.min(Math.max(proposed, bounds.low), bounds.high));
      return;
    }
    const turning = turnRef.current;
    if (turning !== null && turning.pointerId === event.pointerId) {
      const pointer = canvas.worldAt(event);
      if (pointer === null) {
        return;
      }
      // The step since the last report, added up: a turn is measured by how far
      // the pointer went round, not by the angle it stands at.
      const angle = angleAbout(turning.pole, pointer);
      turning.degrees += foldedStep(angle - turning.last);
      turning.last = angle;
      const shown = turnedDegrees(turning.degrees, turning.baseAngle, event.shiftKey);
      if (shown !== turning.shown) {
        turning.shown = shown;
        setDraft({ ids: turning.ids, degrees: shown, picture: view });
      }
      return;
    }

    const drag = dragRef.current;
    if (drag === null || drag.pointerId !== event.pointerId) {
      return;
    }
    if (drag.pixelsPerUnit <= 0) {
      return;
    }
    // Only the pointer's own displacement is reported, so the shapes keep the spot
    // the user grabbed and the application can replay the gesture from its own
    // snapshot.
    const dx = (event.clientX - drag.client[0]) / drag.pixelsPerUnit;
    const dy = -(event.clientY - drag.client[1]) / drag.pixelsPerUnit;
    if (!drag.started) {
      // A press that has not moved yet is still a click, and must not open a
      // gesture the application would record as an undo step that changes nothing.
      if (dx === 0 && dy === 0) {
        return;
      }
      drag.started = true;
      // The snapshot is taken before the first report, so the application can
      // replay the gesture from the arrangement the press found. It is idempotent
      // with the release below.
      onGestureStart();
    }
    // The shapes follow the hand from the local draft alone: the application is
    // asked to judge the arrangement once, on release (see `release`), so a move
    // costs no round trip and a covering's measured arena never re-measures per
    // pointer event. The local size of a total-perimeter copy is the one gesture
    // that stays live, and it goes through `onLocalScale`.
    setDragDraft({ ids: drag.ids, dx, dy, picture: view });
  };

  const release = (event: ReactPointerEvent<SVGElement>) => {
    const scaling = scaleRef.current;
    if (scaling !== null && scaling.pointerId === event.pointerId) {
      scaleRef.current = null;
      setDragging(false);
      setScaleGripAt(null);
      // The last size was reported on the last move; the release only closes the
      // gesture, which is what records the one undo step. A click that moved
      // nothing wrote nothing at all.
      if (scaling.moved) {
        onLocalScaleCommit?.();
      }
      return;
    }
    const turning = turnRef.current;
    if (turning !== null && turning.pointerId === event.pointerId) {
      turnRef.current = null;
      setDragging(false);
      const settled = turnedDegrees(turning.degrees, turning.baseAngle, event.shiftKey);
      if (Math.abs(settled) < TURN_SLOP) {
        // A press that turned nothing is a click: the drawing goes back to the
        // picture and nothing is written, as a knob let go where it started
        // writes nothing.
        setDraft(null);
        return;
      }
      // The draft outlives the gesture by one round trip: the write below is what
      // makes the engine draw the turn, and until its answer arrives the picture
      // still shows the shape where it was. The whole turn is reported here, once
      // — that is what makes one drag one edit and one entry in the undo stack.
      setDraft({ ids: turning.ids, degrees: settled, picture: view });
      onTurn(settled);
      return;
    }

    const drag = dragRef.current;
    if (drag === null || drag.pointerId !== event.pointerId) {
      return;
    }
    dragRef.current = null;
    setDragging(false);
    if (drag.started && event.type === "pointerup") {
      const dx = (event.clientX - drag.client[0]) / drag.pixelsPerUnit;
      const dy = -(event.clientY - drag.client[1]) / drag.pixelsPerUnit;
      if (dx === 0 && dy === 0) {
        setDragDraft(null);
        return;
      }
      // The pointer's exact world displacement is kept. The engine may offer a
      // contact only within three screen pixels; magnification makes that a
      // smaller world distance, so zooming in permits finer placement.
      setDragDraft({ ids: drag.ids, dx, dy, picture: view });
      onGestureStart();
      onDrag(dx, dy, drag.ids, Math.min(3 / drag.pixelsPerUnit, 0.02));
      onGestureEnd();
    } else {
      setDragDraft(null);
    }
  };

  /** The middle button moves the window, wherever it is pressed. */
  const grabWindow = (event: ReactPointerEvent<SVGElement>) => {
    if (event.button !== 1) {
      return;
    }
    // Read in the capture phase, and stopped there: a middle press that landed on
    // a shape must not also reach the shape's own handler.
    event.stopPropagation();
    canvas.beginPan(event);
  };

  const background = (event: ReactPointerEvent<SVGElement>) => {
    if (event.button !== 0) {
      return;
    }
    const svg = canvas.node;
    if (svg === null || svg.getScreenCTM() === null) {
      return;
    }
    releaseFocus();
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const spot: Point = [event.clientX, event.clientY];
    const next: Marquee = {
      pointerId: event.pointerId, start: spot, current: spot,
      base: event.ctrlKey || event.metaKey || event.shiftKey ? selectedIds : [],
    };
    marqueeRef.current = next;
    setMarquee(next);
  };

  const marqueeMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const held = marqueeRef.current;
    if (held === null || held.pointerId !== event.pointerId) return;
    const next = { ...held, current: [event.clientX, event.clientY] as Point };
    marqueeRef.current = next;
    setMarquee(next);
    if (Math.hypot(next.current[0] - next.start[0], next.current[1] - next.start[1]) < CLICK_SLOP) return;
    const left = Math.min(next.start[0], next.current[0]);
    const right = Math.max(next.start[0], next.current[0]);
    const top = Math.min(next.start[1], next.current[1]);
    const bottom = Math.max(next.start[1], next.current[1]);
    const hits = [...(canvas.node?.querySelectorAll<SVGGElement>("[data-shape-id]") ?? [])]
      .filter((element) => {
        const bounds = element.getBoundingClientRect();
        return bounds.left <= right && bounds.right >= left && bounds.top <= bottom && bounds.bottom >= top;
      })
      .map((element) => element.dataset.shapeId ?? "")
      .filter(Boolean);
    const nextIds = [...new Set([...next.base, ...hits])];
    if (nextIds.join("\u0000") !== selectedIds.join("\u0000")) onSelect(nextIds);
  };

  const marqueeRelease = (event: ReactPointerEvent<SVGSVGElement>) => {
    const held = marqueeRef.current;
    if (held === null || held.pointerId !== event.pointerId) return;
    marqueeRef.current = null;
    setMarquee(null);
    if (Math.hypot(event.clientX - held.start[0], event.clientY - held.start[1]) < CLICK_SLOP) {
      onSelect(held.base);
    }
  };

  const marqueeBox = (() => {
    const matrix = canvas.node?.getScreenCTM();
    if (marquee === null || matrix === undefined || matrix === null) return null;
    const a = new DOMPoint(...marquee.start).matrixTransform(matrix.inverse());
    const b = new DOMPoint(...marquee.current).matrixTransform(matrix.inverse());
    return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), width: Math.abs(a.x - b.x), height: Math.abs(a.y - b.y) };
  })();

  /** Replace the browser's context menu with shape creation. */
  const askForCreate = (event: ReactMouseEvent<SVGSVGElement>) => {
    event.preventDefault();
    if (readOnly) return;
    const world = canvas.worldAt(event);
    if (world !== null) {
      onRequestCreate(world, [event.clientX, event.clientY]);
    }
  };

  const cursor = canvas.panning ? PAN_STYLE : CANVAS_STYLE;

  return (
    <>
      <div className="canvas-sheet">
      <svg
        ref={canvas.ref}
        className={["canvas", dragging ? "canvas--dragging" : "", translucent ? "canvas--translucent" : ""].filter(Boolean).join(" ")}
        viewBox={viewBoxOf(frame)}
        preserveAspectRatio="xMidYMid meet"
        style={cursor}
        onPointerDownCapture={grabWindow}
        onPointerDown={background}
        onContextMenu={askForCreate}
        onPointerMove={marqueeMove}
        onPointerUp={marqueeRelease}
        onPointerCancel={marqueeRelease}
        onLostPointerCapture={marqueeRelease}
      >
        <defs>
          <linearGradient id="shape-invalid-gradient" x1="0" y1="1" x2="1" y2="0" gradientUnits="objectBoundingBox">
            <stop offset="0" stopColor="#d55975" />
            <stop offset="0.75" stopColor="#efa5b4" />
            <stop offset="1" stopColor="#ffe9ee" />
          </linearGradient>
          {view.shapes.map((shape) => {
            const rotation = candidate.placements.find((item) => item.shape_id === shape.shape_id)?.rotation ?? 0;
            const base = orientationHighlights ? orientationColor(shape.orientation_group ?? 0) : shape.color ?? "#aa78d4";
            return <radialGradient key={shape.shape_id} id={`shape-fill-${shape.shape_id}`}
              cx=".88" cy=".12" r="1.18" fx=".91" fy=".07" gradientUnits="objectBoundingBox"
              gradientTransform={`rotate(${rotation} .5 .5)`}>
              <stop offset="0" stopColor={`color-mix(in srgb, ${base} 44%, #fff7fd)`} />
              <stop offset=".28" stopColor={`color-mix(in srgb, ${base} 67%, #fff7fd)`} />
              <stop offset=".6" stopColor={`color-mix(in srgb, ${base} 88%, #fff7fd)`} />
              <stop offset="1" stopColor={base} />
            </radialGradient>;
          })}
        </defs>
        <g transform={canvas.transform}>
          <g ref={worldRef} transform="scale(1 -1)" style={translucent ? { isolation: "isolate" } : undefined}>
            <path className="arena" d={view.arena.path} />
            <path className="arena arena--sketch" d={view.arena.path} />
            {view.shapes.map((primitive) => {
              // Where this shape is drawn: the placement being edited wins over the
              // centre the engine's primitive was judged at.
              const [baseX, baseY] = drawnCentre(primitive, candidate);
              const moving = dragDraft !== null && dragDraft.picture === view
                && dragDraft.ids.includes(primitive.shape_id);
              const x = baseX + (moving ? dragDraft.dx : 0);
              const y = baseY + (moving ? dragDraft.dy : 0);
              // How far this shape is drawn turned beyond the picture: a turn of the
              // pointer's that the engine has not answered yet. The group's origin is
              // the shape's own centre — the placement the drawing is translated to —
              // and so is the centre the engine measures a rotation about.
              const turned =
                turn !== null && turn.ids.includes(primitive.shape_id) ? turn.degrees : 0;
              const groupTurn = turned !== 0 && turn !== null && turn.ids.length > 1 && turnPole !== null;
              const transform = groupTurn
                ? `translate(${turnPole[0]} ${turnPole[1]}) rotate(${turned}) translate(${-turnPole[0]} ${-turnPole[1]}) ${shapeTransform(x, y, 0)}`
                : shapeTransform(x, y, turned);
              const classes = ["shape"];
              if (primitive.invalid) {
                classes.push("shape--invalid");
              }
              if (selected.has(primitive.shape_id)) {
                classes.push("shape--selected");
              }
              const className = classes.join(" ");
              const fill = shapeFill(primitive);
              return (
                <g key={primitive.shape_id} data-shape-id={primitive.shape_id} transform={transform}>
                  {primitive.kind === "circle" ? (
                    <circle
                      className={className}
                      cx={0}
                      cy={0}
                      r={primitive.radius}
                      style={fill}
                      onPointerDown={(event) => press(primitive.shape_id, [x, y], event)}
                      onPointerMove={move}
                      onPointerUp={release}
                      onPointerCancel={release}
                      onLostPointerCapture={release}
                    />
                  ) : (
                    <polygon
                      className={className}
                      points={relativePoints(primitive)}
                      style={fill}
                      onPointerDown={(event) => press(primitive.shape_id, [x, y], event)}
                      onPointerMove={move}
                      onPointerUp={release}
                      onPointerCancel={release}
                      onLostPointerCapture={release}
                    />
                  )}
                  {showIds && <text className="shape-id" textAnchor="middle" dominantBaseline="central"
                    transform={`rotate(${-turned}) scale(1 -1)`}
                    fontSize={12 / Math.max(1, (pixelsPerUnit ?? 40) * canvas.zoom)}
                    pointerEvents="none">{primitive.shape_id}</text>}
                </g>
              );
            })}
            {showUnion && view.union && (
              // The union is the engine's own path, drawn in the same world frame as
              // the arena: the browser merges nothing, it only paints what it was sent.
              <path className="union-overlay" d={view.union.path} pointerEvents="none" />
            )}
            {!readOnly && scalePlacement !== null && gripSizeWorld !== null && scaleHandle !== null && (
              // The in-canvas resize handle, the arena canvas' own corner-grip idiom
              // at the bottom-right of the copy. A uniform local scale multiplies
              // every distance from the copy's origin by the same factor, so the
              // gesture is the interface's own arithmetic and the engine judges the
              // size it proposes; it is drawn after the shapes and stops its own
              // press, exactly as the turn grip does.
              <rect
                className="shape-scale-grip"
                x={scaleHandle[0] - gripSizeWorld / 2}
                y={scaleHandle[1] - gripSizeWorld / 2}
                width={gripSizeWorld}
                height={gripSizeWorld}
                onPointerDown={grabScale}
                onPointerMove={move}
                onPointerUp={release}
                onPointerCancel={release}
                onLostPointerCapture={release}
              />
            )}
            {!readOnly && (!dragging || turnRef.current !== null) && grip !== null && arrowScale !== null && (
              // Drawn after the shapes, so it is on top of them and a press on it
              // is never a press on the shape underneath. Its own press is stopped
              // in `grabGrip`, which is what keeps the background — and the click
              // that clears the selection — out of it.
              <g
                className="turn-grip"
                transform={`translate(${grip[0]} ${grip[1]})`}
                onPointerDown={grabGrip}
                onPointerMove={move}
                onPointerUp={release}
                onPointerCancel={release}
                onLostPointerCapture={release}
              >
                {/* The arrow, and the whole of the control: drawn in a unit frame
                    whose own circle is one unit around the point the group is
                    translated to, and scaled to the screen pixels it is measured
                    in. It nearly closes its circle, so a hand reads it as a turn,
                    and the gap it leaves is where its head points. */}
                <g transform={`scale(${arrowScale})`}>
                  <circle className="turn-grip__core" r={1.25} />
                  {/* The band a press has to land in, drawn first so the arrow is
                      over it: a circle whose own stroke is the band, transparent,
                      and wider than the arrow's stroke by the tolerance. One unit
                      of this frame is `ARROW_RADIUS` screen pixels, so the band's
                      two numbers are screen pixels too, and the painted arrow is
                      not one pixel different for it. It is cut at the edge of the
                      selection's box, which is where the object begins: the
                      tolerance is room beside the arrow, not a press taken off the
                      object it turns. */}
                  <clipPath id="turn-grip-cut">
                    <rect
                      x={HIT_CUT}
                      y={-HIT_REACH}
                      width={HIT_REACH - HIT_CUT}
                      height={2 * HIT_REACH}
                    />
                  </clipPath>
                  <circle
                    className="turn-grip__hit"
                    r={HIT_MIDDLE / ARROW_RADIUS}
                    strokeWidth={HIT_WIDTH / ARROW_RADIUS}
                    clipPath="url(#turn-grip-cut)"
                  />
                  <path
                    className="turn-grip__mark"
                    d="M -0.866 -0.5 A 1 1 0 1 0 0.1392 -0.9903"
                  />
                  <path className="turn-grip__mark" d="M 0.1657 -0.4362 L 0.1392 -0.9903 L -0.354 -0.7362" />
                </g>
              </g>
            )}
          </g>
        </g>
        {marqueeBox && <rect className="canvas-marquee" {...marqueeBox} pointerEvents="none" />}
      </svg>
      {view.union && <button type="button" className={`canvas-ids canvas-union${showUnion ? " is-active" : ""}`}
        onClick={() => setShowUnion((value) => !value)} aria-pressed={showUnion}
        aria-label={t("Show the union of the shapes")}>{t("∪")}</button>}
      {onToggleIds && <button type="button" className={`canvas-ids${showIds ? " is-active" : ""}`}
        onClick={onToggleIds} aria-pressed={showIds} aria-label={t("Show shape IDs")}>{t("ID")}</button>}
      <ZoomControl view={canvas} />
      </div>
    </>
  );
}

/**
 * Where one shape is drawn: the placement being edited wins over the centre the
 * engine's primitive was judged at, since the drawing follows the placement.
 */
function drawnCentre(primitive: ShapePrimitiveDoc, candidate: CandidateDoc): Point {
  const placement = candidate.placements.find((item) => item.shape_id === primitive.shape_id);
  return placement === undefined ? primitive.center : [placement.x, placement.y];
}

/**
 * The fill a shape wears: its own colour when the document carries one, and the
 * stylesheet's own when it does not.
 *
 * Written as an inline style rather than as the `fill` attribute, because a
 * presentation attribute loses to any stylesheet rule and would never reach the
 * shape. A shape the analysis reports as violating is left out of it: the
 * violation colours outrank the decoration.
 */
function shapeFill(primitive: ShapePrimitiveDoc): { fill: string } | undefined {
  return primitive.invalid ? undefined : { fill: `url(#shape-fill-${primitive.shape_id})` };
}

/**
 * The box a selection occupies, in the frame's own coordinates, or `null` when
 * nothing is selected.
 *
 * The engine sends each shape's bounds. The browser only translates those bounds
 * by the placement's current displacement, so the control follows an edit.
 */
function selectionBox(
  view: ViewDoc,
  candidate: CandidateDoc,
  selected: Set<string>,
): Bounds | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let count = 0;
  for (const primitive of view.shapes) {
    if (!selected.has(primitive.shape_id)) {
      continue;
    }
    const [centreX, centreY] = drawnCentre(primitive, candidate);
    const dx = centreX - primitive.center[0];
    const dy = centreY - primitive.center[1];
    minX = Math.min(minX, primitive.bounds[0] + dx);
    minY = Math.min(minY, primitive.bounds[1] + dy);
    maxX = Math.max(maxX, primitive.bounds[2] + dx);
    maxY = Math.max(maxY, primitive.bounds[3] + dy);
    count += 1;
  }
  return count === 0 ? null : [minX, minY, maxX, maxY];
}

/**
 * The corners of a polygon relative to its own centre.
 *
 * The engine sends them in world coordinates; the shape is drawn inside a group
 * already translated to the placement, so the centre has to come off here —
 * otherwise the translation would be counted twice.
 */
function relativePoints(primitive: ShapePrimitiveDoc): string {
  const [centerX, centerY] = primitive.center;
  return (primitive.points ?? [])
    .map(([x, y]) => `${x - centerX},${y - centerY}`)
    .join(" ");
}

/**
 * Where a point stands, in degrees, about a pole, counter-clockwise from the
 * `+x` axis — the way the engine measures a rotation.
 *
 * This is the interface's own arithmetic and it knows nothing of a shape: the
 * pole is the centre the drawing already turns the shape about, and the point is
 * where the pointer is. Nothing is negated, unlike on the inspector's knob,
 * which measures in screen pixels: the domain is drawn with `y` growing upwards.
 */
function angleAbout(pole: Point, point: Point): number {
  return (Math.atan2(point[1] - pole[1], point[0] - pole[0]) * 180) / Math.PI;
}

/**
 * One step of a turn, folded into `[-180, 180)`.
 *
 * A turn is added up step by step rather than measured from where the press
 * landed: the pointer's own angle folds back on itself past the halfway mark,
 * and a turn that stopped there would jump.
 */
function foldedStep(degrees: number): number {
  return ((((degrees + 180) % 360) + 360) % 360) - 180;
}

/**
 * The turn a gesture has reached, with the same guides as the inspector's knob.
 */
function turnedDegrees(degrees: number, baseAngle: number, strict: boolean): number {
  return snapAngle(baseAngle + degrees, strict) - baseAngle;
}

/**
 * Where the drawing places one shape: the translation of its placement, and the
 * turn a gesture has given it that the picture does not carry yet.
 *
 * The translation comes from the engine's own documents; the angle is the one
 * number the interface works out, and only while the pointer is down. `rotate`
 * turns about the group's own origin, which is the shape's centre.
 */
function shapeTransform(x: number, y: number, turn: number): string {
  const placed = `translate(${x} ${y})`;
  // Six significant digits, as the panel writes an angle: the pointer's own
  // arithmetic leaves a tail of decimals nothing reads.
  return turn === 0 ? placed : `${placed} rotate(${Number(turn.toPrecision(6))})`;
}
