import React from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { applyDesignTokens } from "@/lib/designTokens";
import { App } from "./App";
import "./styles.css";

applyDesignTokens();

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* HashRouter so deep links work under file:// in the packaged app. */}
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>,
);
