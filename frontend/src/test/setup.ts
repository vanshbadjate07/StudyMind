import '@testing-library/jest-dom/vitest'

// jsdom doesn't implement <dialog> modal behavior (showModal/close are no-ops
// or missing). Polyfill just enough for components using the native element.
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }
}
if (!HTMLDialogElement.prototype.close) {
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute('open')
  }
}

// jsdom doesn't implement scrollIntoView at all — components that
// auto-scroll (e.g. chat) call it in a layout effect regardless of test
// environment.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {}
}
