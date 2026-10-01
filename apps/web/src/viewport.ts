/**
 * Where a canvas looks, and nothing else.
 *
 * The engine decides what a picture contains; panning and zooming only move the
 * window that picture is seen through. That is why nothing here computes a
 * geometric quantity: it applies one translation and one uniform magnification
 * to the group that already carries the vertical flip, and converts a pointer
 * position back into world units so a drag can report the displacement the
 * application asked for.
 *
 * One instance of the hook is shared by every canvas. Switching between the
 * shapes and the arena therefore keeps the same window, and the picture does not
 * jump when the mode changes.
 *
 * The other direction is here too: a control a canvas draws at a fixed size on
 * screen stands inside the picture, so where it has to stand to stay on the
 * canvas is a question about this window, and answered from the same matrix this
 * module already converts a pointer with.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";

import type { Bounds, Point } from "./types";

/** Blank border left around the frame, as a fraction of its larger side. */
export const FRAME_MARGIN = 0.06;

/** How far out and how far in the window can go. */
export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 20;

/** The rectangle of world space a viewBox covers, in the user space the flip implies. */
export type SceneBox = { x: number; y: number; width: number; height: number };

/** The state of the window: how much it magnifies, and where it has been dragged. */
export type Viewport = { zoom: number; tx: number; ty: number };

const ORIGINAL: Viewport = { zoom: 1, tx: 0, ty: 0 };

/**
 * The world rectangle a canvas shows: the frame the engine chose, plus a margin,
 * with the mirrored vertical origin that goes with the flip group.
 */
export function sceneBox(frame: Bounds): SceneBox {
  const [minX, minY, maxX, maxY] = frame;
  const margin = FRAME_MARGIN * Math.max(maxX - minX, maxY - minY, 1e-9);
  return {
    x: minX - margin,
    y: -maxY - margin,
    width: maxX - minX + 2 * margin,
    height: maxY - minY + 2 * margin,
  };
}

/** The `viewBox` attribute of a canvas showing that frame. */
export function viewBoxOf(frame: Bounds): string {
  const box = sceneBox(frame);
  return `${box.x} ${box.y} ${box.width} ${box.height}`;
}

function clampZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) {
    return ORIGINAL.zoom;
  }
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

export type CanvasViewport = {
  /** Attach to the `<svg>` of a canvas: the hook needs it to place the picture. */
  ref: (node: SVGSVGElement | null) => void;
  /** The element that was attached, for a canvas that has to measure itself. */
  node: SVGSVGElement | null;
  /** Wrap the drawing in a group carrying this, inside that `<svg>`. */
  transform: string;
  /** Current magnification, 1 being the original one. */
  zoom: number;
  /** Go back to the original window: no magnification, no displacement. */
  reset: () => void;
  /** Magnify about the centre of the canvas — what a slider does. */
  setZoom: (zoom: number) => void;
  /** The world point an event points at, in the domain's own coordinates. */
  worldAt: (event: { clientX: number; clientY: number }) => Point | null;
  /** Start dragging the window: every move pans until the button is released. */
  beginPan: (event: ReactPointerEvent<SVGElement>) => void;
  /** True while the window is being dragged. */
  panning: boolean;
};

/**
 * The pan and zoom of one window, shared by the canvases that draw in it.
 *
 * The wheel is listened to natively rather than through React: React registers
 * its own `wheel` handler as passive, so `preventDefault` there would be ignored
 * and the page behind the canvas would scroll while zooming.
 */
export function useViewport(wheelZoom = true): CanvasViewport {
  const [node, setNode] = useState<SVGSVGElement | null>(null);
  const [viewport, setViewport] = useState<Viewport>(ORIGINAL);
  const [panning, setPanning] = useState(false);

  // Read by the handlers below, which are attached outside React's render and
  // would otherwise close over a magnification that is one edit too old.
  const current = useRef(viewport);
  current.current = viewport;

  const ref = useCallback((next: SVGSVGElement | null) => setNode(next), []);

  /** Where a screen position falls in the canvas' own user space. */
  const userAt = useCallback(
    (clientX: number, clientY: number): Point | null => {
      const matrix = node === null ? null : node.getScreenCTM();
      if (matrix === null) {
        return null;
      }
      const point = new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse());
      return [point.x, point.y];
    },
    [node],
  );

  const worldAt = useCallback(
    (event: { clientX: number; clientY: number }): Point | null => {
      const user = userAt(event.clientX, event.clientY);
      if (user === null) {
        return null;
      }
      const { zoom, tx, ty } = current.current;
      // The flip group mirrors y *after* the window has been applied, so world
      // coordinates are the user ones untranslated first, unmirrored second.
      return [(user[0] - tx) / zoom, -(user[1] - ty) / zoom];
    },
    [userAt],
  );

  /** Magnify so that the point under a screen position keeps its place. */
  const zoomAt = useCallback(
    (clientX: number, clientY: number, zoom: number) => {
      const user = userAt(clientX, clientY);
      if (user === null) {
        return;
      }
      const next = clampZoom(zoom);
      setViewport((state) => {
        // A pair, not an array: the two coordinates are read below, and a
        // tuple says so.
        const world: Point = [
          (user[0] - state.tx) / state.zoom,
          (user[1] - state.ty) / state.zoom,
        ];
        return { zoom: next, tx: user[0] - next * world[0], ty: user[1] - next * world[1] };
      });
    },
    [userAt],
  );

  const setZoom = useCallback(
    (zoom: number) => {
      if (node === null) {
        setViewport((state) => ({ ...state, zoom: clampZoom(zoom) }));
        return;
      }
      const rect = node.getBoundingClientRect();
      zoomAt(rect.x + rect.width / 2, rect.y + rect.height / 2, zoom);
    },
    [node, zoomAt],
  );

  const reset = useCallback(() => setViewport(ORIGINAL), []);

  useEffect(() => {
    if (node === null || !wheelZoom) {
      return;
    }
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      // Firefox reports a wheel notch in lines rather than in pixels; without
      // this, one notch there would magnify by a barely visible amount.
      const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
      const bounded = Math.max(-140, Math.min(140, delta));
      zoomAt(event.clientX, event.clientY, current.current.zoom * Math.exp(-bounded * 0.0015));
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [node, wheelZoom, zoomAt]);

  const beginPan = useCallback(
    (event: ReactPointerEvent<SVGElement>) => {
      const matrix = node === null ? null : node.getScreenCTM();
      if (matrix === null || matrix.a === 0) {
        return;
      }
      // A middle press on a canvas would otherwise start the browser's own
      // autoscroll, and on a shape it must not read as a grab.
      event.preventDefault();
      // The canvas' own scale, in screen pixels per user unit: a drag reported in
      // pixels has to become a displacement in the units the drawing uses. It is
      // constant for the whole gesture, since panning does not magnify.
      const perUnit = matrix.a;
      let last = { x: event.clientX, y: event.clientY };
      const move = (moved: PointerEvent) => {
        const dx = (moved.clientX - last.x) / perUnit;
        const dy = (moved.clientY - last.y) / perUnit;
        last = { x: moved.clientX, y: moved.clientY };
        setViewport((state) => ({ ...state, tx: state.tx + dx, ty: state.ty + dy }));
      };
      const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
        window.removeEventListener("pointercancel", stop);
        setPanning(false);
      };
      setPanning(true);
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
      window.addEventListener("pointercancel", stop);
    },
    [node],
  );

  return {
    ref,
    node,
    transform: `translate(${viewport.tx} ${viewport.ty}) scale(${viewport.zoom})`,
    zoom: viewport.zoom,
    reset,
    setZoom,
    worldAt,
    beginPan,
    panning,
  };
}

/**
 * A world point kept inside the visible canvas, for a mark a canvas draws at a
 * fixed size on screen.
 *
 * `radius` is that mark's own reach around the point, in screen pixels, and it is
 * the room kept for it: the answer is the point pulled back just far enough that
 * none of the mark is off the canvas, or the point itself when it was already
 * inside. A control that followed its shape out of a magnified window could not be
 * pressed, so it stays where a hand can reach it.
 *
 * The screen matrix of the group the mark is drawn in is what does the converting,
 * because it is the browser's own answer to where the picture lies: a canvas
 * letterboxes its frame inside the element it fills, and the element's box alone
 * would place the mark off the drawing. The matrix is read after every render —
 * panning and magnifying both render — so the control moves with the picture it
 * belongs to.
 */
export function useInsideCanvas(
  node: SVGSVGElement | null,
  group: RefObject<SVGGElement | null>,
  world: Point | null,
  radius: number,
): Point | null {
  const [inside, setInside] = useState<Point | null>(null);

  useLayoutEffect(() => {
    const mark = group.current;
    const matrix = mark === null ? null : mark.getScreenCTM();
    // A group that is not on screen has no matrix, and a canvas that has not been
    // laid out yet has one that cannot be inverted — an element of no size scales
    // by zero. There is nothing to clamp against in either case, and the mark is
    // left where it was asked for; `matrix.a` is the canvas' own scale, exactly
    // what the pan checks before reading a pointer the same way.
    if (node === null || matrix === null || matrix.a === 0 || world === null) {
      setInside(null);
      return;
    }
    const rect = node.getBoundingClientRect();
    const spot = new DOMPoint(world[0], world[1]).matrixTransform(matrix);
    // A canvas narrower than twice the room asked for has none to give: the low
    // bound is then the one that stands, exactly as the finish control does it.
    const x = Math.min(
      Math.max(spot.x, rect.left + radius),
      Math.max(rect.left + radius, rect.right - radius),
    );
    const y = Math.min(
      Math.max(spot.y, rect.top + radius),
      Math.max(rect.top + radius, rect.bottom - radius),
    );
    if (x === spot.x && y === spot.y) {
      setInside(null);
      return;
    }
    const back = new DOMPoint(x, y).matrixTransform(matrix.inverse());
    setInside((current) =>
      current !== null && current[0] === back.x && current[1] === back.y
        ? current
        : [back.x, back.y],
    );
  });

  return world === null ? null : inside ?? world;
}
