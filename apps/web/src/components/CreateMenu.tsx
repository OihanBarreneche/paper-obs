/**
 * The little window that opens where a click landed, offering what can be made there.
 *
 * A click on an empty canvas should mean "put something here", and there is more
 * than one thing "something" can be. The application decides what the entries
 * are — the one elementary-shape list every workspace shares — and this draws
 * them at the pointer and reports the choice.
 *
 * It is placed inside the window, not at the raw click: a click near the right
 * or bottom edge would otherwise open it off screen. Closing on Escape is the
 * application's business — it already owns the keyboard — so the only way out
 * declared here is the veil, which is also what makes a click anywhere else
 * dismiss the menu rather than act on the canvas behind it.
 *
 * The menu reads as one vertical list, never several lines of wrapped text: every
 * entry is a row, its name stays on its line however long it is, and the two
 * shapes whose size is not a single number — a regular polygon and an ellipse —
 * keep their fields beside the name rather than under it.
 */

import { useLayoutEffect, useRef, useState } from "react";

import type { Point } from "../types";
import { useI18n } from "../i18n";

import "./CreateMenu.css";

export type CreateItem = {
  /** Reported back when the entry is chosen. */
  id: string;
  label: string;
  hint?: string;
  /**
   * The side count this entry starts from, for an entry that builds a regular
   * polygon. A field appears beside it and the chosen count is reported back with
   * the identifier; an entry without it is picked exactly as it is, which is what
   * every other entry wants.
   */
  sides?: number;
  /**
   * The two semi-axes this entry starts from, for an entry that builds an ellipse.
   * A field per axis appears beside it and the chosen pair is reported back with
   * the identifier. An entry carries either a side count or a pair of axes, never
   * both, and one that carries neither is picked exactly as it is.
   */
  axes?: [number, number];
};

export type CreateGroup = {
  /** A heading, or null for the entries of a menu that has only one meaning. */
  title: string | null;
  items: CreateItem[];
};

export type CreateMenuProps = {
  /** Where the click happened, in client coordinates. */
  at: Point;
  title: string;
  groups: CreateGroup[];
  onPick: (id: string, sides?: number, axes?: [number, number]) => void;
  onClose: () => void;
};

/** The fewest sides a polygon can have, which is where the engine starts refusing. */
const MIN_SIDES = 3;

/** Distance kept from the edge of the window. */
const EDGE = 12;

export function CreateMenu({ at, title, groups, onPick, onClose }: CreateMenuProps) {
  const { t } = useI18n();
  const card = useRef<HTMLDivElement | null>(null);
  const [spot, setSpot] = useState<Point>(at);
  // The numbers typed into an entry, kept here so a menu that re-renders under
  // the pointer does not lose what was typed into it.
  const [sides, setSides] = useState<Record<string, number>>({});
  const [axes, setAxes] = useState<Record<string, [number, number]>>({});

  useLayoutEffect(() => {
    const node = card.current;
    if (node === null) {
      return;
    }
    const { width, height } = node.getBoundingClientRect();
    setSpot([
      Math.max(EDGE, Math.min(at[0], window.innerWidth - width - EDGE)),
      Math.max(EDGE, Math.min(at[1], window.innerHeight - height - EDGE)),
    ]);
  }, [at]);

  return (
    <>
      <div className="create-menu__veil" onPointerDown={onClose} />
      <div
        ref={card}
        className="create-menu"
        role="menu"
        style={{ left: `${spot[0]}px`, top: `${spot[1]}px` }}
      >
        <p className="create-menu__title">{t(title)}</p>
        {groups.map((group) => (
          <div key={group.title ?? "items"} className="create-menu__group">
            {group.title !== null && <p className="create-menu__heading">{t(group.title)}</p>}
            {group.items.map((item) => {
              const body = (
                <>
                  <span className="create-menu__label">{t(item.label)}</span>
                  {item.hint !== undefined && <span className="create-menu__hint">{t(item.hint)}</span>}
                </>
              );
              const chosen = sides[item.id] ?? item.sides;
              const chosenAxes = axes[item.id] ?? item.axes;
              // An entry carries at most one control: the side count of a regular
              // polygon, or the two semi-axes of an ellipse. An entry with neither
              // keeps the DOM it had and is picked exactly as it is.
              const control = item.sides !== undefined || item.axes !== undefined;
              const pick = (
                <button
                  key={control ? undefined : item.id}
                  className="button create-menu__item"
                  type="button"
                  role="menuitem"
                  onClick={() =>
                    onPick(
                      item.id,
                      item.sides === undefined ? undefined : chosen,
                      item.axes === undefined ? undefined : chosenAxes,
                    )
                  }
                >
                  {body}
                </button>
              );
              if (!control) {
                return pick;
              }
              return (
                <div className="create-menu__entry" key={item.id}>
                  {pick}
                  {item.sides !== undefined && (
                    <input
                      className="input input--narrow"
                      type="number"
                      min={MIN_SIDES}
                      step={1}
                      aria-label={`${t(item.label)} ${t("side count")}`}
                      value={chosen}
                      onChange={(event) =>
                        setSides((current) => ({ ...current, [item.id]: Number(event.target.value) }))
                      }
                    />
                  )}
                  {chosenAxes !== undefined && (
                    <>
                      <input
                        className="input input--narrow"
                        type="number"
                        step="any"
                        aria-label={`${t(item.label)} ${t("semi-axis a")}`}
                        value={chosenAxes[0]}
                        onChange={(event) =>
                          setAxes((current) => ({
                            ...current,
                            [item.id]: [
                              Number(event.target.value),
                              current[item.id]?.[1] ?? chosenAxes[1],
                            ],
                          }))
                        }
                      />
                      <input
                        className="input input--narrow"
                        type="number"
                        step="any"
                        aria-label={`${t(item.label)} ${t("semi-axis b")}`}
                        value={chosenAxes[1]}
                        onChange={(event) =>
                          setAxes((current) => ({
                            ...current,
                            [item.id]: [
                              current[item.id]?.[0] ?? chosenAxes[0],
                              Number(event.target.value),
                            ],
                          }))
                        }
                      />
                    </>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </>
  );
}
