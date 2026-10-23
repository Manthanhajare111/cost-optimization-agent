import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { setTheme } from "@ui5/webcomponents-base/dist/config/Theme.js";
import "@ui5/webcomponents-react/dist/Assets.js";
import App from "./App";
import "./styles.css";

setTheme("sap_horizon");

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
