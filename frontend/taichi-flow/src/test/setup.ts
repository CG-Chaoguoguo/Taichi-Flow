import "@testing-library/jest-dom/vitest";
import "../index.css";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// react-resizable-panels observes its real DOM group in production. jsdom does
// not provide ResizeObserver, so give component tests the same no-op browser
// contract instead of failing before their assertions run.
if (typeof window.ResizeObserver === "undefined") {
  class TestResizeObserver implements ResizeObserver {
    constructor(_callback: ResizeObserverCallback) {}

    observe(_target: Element, _options?: ResizeObserverOptions): void {}
    unobserve(_target: Element): void {}
    disconnect(): void {}
  }

  Object.defineProperty(window, "ResizeObserver", {
    configurable: true,
    value: TestResizeObserver,
    writable: true,
  });
}

afterEach(() => cleanup());

if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
}
