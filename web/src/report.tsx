import React from "react";
import ReactDOM from "react-dom/client";
import { ReviewView } from "./ReviewView";
import type { ReviewBundle } from "./types";
import "./styles.css";

const source = document.getElementById("review-bundle")?.textContent;
if (!source) throw new Error("review bundle is missing");
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><ReviewView bundle={JSON.parse(source) as ReviewBundle} reportMode /></React.StrictMode>);
