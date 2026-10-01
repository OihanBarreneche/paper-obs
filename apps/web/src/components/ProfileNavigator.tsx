import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MAX_VISIBLE_COUNT, PACKING_INDEX, SQUARE_RECORDS, withinVisibleCount } from "../catalog";
import type { SquareRecord } from "../catalog";
import { api } from "../api";
import { copyConfigurations, copyFigureUrl, copyNoun, copyProblem, copyProblemId, copyable, loadCopyCatalog, loadFamilyPreviews } from "../equalCopiesCatalog";
import type { CopyCatalog, FamilyPreview } from "../equalCopiesCatalog";
import { useI18n } from "../i18n";
import type { ProfileCategory } from "../profileLibrary";
import type { ExampleSummaryDoc, ProblemDoc, ShapeFamilyDoc } from "../types";
import "./ProfileNavigator.css";

type Props = {
  categories: ProfileCategory[];
  categoryId: string;
  examples: ExampleSummaryDoc[];
  localProblems: Record<string, ProblemDoc>;
  problemId: string | null;
  onCategory: (id: string) => void;
  onProblem: (id: string) => void;
  onCreateCategory: (name: string) => void;
  onRenameCategory: (id: string, name: string) => void;
  onDeleteCategory: (id: string) => void;
  onRemoveProblem: (id: string) => void;
  onEditProblem: (id: string) => void;
  onAddSquare: (count: number) => void;
  /** Store a generated catalogue document in the active category, then open it. */
  onAddProblem: (problem: ProblemDoc) => void;
  onNewCustom: () => void;
  onImportProblem: (problem: unknown) => Promise<void>;
  guideReveal: "picker" | "catalog-list" | "catalog-family" | null;
};

const FAMILIES = ["Packing equal copies", "Maximize total perimeter", "Covering"] as const;
/**
 * The navigator family whose figures keep the source's own colours.
 *
 * There the colour encodes the different sizes of the packed shapes, so it is
 * information, not decoration, and those figures are left untouched. Every other
 * family's source figures wear the catalogue's pink/purple treatment. (A generated
 * family's `section` prop is this navigator family, not the heading below.)
 */
const PERIMETER_FAMILY = "Maximize total perimeter";
/** The collection's own section heading behind each navigator family. */
const SECTION_HEADINGS: Record<string, string> = {
  "Packing equal copies": "Packing Equal Copies",
  "Maximize total perimeter": "Packing Copies to Maximize Total Perimeter",
  Covering: "Covering",
};

/** The one line a subfamily whose every record is above the display limit shows. */
function hiddenRecordsNote(t: (english: string) => string): string {
  return `${t("Every record of this subfamily packs more than")} ${MAX_VISIBLE_COUNT} ${t("shapes, so it is not listed here: the interface stays smooth this way.")}`;
}
/** The curated subfamily: 29 hand-checked records beside the generated catalogue. */
const SQUARES = "Squares in squares";

/**
 * The noun the container filter shows for a catalogue container.
 *
 * A container is not the packed shape's plural: "circles in squares" packs
 * circles into a *square*, and the two words translate differently in French
 * ("disques" against "carré"). The mapped keys are therefore distinct from the
 * shape nouns, and an unknown container keeps its asset word.
 */
const CONTAINER_NOUNS: Record<string, string> = {
  circle: "container circle", square: "container square", triangle: "container triangle",
  pentagon: "container pentagon", hexagon: "container hexagon", octagon: "container octagon",
  rectangle: "container rectangle", ellipse: "container ellipse",
  tan: "container tan", domino: "container domino", l: "container l",
};

/**
 * Fixed navigation sketches, one outline per catalogue shape.
 *
 * A tile nobody has opened has no arrangement to draw, and nothing here measures
 * anything: the same outline serves as the container and, smaller, as the four
 * copies. It is decoration, never a solution and never a verdict.
 */
const SKETCH_OUTLINES: Record<string, string> = {
  circle: "M 1 0 A 1 1 0 1 0 -1 0 A 1 1 0 1 0 1 0 Z",
  triangle: "M 0 -1.1 L 1.05 0.6 L -1.05 0.6 Z",
  square: "M -0.9 -0.9 H 0.9 V 0.9 H -0.9 Z",
  pentagon: "M 0 -1.05 L 1 -0.34 L 0.62 0.85 L -0.62 0.85 L -1 -0.34 Z",
  hexagon: "M 0 -1.05 L 0.91 -0.52 L 0.91 0.52 L 0 1.05 L -0.91 0.52 L -0.91 -0.52 Z",
  octagon: "M -0.43 -1.04 H 0.43 L 1.04 -0.43 V 0.43 L 0.43 1.04 H -0.43 L -1.04 0.43 V -0.43 Z",
  tan: "M -1 -1 H 1 V 1 Z",
  domino: "M -0.5 -1 H 0.5 V 1 H -0.5 Z",
  l: "M -1 -1 H -0.2 V 0.2 H 1 V 1 H -1 Z",
  rectangle: "M -1.05 -0.62 H 1.05 V 0.62 H -1.05 Z",
  ellipse: "M 1.05 0 A 1.05 0.62 0 1 0 -1.05 0 A 1.05 0.62 0 1 0 1.05 0 Z",
};
const SKETCH_FALLBACK = SKETCH_OUTLINES["square"] ?? "";

/**
 * One published record's figure, hotlinked from the source page.
 *
 * Copying the collection's figures was ruled out: there are about two thousand of
 * them and tens of megabytes of bitmaps, for a panel that shows a handful at a
 * time. The source page is fetched only when its subfamily is opened, one image at
 * a time and lazily, and the reference keeps its own link so the reader can check
 * the original. A record whose source publishes no figure simply shows no picture:
 * a dashed "not published" plate was an invented line the owner removed.
 */
function Figure({ url, alt, tinted }: { url: string; alt: string; tinted: boolean }) {
  const [failed, setFailed] = useState(false);
  if (url === "" || failed) return null;
  // Our own drawings already wear the catalogue's pink/purple; only a figure
  // hotlinked from the source is treated, and the perimeter section keeps its own
  // colours because there they encode the sizes of the packed shapes.
  const source = /^https?:/i.test(url);
  return <span className="profile-catalog__figure">
    <img src={url} alt={alt} loading="lazy" decoding="async" referrerPolicy="no-referrer"
      className={source && tinted ? "is-source" : undefined}
      onError={() => setFailed(true)} />
  </span>;
}

/**
 * One subfamily tile: the real picture the builder chose for it.
 *
 * The manifest says whether that is an engine drawing of the exact published
 * packing, the source's own figure, or a schematic for a family whose source
 * publishes none. A failed load falls back on the sketch so the grid never tears.
 */
function FamilyPicture({ preview, shape, container, tinted }: { preview: FamilyPreview | undefined; shape: string; container: string; tinted: boolean }) {
  const [failed, setFailed] = useState(false);
  if (preview !== undefined && preview.url !== "" && !failed) {
    // A rendered tile is our own drawing and already matches; a source figure is a
    // bitmap and takes the filter, unless it belongs to the perimeter section.
    const source = preview.kind === "figure";
    return <img src={preview.url} alt="" loading="lazy" decoding="async"
      className={source && tinted ? "is-source" : undefined}
      onError={() => setFailed(true)} />;
  }
  return <CopySketch shape={shape} container={container} />;
}

/** How a record's symbol reads as a measure; an unknown symbol keeps its letter. */
const MEASURES: Record<string, string> = { r: "radius", s: "side", a: "area" };

function CopySketch({ shape, container }: { shape: string; container: string }) {
  const positions = [[-17, -17], [17, -17], [-17, 17], [17, 17]] as const;
  const outline = (name: string) => SKETCH_OUTLINES[name] ?? SKETCH_FALLBACK;
  return <svg viewBox="0 0 180 126" role="img" aria-label={`${shape} in ${container}`}>
    <path className="catalog-sketch__boundary" d={outline(container)} transform="translate(90 63) scale(48)" />
    {positions.map(([x, y]) => <path key={`${x}:${y}`} d={outline(shape)} transform={`translate(${90 + x} ${63 + y}) scale(13)`} />)}
  </svg>;
}

/**
 * One published record of a subfamily: its figure first, then the numbers.
 *
 * The figure is the source's own drawing of that record — the one thing that shows
 * the configuration rather than naming it. It comes before the title so the panel
 * reads as a gallery of pictures with their measurements underneath, and a record
 * whose figure the source does not serve keeps its card and says so.
 */
function CatalogConfig(props: {
  canBuild: boolean;
  installed: boolean;
  onOpen: () => void;
  title: string;
  meta: string;
  formula: string;
  attribution: string;
  figure: string;
  figureLabel: string;
  action: string;
  /** Whether a source figure hotlinked here takes the catalogue's colour filter. */
  tintFigure: boolean;
  /**
   * What the record's published number cannot say. A launchable family whose
   * template measures something else than the source did wears it as a badge, so a
   * launcher never hides the mismatch behind a comparable-looking score.
   */
  caveat?: string;
}) {
  const body = <>
    <Figure url={props.figure} alt={props.figureLabel} tinted={props.tintFigure} />
    <span className="profile-catalog__card-title">{props.title}</span>
    <span className="profile-catalog__card-meta">{props.meta}</span>
    {props.caveat !== undefined && props.caveat !== "" && <span className="profile-catalog__config-caveat" role="note">{props.caveat}</span>}
    {props.formula !== "" && <span className="profile-catalog__config-formula">{props.formula}</span>}
    <span className="profile-catalog__config-attribution">{props.attribution}</span>
    <span className="profile-catalog__card-action">{props.action}{props.canBuild ? " ↗" : ""}</span>
  </>;
  return props.canBuild
    ? <button type="button" className="profile-catalog__config" onClick={props.onOpen}>{body}</button>
    : <div className="profile-catalog__config is-coming">{body}</div>;
}

/**
 * One generated subfamily: its published records, and what can be done with them.
 *
 * A record stands for every count its figure covers, so it is expanded into one
 * card per count: each card adds exactly one problem, with that count as its
 * seed. A subfamily the lab cannot build yet — the asset does not call it
 * supported, or the palette carries no unit shape for it — keeps its cards, so
 * the source stays readable, but they are not buttons.
 */
function CatalogFamily(props: {
  catalog: CopyCatalog | null;
  slug: string;
  /** The navigator family this subfamily is shown under. */
  section: string;
  palette: ShapeFamilyDoc[];
  localProblems: Record<string, ProblemDoc>;
  categoryProblemIds: string[];
  onAdd: (problem: ProblemDoc) => void;
  onBack: () => void;
  onClose: () => void;
}) {
  const { t, number } = useI18n();
  const catalog = props.catalog;
  const palette = props.palette;
  const family = catalog?.families.find((entry) => entry.slug === props.slug) ?? null;
  const back = <button type="button" className="profile-catalog__back" onClick={props.onBack}>← {t("All subfamilies")}</button>;
  if (catalog === null || family === null) {
    return <>{back}<div className="profile-catalog__pending"><strong>{t("Loading the catalogue…")}</strong></div></>;
  }
  const canBuild = copyable(family, palette);
  const configurations = copyConfigurations(family);
  const tintFigure = props.section !== PERIMETER_FAMILY;
  const status = (value: string) =>
    value === "proved" ? "Proved optimum" : value === "best_known" ? "Best known" : "Not proved";
  return <>
    {back}
    <div className="profile-catalog__result-heading">
      <div><span className="eyebrow">{t(props.section)}</span><h3>{t(family.title)}</h3></div>
      <small>{number(family.instances.length)} {t("instances")} · {t("Last checked")}: {catalog.generated}</small>
    </div>
    {family.intro && <p className="profile-catalog__intro" lang="en"><strong>{t("Source description")}:</strong> {family.intro}</p>}
    {!canBuild && <p className="profile-catalog__coming" role="note">
      <strong>{t("Coming soon")}</strong> — {t("This subfamily is listed for reference; the engine cannot judge it yet.")}</p>}
    {configurations.length === 0 && <p className="profile-catalog__hidden" role="note">{hiddenRecordsNote(t)}</p>}
    <div className="profile-catalog__configs">
      {configurations.map(({ count, instance }, index) => {
        const installed = props.localProblems[copyProblemId(family, count, instance.figure)] !== undefined
          || props.categoryProblemIds.includes(copyProblemId(family, count, instance.figure));
        const open = () => {
          props.onAdd(copyProblem(catalog, family, instance, count, palette));
          props.onClose();
        };
        return <CatalogConfig
          // A source typo can print one count beside two different figures — the
          // dominoes-in-squares page prints "3." for figure 5.png as well as for its
          // real n = 3 record — so the figure and the count are not enough to key the
          // cards apart; the position in the expanded list always is. The card still
          // shows the printed number: this is a React key, never a correction.
          key={`${index}:${instance.figure}:${count}`}
          canBuild={canBuild}
          installed={installed}
          onOpen={open}
          title={`${count} ${t(copyNoun(family.shape, count))}`}
          meta={instance.value === null
            ? t(status(instance.status))
            : `${t(props.section === PERIMETER_FAMILY
              ? family.shape === "circle" ? "total radius" : "total side"
              : MEASURES[instance.symbol] ?? "side")} ${number(instance.value, 5)} ${instance.symbol} · ${t(status(instance.status))}`}
          formula={instance.formula}
          caveat={t(family.caveat)}
          attribution={instance.attribution}
          figure={copyFigureUrl(family, instance)}
          figureLabel={t("Published figure")}
          action={t(canBuild ? (installed ? "Open profile" : "Add to category") : "Coming soon")}
          tintFigure={tintFigure}
        />;
      })}
    </div>
  </>;
}

/**
 * The source's own sentence for a curated record, rebuilt from what the page states.
 *
 * The generated catalogue carries its attribution verbatim; a curated record holds
 * the construction and the proof as separate fields, so the two are put back in the
 * source's order here, and a trivial grid falls back on its note.
 */
function squareAttribution(record: SquareRecord, t: (english: string) => string): string {
  const { author, date, proved_by, proof_date, note } = record.reference;
  const sentences: string[] = [];
  if (author !== "") sentences.push(`${t("Found by")} ${author}${date === "" ? "" : ` ${t("in")} ${date}`}.`);
  if (proved_by !== "") sentences.push(`${t("Proved by")} ${proved_by}${proof_date === "" ? "" : ` ${t("in")} ${proof_date}`}.`);
  return sentences.length > 0 ? sentences.join(" ") : note;
}

export function ProfileNavigator(props: Props) {
  const { t, number } = useI18n();
  // The one display rule (catalog.ts): a record whose own count is above
  // `MAX_VISIBLE_COUNT` is not listed, while the data itself stays complete.
  const squareRecords = SQUARE_RECORDS.filter((record) => withinVisibleCount(record.count));
  const [open, setOpen] = useState(false);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalog, setCatalog] = useState<CopyCatalog | null>(null);
  const [previews, setPreviews] = useState<Record<string, FamilyPreview>>({});
  const [palette, setPalette] = useState<ShapeFamilyDoc[]>([]);
  const [catalogError, setCatalogError] = useState("");
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [family, setFamily] = useState<string>(FAMILIES[0]);
  // The catalogue filters: "" means "all", and they narrow the tiles the navigator
  // lists without touching the asset. They live here, not on a subfamily, so they
  // survive opening and closing a subfamily and switching between the sections.
  const [shapeFilter, setShapeFilter] = useState("");
  const [containerFilter, setContainerFilter] = useState("");
  const [subfamily, setSubfamily] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState("");
  const [addingCategory, setAddingCategory] = useState(false);
  const [categoryDraft, setCategoryDraft] = useState("");
  const [categoryMenu, setCategoryMenu] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [renamingCategory, setRenamingCategory] = useState(false);
  const [renameDraft, setRenameDraft] = useState("");
  const root = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (props.guideReveal === "picker") {
      setCatalogOpen(false);
      setOpen(true);
    } else if (props.guideReveal === "catalog-list" || props.guideReveal === "catalog-family") {
      setOpen(false);
      setFamily(FAMILIES[0]);
      setShapeFilter("");
      setContainerFilter("");
      setSubfamily(props.guideReveal === "catalog-family" ? "cirincir" : null);
      setCatalogOpen(true);
    } else {
      setOpen(false);
      setCatalogOpen(false);
    }
  }, [props.guideReveal]);
  useEffect(() => { if (!catalogOpen) { setImporting(false); setImportError(""); } }, [catalogOpen]);
  // The catalogue is half a megabyte: it is fetched the first time the panel
  // opens, and once only — the asset is a constant, not something to poll. The
  // palette travels with it because the tan, the domino and the L have no unit
  // outline the browser may invent: theirs is the palette's own document, and a
  // family whose shape the palette does not carry is offered as a record only.
  useEffect(() => {
    if (!catalogOpen || catalog !== null) return;
    let live = true;
    setCatalogError("");
    Promise.all([
      loadCopyCatalog(),
      api.shapes().then((answer) => answer.shapes).catch(() => null),
      loadFamilyPreviews().catch(() => null),
    ])
      .then(([loaded, shapes, manifest]) => {
        if (!live) return;
        setCatalog(loaded);
        if (shapes !== null) setPalette(shapes);
        if (manifest !== null) setPreviews(manifest.families);
      })
      .catch((cause) => { if (live) setCatalogError(cause instanceof Error ? cause.message : String(cause)); });
    return () => { live = false; };
  }, [catalogOpen, catalog, catalogAttempt]);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (open && !root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); setCatalogOpen(false); }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  const current = props.categories.find((item) => item.id === props.categoryId) ?? props.categories[0];
  const names = new Map(props.examples.map((item) => [item.problem_id, item.name]));
  Object.values(props.localProblems).forEach((item) => names.set(item.problem_id, item.name));
  const currentName = props.problemId && current?.problemIds.includes(props.problemId)
    ? names.get(props.problemId) ?? props.problemId : t("Choose a problem");

  const addCategory = () => {
    const name = categoryDraft.trim();
    if (!name) return;
    props.onCreateCategory(name);
    setCategoryDraft("");
    setAddingCategory(false);
  };
  const renameCategory = () => {
    const name = renameDraft.trim();
    if (!current || !name) return;
    props.onRenameCategory(current.id, name);
    setRenamingCategory(false);
    setCategoryMenu(false);
  };

  // The filter options, and what they leave visible. Only the sections the navigator
  // shows contribute: "Other Packing Problems" is a reference section, not a tab.
  // The curated squares are added by hand because the asset does not list them.
  const listedSections = new Set(Object.values(SECTION_HEADINGS));
  const listedFamilies = (catalog?.families ?? []).filter((entry) => listedSections.has(entry.section));
  const shapeOptions = [...new Set(["square", ...listedFamilies.map((entry) => entry.shape)])].sort();
  const containerOptions = [...new Set(["square", ...listedFamilies.map((entry) => entry.container)])].sort();
  const matchesFilters = (shape: string, container: string) =>
    (shapeFilter === "" || shape === shapeFilter) && (containerFilter === "" || container === containerFilter);
  const sectionFamilies = listedFamilies.filter((entry) => entry.section === SECTION_HEADINGS[family]);
  const curatedVisible = family === "Packing equal copies" && matchesFilters("square", "square");
  const shownFamilies = sectionFamilies.filter((entry) => matchesFilters(entry.shape, entry.container)).length
    + (curatedVisible ? 1 : 0);
  const totalFamilies = sectionFamilies.length + (family === "Packing equal copies" ? 1 : 0);
  const filtered = shapeFilter !== "" || containerFilter !== "";
  // Changing a filter returns to the subfamily list: the open subfamily may no
  // longer match, and showing a tile the filter excludes would misstate the catalogue.
  const changeShapeFilter = (value: string) => { setShapeFilter(value); setSubfamily(null); };
  const changeContainerFilter = (value: string) => { setContainerFilter(value); setSubfamily(null); };
  const resetFilters = () => { setShapeFilter(""); setContainerFilter(""); setSubfamily(null); };

  return <div className="profile-picker" ref={root}>
    <button className="profile-picker__trigger" type="button" aria-expanded={open}
      onClick={() => setOpen((value) => !value)}>
      <span className="profile-picker__category-name">{t(current?.name ?? "Demonstration")}</span>
      <strong>{t(currentName)}</strong><span aria-hidden="true">⌄</span>
    </button>
    <button className="profile-picker__edit-trigger" type="button" aria-label={t("Edit current problem")}
      disabled={!props.problemId || !current?.problemIds.includes(props.problemId)}
      onClick={() => props.problemId && props.onEditProblem(props.problemId)}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 16-.6 4.6L8 20l11-11-4-4L4 16Zm9.5-9.5 4 4" /></svg>
    </button>
    {open && <div className="profile-picker__popover">
      <div className="profile-picker__categories">
        <h3>{t("Categories")}</h3>
        {props.categories.map((item) => <button key={item.id} type="button"
          className={item.id === props.categoryId ? "is-active" : ""}
          onClick={() => { props.onCategory(item.id); setCategoryMenu(false); setRenamingCategory(false); }}>{t(item.name)}<small>{item.problemIds.length}</small></button>)}
        {addingCategory ? <div className="profile-picker__new">
          <input autoFocus value={categoryDraft} aria-label={t("Category name")}
            onChange={(event) => setCategoryDraft(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") addCategory(); if (event.key === "Escape") setAddingCategory(false); }} />
          <button type="button" onClick={addCategory}>{t("Add")}</button>
        </div> : <button className="profile-picker__add" type="button" onClick={() => setAddingCategory(true)}>＋ {t("New category")}</button>}
      </div>
      <div className="profile-picker__profiles">
        <div className="profile-picker__profiles-heading"><h3>{t(current?.name ?? "Demonstration")}</h3>
          <button type="button" className="profile-picker__dots" aria-label={t("Category options")}
            onClick={() => { setCategoryMenu((value) => !value); setConfirmDelete(false); setRenamingCategory(false); }}>⋯</button>
        </div>
        {categoryMenu && <div className="profile-picker__category-menu">
          {renamingCategory ? <form onSubmit={(event) => { event.preventDefault(); renameCategory(); }}>
            <label htmlFor="category-rename">{t("Category name")}</label>
            <input id="category-rename" autoFocus maxLength={80} value={renameDraft}
              onChange={(event) => setRenameDraft(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Escape") setRenamingCategory(false); }} />
            <button type="submit" disabled={!renameDraft.trim()}>{t("Save")}</button>
            <button type="button" onClick={() => setRenamingCategory(false)}>{t("Cancel")}</button>
          </form> : confirmDelete ? <><span>{t("Delete this category?")}</span>
            <button className="profile-picker__delete" type="button" onClick={() => { if (current) props.onDeleteCategory(current.id); setConfirmDelete(false); setCategoryMenu(false); }}>{t("Delete category")}</button>
            <button type="button" onClick={() => setConfirmDelete(false)}>{t("Cancel")}</button></>
            : <><button type="button" onClick={() => { setRenameDraft(t(current?.name ?? "")); setRenamingCategory(true); }}>{t("Rename category")}</button>
              <button className="profile-picker__delete" type="button" disabled={props.categories.length < 2} onClick={() => setConfirmDelete(true)}>{t("Delete category")}</button></>}
        </div>}
        {current?.problemIds.length ? current.problemIds.map((id) => <div key={id} className={id === props.problemId ? "profile-picker__profile is-active" : "profile-picker__profile"}>
          <button type="button" className="profile-picker__profile-name"
            onClick={() => { props.onProblem(id); setOpen(false); }}>{t(names.get(id) ?? id)}</button>
          <button type="button" className="profile-picker__icon" aria-label={`${t("Edit problem")}: ${t(names.get(id) ?? id)}`}
            onClick={() => { props.onEditProblem(id); setOpen(false); }}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 16-.6 4.6L8 20l11-11-4-4L4 16Zm9.5-9.5 4 4" /></svg></button>
          <button type="button" className="profile-picker__icon" aria-label={`${t("Remove from category")}: ${t(names.get(id) ?? id)}`}
            onClick={() => props.onRemoveProblem(id)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m-9 0 1 13h10l1-13M10 11v6m4-6v6" /></svg></button>
        </div>) : <p>{t("No problem in this category yet.")}</p>}
        <button className="profile-picker__add" type="button" onClick={() => { setCatalogOpen(true); setOpen(false); }}>＋ {t("Add a problem")}</button>
      </div>
    </div>}
    {catalogOpen && createPortal(<div className="profile-catalog" role="dialog" aria-modal="true" aria-label={t("Problem catalog")}>
      <div className="profile-catalog__backdrop" onClick={() => setCatalogOpen(false)} />
      <div className="profile-catalog__sheet">
        <header><div><span className="eyebrow">PAPER OBS / {t("LIBRARY")}</span><h2>{t("Add a problem")}</h2>
          <p>{t("Choose a family, a configuration, then add it to the active category.")}</p>
          {/* One note replaces the per-card grid badge the owner found repetitive. */}
          <p className="profile-catalog__placements" role="note">{t("The exact placements are not known for most instances: the lab opens them on a grid construction, not on the published record.")}</p>
          <a className="profile-catalog__source" href={PACKING_INDEX} target="_blank" rel="noopener noreferrer">{t("Catalog source")}: Erich Friedman's Packing Center ↗</a></div>
          <button type="button" className="button" onClick={() => setCatalogOpen(false)}>{t("Close")}</button></header>
        <div className="profile-catalog__columns">
          <nav aria-label={t("Families")}>
            <h3>{t("Families")}</h3>
            {FAMILIES.map((item) => <button key={item} type="button" className={family === item ? "is-active" : ""}
              onClick={() => { setFamily(item); setSubfamily(null); }}>{t(item)}</button>)}
            <p className="profile-catalog__future" role="note">{t("More families will be added over time. Anyone can request a new family through GitHub Issues.")} <a href="https://github.com/OihanBarreneche/paper-obs/issues/new" target="_blank" rel="noopener noreferrer">{t("Request a family")} ↗</a></p>
            <div className="profile-catalog__custom-entry"><h3>{t("Custom problem")}</h3>
              <button type="button" onClick={() => { setCatalogOpen(false); props.onNewCustom(); }}>＋ {t("Create a custom problem")}</button>
              <button type="button" onClick={() => { setImporting(true); setImportError(""); }}>↑ {t("Import a problem")}</button></div>
          </nav>
          <section className="profile-catalog__results">
            {importing ? <div className="profile-catalog__import">
              <button type="button" className="profile-catalog__back" onClick={() => setImporting(false)}>← {t("Back to catalog")}</button>
              <h3>{t("Import a problem")}</h3>
              <p>{t("Use the JSON file created by Export problem. The engine validates it before adding it to this category.")}</p>
              <label htmlFor="import-problem-file">{t("Choose a JSON file")}</label>
              <input id="import-problem-file" type="file" accept=".json,application/json" onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void file.text().then((value) => { setImportText(value); setImportError(""); }).catch((cause) => setImportError(String(cause)));
              }} />
              <label htmlFor="import-problem-json">{t("Problem JSON")}</label>
              <textarea id="import-problem-json" className="input" rows={12} spellCheck={false} value={importText}
                onChange={(event) => { setImportText(event.target.value); setImportError(""); }} />
              {importError && <p className="profile-catalog__import-error" role="alert">{importError}</p>}
              <button type="button" className="button button--primary" disabled={!importText.trim()} onClick={() => {
                try {
                  const document: unknown = JSON.parse(importText);
                  void props.onImportProblem(document).then(() => { setCatalogOpen(false); setImporting(false); setImportText(""); })
                    .catch((cause) => setImportError(cause instanceof Error ? cause.message : String(cause)));
                } catch (cause) { setImportError(cause instanceof Error ? cause.message : String(cause)); }
              }}>{t("Import into category")}</button>
            </div> : subfamily === null ? <>
              {/* The two filters sit on the family list's own header line, as one
                  right-aligned horizontal row, and only there: a subfamily is opened
                  without them, so its records are never shown through a filter they
                  may no longer match. "all" is each select's default. */}
              <div className="profile-catalog__result-heading">
                <div><span className="eyebrow">{t(family)}</span><h3>{t("Subfamilies")}</h3></div>
                <div className="profile-catalog__filters">
                  <label className="profile-catalog__filter"><span>{t("shape")}</span>
                    <select value={shapeFilter} aria-label={t("shape")} onChange={(event) => changeShapeFilter(event.target.value)}>
                      <option value="">{t("All")}</option>
                      {shapeOptions.map((shape) => <option key={shape} value={shape}>{t(copyNoun(shape, 2))}</option>)}
                    </select>
                  </label>
                  <label className="profile-catalog__filter"><span>{t("container")}</span>
                    <select value={containerFilter} aria-label={t("container")} onChange={(event) => changeContainerFilter(event.target.value)}>
                      <option value="">{t("All")}</option>
                      {containerOptions.map((container) => <option key={container} value={container}>{t(CONTAINER_NOUNS[container] ?? container)}</option>)}
                    </select>
                  </label>
                  <small className="profile-catalog__filter-count">
                    {filtered && <button type="button" className="profile-catalog__filter-reset" onClick={resetFilters}>{t("Reset filters")}</button>}
                    <span>{number(shownFamilies)} / {number(totalFamilies)} {t("subfamilies")}</span>
                  </small>
                </div>
              </div>
              {catalog === null && catalogError === "" && <p className="profile-catalog__intro">{t("Loading the catalogue…")}</p>}
              {catalogError !== "" && <p className="profile-catalog__import-error" role="alert">
                {t("The catalogue could not be loaded.")} {catalogError}
                <button type="button" className="profile-catalog__back" onClick={() => setCatalogAttempt((value) => value + 1)}>{t("Retry")}</button></p>}
              {catalog !== null && shownFamilies === 0 && <p className="profile-catalog__intro">{t("No subfamily matches these filters.")}</p>}
              <div className="profile-catalog__overview">
                {curatedVisible && <button type="button" className="profile-catalog__subfamily" onClick={() => setSubfamily(SQUARES)}>
                  <span className="profile-catalog__subfamily-picture"><FamilyPicture preview={previews["squinsqu"]} shape="square" container="square" tinted /></span>
                  <span className="profile-catalog__subfamily-name">{t(SQUARES)}</span>
                  <span className="profile-catalog__subfamily-meta"><span>{number(SQUARE_RECORDS.length)} {t("instances")}</span><span>{t("Browse configurations")} ↗</span></span>
                </button>}
                {sectionFamilies.filter((entry) => matchesFilters(entry.shape, entry.container)).map((entry) => <button key={entry.slug} type="button"
                  className="profile-catalog__subfamily" onClick={() => setSubfamily(entry.slug)}>
                  <span className="profile-catalog__subfamily-picture"><FamilyPicture preview={previews[entry.slug]} shape={entry.shape} container={entry.container} tinted={family !== PERIMETER_FAMILY} /></span>
                  <span className="profile-catalog__subfamily-name">{t(entry.title)}</span>
                  <span className="profile-catalog__subfamily-meta"><span>{number(entry.instances.length)} {t("instances")}</span><span>{entry.supported ? t("Browse configurations") : t("Coming soon")} ↗</span></span>
                </button>)}
              </div>
            </> : subfamily === SQUARES && family === "Packing equal copies" ? <>
              <button type="button" className="profile-catalog__back" onClick={() => setSubfamily(null)}>← {t("All subfamilies")}</button>
              <div className="profile-catalog__result-heading"><div><span className="eyebrow">{t(family)}</span><h3>{t(subfamily)}</h3></div>
                <small>{t("Unit squares · smallest square container")}</small>
              </div>
              {/* The curated records wear the same card as every generated family:
                  the published figure first, then the numbers, then the action. */}
              {squareRecords.length === 0 && <p className="profile-catalog__hidden" role="note">{hiddenRecordsNote(t)}</p>}
              <div className="profile-catalog__configs">{squareRecords.map((record) => {
                const id = `squares-${record.count}-in-smallest-square`;
                const installed = current?.problemIds.includes(id) ?? false;
                return <CatalogConfig
                  key={record.count}
                  canBuild
                  installed={installed}
                  onOpen={() => { props.onAddSquare(record.count); setCatalogOpen(false); }}
                  title={`${record.count} ${t(record.count === 1 ? "square" : "squares")}`}
                  meta={`${t("side")} ${number(record.side, 5)} · ${t(record.reference.status === "proved" ? "Proved optimum" : "Best known")}`}
                  formula=""
                  attribution={squareAttribution(record, t)}
                  figure={record.reference.preview}
                  figureLabel={t("Published figure")}
                  tintFigure
                  action={t(installed ? "Open profile" : "Add to category")}
                />;
              })}</div>
            </> : <CatalogFamily catalog={catalog} slug={subfamily} section={family} palette={palette}
              localProblems={props.localProblems} categoryProblemIds={current?.problemIds ?? []}
              onAdd={props.onAddProblem} onBack={() => setSubfamily(null)} onClose={() => setCatalogOpen(false)} />}
          </section>
        </div>
      </div>
    </div>, document.body)}
  </div>;
}
