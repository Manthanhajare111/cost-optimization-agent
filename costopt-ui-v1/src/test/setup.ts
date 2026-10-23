import "@testing-library/jest-dom/vitest";

class ResizeObserverMock { observe() {} unobserve() {} disconnect() {} }
Object.defineProperty(globalThis, "ResizeObserver", { value: ResizeObserverMock, writable: true, configurable: true });
HTMLDialogElement.prototype.showModal = function showModal() { this.setAttribute("open", ""); };
HTMLDialogElement.prototype.close = function close() { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); };
