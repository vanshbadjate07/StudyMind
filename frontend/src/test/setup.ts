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
