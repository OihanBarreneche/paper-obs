import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { I18nProvider } from "./i18n";
import "./styles.css";
import "./workbook.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("the page has no #root element to mount the application into");
}

createRoot(container).render(
  <StrictMode>
    <I18nProvider><App /></I18nProvider>
  </StrictMode>,
);
