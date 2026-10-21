import "@testing-library/jest-dom/vitest";

// jsdom lacks these; charts and layout need them.
class RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;
