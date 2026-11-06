import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { registry } from "./scene/registry";
import { app } from "./state/app";
import "./scene/bvh";
import "./theme.css";

// dev server only: the store and the registry for the console and browser tests
if (import.meta.env.DEV) Object.assign(window, { __metro: { app, registry } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
