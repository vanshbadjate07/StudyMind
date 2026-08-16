export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
export const ALLOWED_EXTENSIONS = [".pdf"];

export interface ValidationResult {
  valid: boolean;
  reason?: string;
}

export function validateFile(file: File): ValidationResult {
  const dotIndex = file.name.lastIndexOf(".");
  const extension = dotIndex === -1 ? "" : file.name.slice(dotIndex).toLowerCase();

  if (!ALLOWED_EXTENSIONS.includes(extension)) {
    return { valid: false, reason: "Only PDF files are supported." };
  }
  if (file.size === 0) {
    return { valid: false, reason: "This file is empty." };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    const limitMb = MAX_UPLOAD_BYTES / (1024 * 1024);
    return { valid: false, reason: `File exceeds the ${limitMb}MB limit.` };
  }
  return { valid: true };
}
