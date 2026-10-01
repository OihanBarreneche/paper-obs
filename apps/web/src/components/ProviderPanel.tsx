/**
 * Choosing the model that will think, and where its key comes from.
 *
 * The backend describes its providers — a base URL, the name of the environment
 * variable holding a key, the models it serves — so this panel is a form over a
 * table it does not own: adding a provider to the backend adds an option here
 * without a line of TypeScript.
 *
 * The choice is kept in this browser, the key included (see `write`), and the
 * key is never written into a run document.
 */

import { useEffect, useState } from "react";

import { ApiError, api } from "../api";
import { useI18n } from "../i18n";
import type { ProviderDoc } from "../types";

import "./ProviderPanel.css";

/** Where this browser keeps the choice between sessions, the key included (see `write`). */
const STORAGE_KEY = "paper-obs.model";

/** The choice as this tab last read or wrote it, so the stored one is parsed once. */
let sessionSettings: ModelSettings | null = null;

/** What the panel holds: which provider, which model, and how to reach it. */
export type ModelSettings = {
  provider: string;
  model: string;
  baseUrl: string;
  /** Kept in this browser with the rest, never in a run document. */
  apiKey: string;
  /**
   * What a million tokens cost in and out, as typed.
   *
   * The lab ships no price list: a price ages badly, and a stale dollar figure is worse
   * than none. A run records tokens either way, and shows money only when a price came
   * with the run.
   */
  priceIn: string;
  priceOut: string;
  /** The price of input read from the provider's cache; empty bills it at `priceIn`. */
  priceCached: string;
  /**
   * The sampling temperature, as typed; empty keeps the run's default of 0. A higher one
   * lets two turns that open on the same state answer differently.
   */
  temperature: string;
};

/** The model option that opens a field for an id the lists do not hold; ids have no spaces. */
const TYPED = "typed id";

const EMPTY: ModelSettings = {
  provider: "",
  model: "",
  baseUrl: "",
  apiKey: "",
  priceIn: "",
  priceOut: "",
  priceCached: "",
  temperature: "",
};

function describe(cause: unknown): string {
  if (cause instanceof ApiError) {
    return cause.message;
  }
  return cause instanceof Error ? cause.message : String(cause);
}

/** Read the choice kept in this browser, the key included, or the empty one. */
export function readModelSettings(): ModelSettings {
  if (sessionSettings !== null) return sessionSettings;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) {
      return EMPTY;
    }
    const document = JSON.parse(raw) as Partial<ModelSettings>;
    const settings: ModelSettings = {
      provider: typeof document.provider === "string" ? document.provider : "",
      model: typeof document.model === "string" ? document.model : "",
      baseUrl: typeof document.baseUrl === "string" ? document.baseUrl : "",
      apiKey: typeof document.apiKey === "string" ? document.apiKey : "",
      priceIn: typeof document.priceIn === "string" ? document.priceIn : "",
      priceOut: typeof document.priceOut === "string" ? document.priceOut : "",
      priceCached: typeof document.priceCached === "string" ? document.priceCached : "",
      temperature: typeof document.temperature === "string" ? document.temperature : "",
    };
    sessionSettings = settings;
    return settings;
  } catch {
    return EMPTY;
  }
}

/**
 * Keep the choice in this browser, the key included.
 *
 * A local lab whose owner stops and starts it all day: retyping a key after every refresh is
 * friction with nothing behind it while the page is served on localhost to one person. The
 * key is therefore stored beside the provider and the prices, and the dialog can still forget
 * it in one click. It is never written into a run document — that guarantee is about the files
 * a run leaves behind, and it costs the reader nothing.
 */
function write(settings: ModelSettings): void {
  sessionSettings = settings;
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        provider: settings.provider,
        model: settings.model,
        baseUrl: settings.baseUrl,
        apiKey: settings.apiKey,
        priceIn: settings.priceIn,
        priceOut: settings.priceOut,
        priceCached: settings.priceCached,
        temperature: settings.temperature,
      }),
    );
  } catch {
    // A browser that refuses storage is not a reason to refuse the choice.
  }
}

/** Forget the stored key, leaving the provider, the model and the prices alone. */
export function forgetSessionKey(): void {
  if (sessionSettings !== null) {
    sessionSettings = { ...sessionSettings, apiKey: "" };
    write(sessionSettings);
  }
}

export type ProviderPanelProps = {
  /** Whether the dialog is up; a closed panel renders nothing at all. */
  open: boolean;
  onClose: () => void;
};

export function ProviderPanel({ open, onClose }: ProviderPanelProps) {
  const { t } = useI18n();
  const [providers, setProviders] = useState<ProviderDoc[]>([]);
  const [keyPresent, setKeyPresent] = useState<Record<string, boolean>>({});
  const [settings, setSettings] = useState<ModelSettings>(readModelSettings);
  const [discovered, setDiscovered] = useState<string[] | null>(null);
  const [typing, setTyping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!open || loaded) {
      return;
    }
    let live = true;
    void (async () => {
      try {
        const answer = await api.providers();
        if (!live) {
          return;
        }
        setProviders(answer.providers);
        setKeyPresent(answer.key_present.providers);
        setSettings((current) => {
          const name = current.provider === "" ? answer.providers[0]?.name ?? "" : current.provider;
          const chosen = answer.providers.find((item) => item.name === name);
          return {
            ...current,
            provider: name,
            model: current.model === "" ? chosen?.models[0] ?? "" : current.model,
          };
        });
        setLoaded(true);
      } catch (cause) {
        if (live) {
          setError(describe(cause));
        }
      }
    })();
    return () => {
      live = false;
    };
  }, [open, loaded]);

  const chosen = providers.find((item) => item.name === settings.provider) ?? null;
  const needsKey = chosen === null ? true : chosen.needs_key;
  const keyReady = chosen !== null && keyPresent[chosen.name] === true;
  const needsBaseUrl = chosen !== null && chosen.base_url === "";
  // The provider table's ids come first; what the provider itself lists joins them, and any
  // other id can still be typed, so a stale default is never the only option.
  const knownModels = chosen?.models ?? [];
  const listedModels = (discovered ?? []).filter((name) => !knownModels.includes(name));
  const typed = typing || (settings.model !== "" && ![...knownModels, ...listedModels].includes(settings.model))
    || knownModels.length + listedModels.length === 0;

  if (!open) {
    return null;
  }

  const aboutKey = keyReady
    ? `${t("Key configured in the environment")} (${chosen?.api_key_env}).`
    : needsKey
      ? `${t("Enter a key for")} ${chosen?.name} (${chosen?.api_key_env}).`
      : t("No key required.");

  const discover = async () => {
    if (chosen === null) {
      return;
    }
    setError(null);
    try {
      const answer = await api.providerModels({
        provider: chosen.name,
        api_key: settings.apiKey === "" ? undefined : settings.apiKey,
        base_url: needsBaseUrl && settings.baseUrl !== "" ? settings.baseUrl : undefined,
      });
      setDiscovered(answer.models);
    } catch (cause) {
      setError(describe(cause));
    }
  };

  return (
    <div className="modal">
      <section className="modal__panel" role="dialog" aria-label={t("model")}>
        <div className="modal__body">
          <h2 className="panel__title">{t("Model")}</h2>
          <p className="muted">
            {t("Choose a provider and a model. Your key is kept in this browser and never written into a run file.")}
          </p>
          {error !== null && <p className="provider-panel__error">{t(error)}</p>}
          {chosen !== null && <p className="muted">{aboutKey}</p>}
          <div className="grid-2">
            <label className="field">
              <span className="field__label">{t("provider")}</span>
              <select
                className="select"
                value={settings.provider}
                onChange={(event) => {
                  const name = event.target.value;
                  const next = providers.find((item) => item.name === name);
                  setDiscovered(null);
                  setTyping(false);
                  setError(null);
                  setSettings((current) => ({
                    ...current,
                    provider: name,
                    model: next?.models[0] ?? "",
                  }));
                }}
              >
                {providers.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="field">
              <span className="field__label">{t("model")}</span>
              <span className="provider-panel__model">
                <select
                  className="select"
                  aria-label={t("model")}
                  value={typed ? TYPED : settings.model}
                  onChange={(event) => {
                    const value = event.target.value;
                    setTyping(value === TYPED);
                    if (value !== TYPED) setSettings((current) => ({ ...current, model: value }));
                  }}
                >
                  {knownModels.length > 0 && <optgroup label={t("Known models")}>
                    {knownModels.map((name) => <option key={name} value={name}>{name}</option>)}
                  </optgroup>}
                  {listedModels.length > 0 && <optgroup label={t("Listed by the provider")}>
                    {listedModels.map((name) => <option key={name} value={name}>{name}</option>)}
                  </optgroup>}
                  <option value={TYPED}>{t("Other: type an identifier…")}</option>
                </select>
                {typed && <input
                  className="input provider-panel__typed"
                  aria-label={t("Type the exact model identifier")}
                  value={settings.model}
                  spellCheck={false}
                  placeholder={t("Type the exact model identifier")}
                  onChange={(event) =>
                    setSettings((current) => ({ ...current, model: event.target.value }))
                  }
                />}
                {discovered !== null && <span className="provider-panel__listed">
                  {discovered.length} {t("models listed by the provider")}
                </span>}
              </span>
            </div>
            {needsBaseUrl && (
              <label className="field">
                <span className="field__label">{t("base url")}</span>
                <input
                  className="input"
                  value={settings.baseUrl}
                  spellCheck={false}
                  placeholder="https://…"
                  onChange={(event) =>
                    setSettings((current) => ({ ...current, baseUrl: event.target.value }))
                  }
                />
              </label>
            )}
            <label className="field">
              <span className="field__label">{t("price / M in")}</span>
              <input
                className="input input--narrow"
                inputMode="decimal"
                value={settings.priceIn}
                spellCheck={false}
                placeholder={t("optional")}
                title={t("Price per million input tokens")}
                onChange={(event) =>
                  setSettings((current) => ({ ...current, priceIn: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span className="field__label">{t("price / M cached in")}</span>
              <input
                className="input input--narrow"
                inputMode="decimal"
                value={settings.priceCached}
                spellCheck={false}
                placeholder={t("optional")}
                title={t("Price per million input tokens read from the provider's cache (cache hit); empty bills them at the input price")}
                onChange={(event) =>
                  setSettings((current) => ({ ...current, priceCached: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span className="field__label">{t("price / M out")}</span>
              <input
                className="input input--narrow"
                inputMode="decimal"
                value={settings.priceOut}
                spellCheck={false}
                placeholder={t("optional")}
                title={t("Price per million output tokens")}
                onChange={(event) =>
                  setSettings((current) => ({ ...current, priceOut: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span className="field__label">{t("temperature")}</span>
              <input
                className="input input--narrow"
                inputMode="decimal"
                value={chosen?.accepts_temperature === false ? "" : settings.temperature}
                disabled={chosen?.accepts_temperature === false}
                spellCheck={false}
                placeholder="0"
                title={t(chosen?.accepts_temperature === false
                  ? "This endpoint refuses a temperature: its own default is used"
                  : "From 0 to 2: a higher temperature lets turns that start alike answer differently")}
                onChange={(event) =>
                  setSettings((current) => ({ ...current, temperature: event.target.value }))
                }
              />
            </label>
            {needsKey && (
              <label className="field">
                <span className="field__label">{t("key")}</span>
                <input
                  className="input"
                  type="password"
                  name="paper-obs-api-key"
                  autoComplete="new-password"
                  value={settings.apiKey}
                  spellCheck={false}
                  placeholder={t(keyReady ? "already in the environment" : "typed here")}
                  onChange={(event) =>
                    setSettings((current) => ({ ...current, apiKey: event.target.value }))
                  }
                />
              </label>
            )}
          </div>
          {needsKey && (
            <p className="muted">
              {t("This key is kept in this browser and sent to this server for the runs you start; it is never written into a run document.")}{" "}
              <button
                type="button"
                className="button button--ghost"
                disabled={settings.apiKey === ""}
                onClick={() => {
                  forgetSessionKey();
                  setSettings((current) => ({ ...current, apiKey: "" }));
                }}
              >
                {t("Forget key")}
              </button>
            </p>
          )}
          {chosen !== null && <p className="muted">{t(chosen.note)}</p>}
        </div>
        <div className="modal__actions">
          <button
            type="button"
            className="button button--ghost"
            // Some catalogues answer without a key (OpenRouter's); one that needs a key says so.
            disabled={chosen === null}
            onClick={() => void discover()}
          >
            {t("Fetch the model list")}
          </button>
          <button type="button" className="button button--ghost" onClick={onClose}>
            {t("Close")}
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => {
              write(settings);
              onClose();
            }}
          >
            {t("Save")}
          </button>
        </div>
      </section>
    </div>
  );
}
